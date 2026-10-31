from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import pandas as pd

from comum.dominio.classificadores import agregar_remuneracoes
from comum.config.configuration import ANO_MES_REFERENCIA
from comum.config import constantes as const
from comum.config.logger_config import logger
from comum.dominio.referencia_do_arquivo import referencia_do_arquivo
from comum.arquivos.gerenciador import carregar_dados
from comum.dados import tabelas
from comum.dados.repositorio_tabelas import bd_tabelas

# Códigos de erro gravados na coluna `codigo_erro`.
#
# ⚠️ **Provisórios.** O de-para oficial de códigos de erro nunca foi informado
# pelo cliente — a V2 não traz nenhuma tabela de códigos. Até 2026-08-04 existia
# um único valor fixo para toda e qualquer falha, o que tornava a coluna inútil
# para diagnóstico. Estes distinguem as categorias que o código **já** conhece;
# quando o de-para real chegar, é aqui que ele entra.
COD_ERRO_VALIDACAO = "ERR_VALIDACAO_PROCESSAMENTO"
COD_ERRO_LEITURA = "ERR_LEITURA_ARQUIVO"



@dataclass(frozen=True)
class _Layout:
    """Onde cada campo está, por tipo de arquivo.

    🔴 **Circulam dois formatos sob o nome "expectativa" (25/09/2026).**

    * `_LAYOUT_DETRAF` — o Detraf comum, 21 colunas, `Rel` na 5, `R$_Bruto` na
      14. É também o formato dos arquivos que a Vivo gera como
      `DETRAF_FINAL_VIVO_..._D.csv`, os quatro que estão em `arquivos/`.
    * `_LAYOUT_EXPECTATIVA` — o que sai do ICT, com `GROUP_CREDORA` no início e
      `PARTE_TARIFADA` no meio, tudo deslocado (ver `constantes.py`).

    ⚠️ **Qual deles usar NÃO se decide pelo nome do lote.** Em 24/09 foi o que
    eu fiz, e errou o caso mais comum: nos quatro arquivos do repositório o
    filtro de `Rel` acha 8.275 / 249 / 52 / 355 linhas na coluna 5 e **zero**
    na coluna 6. O arquivo saía vazio do filtro, a extração caía nos
    `dados_padrao`, e os 562 registros do ponto 5 da Luciana continuavam com
    `remuneracoes` nulo — o sintoma que a mudança deveria ter curado.

    Quem decide é `_layout_do_conteudo`, pela própria coluna `Rel`.

    ⚠️ `r_bruto = None` no layout do ICT não é omissão: **aquele** arquivo não
    tem a coluna, termina em `VALOR_LIQUIDO` (pendência N3). Preencher
    `valor_bruto_desp` com o líquido seria gravar uma coisa no lugar de outra,
    em silêncio. Fica zero, e o log diz por quê. O arquivo da Vivo tem
    `R$_Bruto` e é somado normalmente.
    """

    credora: int
    devedora: int
    referencia: int
    rel: int
    descritor: int
    minutos: int
    r_bruto: int | None


_LAYOUT_DETRAF = _Layout(
    credora=const.COL_CREDORA,
    devedora=const.COL_DEVEDORA,
    referencia=const.COL_REFERENCIA,
    rel=const.COL_REL,
    descritor=const.COL_DESCRITOR,
    minutos=const.COL_MINUTOS,
    r_bruto=const.COL_R_BRUTO,
)

_LAYOUT_EXPECTATIVA = _Layout(
    credora=const.EXPECTATIVA_COL_CREDORA,
    devedora=const.EXPECTATIVA_COL_DEVEDORA,
    referencia=const.EXPECTATIVA_COL_REFERENCIA,
    rel=const.EXPECTATIVA_COL_REL,
    descritor=const.EXPECTATIVA_COL_DESCRITOR,
    minutos=const.EXPECTATIVA_COL_MINUTOS,
    r_bruto=const.EXPECTATIVA_COL_R_BRUTO,
)


#: Indicador de linha de TRÁFEGO na coluna `Rel` — o resto é linha de total.
_VALORES_REL_DE_TRAFEGO = ["00", "0", 0]


def _layout_do_conteudo(df, preferido: "_Layout", nome_arquivo: str) -> "_Layout":
    """Escolhe o layout olhando o ARQUIVO, não o nome do lote.

    🔴 Correção de 2026-09-25. Circulam **dois** formatos sob o nome
    "expectativa":

    * o que a Vivo gera como `DETRAF_FINAL_VIVO_..._D.csv`, que é um Detraf
      comum — 21 colunas, `Rel` na 5, `R$_Bruto` na 14;
    * o que sai do ICT, com `GROUP_CREDORA` e `PARTE_TARIFADA` a mais, tudo
      deslocado e **sem** `R$_Bruto` (pendência N3).

    Decidir pelo nome do lote acerta um e erra o outro, e o erro é silencioso:
    o filtro de `Rel` lê a coluna errada, não sobra linha, e o registro vai
    para o banco como "Validado" com `remuneracoes` nulo e volumetria zerada.
    Foi o que manteve os 562 registros vazios do ponto 5 da Luciana.

    A coluna `Rel` é o próprio desempate: só ela vale "00"/"0" nas linhas de
    tráfego. Testa-se o candidato preferido primeiro e, se ele não encontra
    nenhuma linha de tráfego, o outro.
    """
    candidatos = [preferido] + [
        outro
        for outro in (_LAYOUT_DETRAF, _LAYOUT_EXPECTATIVA)
        if outro is not preferido
    ]
    for candidato in candidatos:
        if candidato.rel >= df.shape[1]:
            continue
        if df.iloc[:, candidato.rel].isin(_VALORES_REL_DE_TRAFEGO).any():
            if candidato is not preferido:
                logger.info(
                    f"[{nome_arquivo}] layout do conteúdo difere do esperado "
                    f"pelo lote: lendo `Rel` na coluna {candidato.rel}."
                )
            return candidato
    return preferido


#: Sufixo que a validação acrescenta ao nome do arquivo em disco.
#:
#: 🔴 **Só para os arquivos de origem Vivo (29/09/2026).** O pedido do sufixo
#: (ponto 5 do e-mail de 23/09) estava na seção da expectativa, e nós o
#: aplicamos a tudo. O e-mail de 29/09 separa as duas famílias e é explícito
#: sobre a primeira:
#:
#:     "O RPA não pode promover nenhuma alteração nos arquivos recebidos nos
#:      e-mails. Exemplo: expectativa-telefonica-brasil-smp-c-vc1-202607_ERRO.xlsx
#:      — o nome do arquivo na tabela está com _ERRO no final, diferente do
#:      arquivo original na pasta 33."
#:
#: O Detraf que a operadora manda é insumo de terceiro: o nome dele é o que ela
#: escreveu, no disco e no banco. Os lotes `DETRAF_*` ficam de fora do mapa de
#: propósito — `_nome_com_sufixo` devolve o nome original para quem não está
#: aqui.
_SUFIXO_POR_LOTE = {
    "EXPECTATIVA_SUCESSO": "_EXP",
    "EXPECTATIVA_ERRO": "_ERRO",
}


def _nome_com_sufixo(path_arquivo: Path, tipo_lote: str) -> str:
    """O nome que o arquivo TERÁ em disco, com `_EXP` ou `_ERRO`.

    🔴 **A ordem enganava o banco (24/09/2026).** A validação renomeia os
    arquivos depois de registrá-los (`renomear_arquivos_processados`), então
    `path_arquivo.name` aqui ainda é o nome antigo — e o banco guardava um nome
    que já não existia no disco.

    Foi o ponto 5 do e-mail da Luciana de 23/09, *"não foram renomeados como
    orientado"*: a consulta mostrou **0 de 564** registros de expectativa com o
    sufixo. Os arquivos estavam renomeados; o banco é que apontava para o nome
    anterior, e quem fosse procurar o arquivo a partir da tabela não o acharia.

    Deriva o nome em vez de esperar o rename porque o registro acontece antes:
    inverter a ordem mudaria o fluxo da validação por uma questão de rótulo.

    Idempotente — arquivo que já chega com o sufixo não ganha outro.
    """
    sufixo = _SUFIXO_POR_LOTE.get(tipo_lote)
    if not sufixo or path_arquivo.stem.upper().endswith(sufixo):
        return path_arquivo.name
    return f"{path_arquivo.stem}{sufixo}{path_arquivo.suffix}"


class LeituraDetrafFalhou(RuntimeError):
    """O arquivo não pôde ser lido — distinto de "lido e sem tráfego"."""


def _arredondar(valor) -> Optional[float]:
    """Arredonda para 2 casas, preservando `None` (leitura falhou)."""
    return None if valor is None else round(float(valor), 2)


def obter_codigo_erro(path_arquivo: Path) -> str:
    """
    Código de erro de um arquivo que caiu no fluxo `_ERRO`.

    Ainda não há de-para oficial (ver o bloco de constantes acima), então a
    categoria vem do que o chamador sabe: este é o caso "arquivo validado e
    reprovado", distinto de "arquivo não pôde ser lido".
    """
    return COD_ERRO_VALIDACAO


class TransformadorRelatorioRPA:
    def __init__(self):
        """
        Inicializa o transformador de relatórios para o banco de dados.

        :param repositorio_cache: Instância da classe RepositorioCache (contém o método validar_eot e o anexo 5)
        :param periodo_fixo: String de período vinda do config.py (Ex: "202604")
        :param carregar_dados_funcao: Referência para a sua função existente 'carregar_dados'
        """
        self.repositorio_tabelas = bd_tabelas
        self.periodo = ANO_MES_REFERENCIA

        # Garante o acesso direto à tabela do anexo 5 tratada em memória
        self.tbl_anexo5 = self.repositorio_tabelas.tbl_anexo5_processado

    def _obter_tipo_servico(self, nome_fantasia: Optional[str]) -> Optional[str]:
        """Busca o Tipo de Serviço no Anexo 5 a partir do Nome Fantasia.

        As colunas vêm de ``tabelas.COL_ANEXO5_*``: no banco real elas **não têm
        acento**, e até 2026-08-06 esta linha procurava ``"Tipo de Serviço"``
        acentuado — ``KeyError`` em toda execução contra o MySQL de verdade.
        """
        if not nome_fantasia:
            return None

        # Filtra a tabela em memória para capturar o Tipo de Serviço correspondente
        resultado = self.tbl_anexo5[
            self.tbl_anexo5[tabelas.COL_ANEXO5_NOME_FANTASIA] == nome_fantasia
        ]
        if resultado.empty:
            return None

        return resultado.iloc[0][tabelas.COL_ANEXO5_TIPO_SERVICO]

    def _extrair_dados_internos(
        self,
        path_arquivo: Path,
        layout: "_Layout | None" = None,
    ) -> dict:
        """
        Abre o arquivo, remove as linhas de totais e extrai volumetria e chaves.

        `layout` é o palpite vindo do lote; o layout de verdade sai do conteúdo
        (`_layout_do_conteudo`), e é dele que vem a coluna da Referência, de
        onde sai o `periodo` — ver o comentário em `preparar_lote`.

        Raises:
            LeituraDetrafFalhou: Se o arquivo não puder ser lido ou interpretado.

        ⚠️ **Zero não é o mesmo que "não consegui ler".** Até 2026-08-04 uma falha
        de I/O caía nos `dados_padrao` — o registro ia para o banco com minutos e
        valor bruto zerados e o arquivo era marcado como processado. Zero é um
        resultado **legítimo** (operadora sem tráfego no mês), então ninguém
        conseguiria distinguir os dois casos depois.

        Os `dados_padrao` continuam valendo para o arquivo que foi **lido com
        sucesso** e não tem linha de tráfego — aí o zero é a resposta correta.
        """
        dados_padrao = {
            "empresa": None,
            "tipo_servico_operadora": None,
            "tipo_servico_vivo": None,
            "remuneracoes": None,
            "minuto_desp": 0.0,
            "valor_bruto_desp": 0.0,
            # 🔴 Pedido da Vivo (21/09/2026): o total de LINHAS do arquivo, não
            # de minutos. Existe porque o produto SMS tem `minutos = 0` — sem
            # esta coluna, um Detraf de SMS com mil registros é indistinguível
            # de um arquivo sem tráfego nenhum.
            "qtde_desp": 0,
            # Sem arquivo legível não há referência de dentro dele: a
            # competência da execução é o fallback (2026-09-24).
            "periodo": self.periodo,
        }

        try:
            # Uso obrigatório da função existente do projeto (Regra 2)
            df = carregar_dados(path_arquivo)

            if df is None or df.empty:
                return dados_padrao

            # O layout sai do conteúdo, não do nome do lote — e tem que ser
            # resolvido ANTES da referência, que também depende dele.
            layout = _layout_do_conteudo(
                df, layout or _LAYOUT_DETRAF, path_arquivo.name
            )

            # A referência vem do arquivo INTEIRO, antes de tirar os totais: o
            # arquivo só de totais ainda pode ter a coluna preenchida, e o que
            # importa aqui é o carimbo, não a volumetria (2026-09-24, Luciana).
            periodo = referencia_do_arquivo(
                df,
                self.periodo,
                nome_arquivo=path_arquivo.name,
                indice_coluna=layout.referencia,
            )
            dados_padrao["periodo"] = periodo

            # REGRA DE NEGÓCIO: Remover as linhas de totais pela coluna `Rel`.
            # Mantém só os registros puros, cujo indicador é '00', '0' ou 0.
            df_filtrado = df[
                df.iloc[:, layout.rel].isin(_VALORES_REL_DE_TRAFEGO)
            ].copy()

            if df_filtrado.empty:
                return dados_padrao

            # Linhas de tráfego, já sem os totais — é o que a Vivo quer contar.
            qtde_desp = int(len(df_filtrado))

            # Captura da primeira linha de dados purificados para extração de chaves de metadados
            primeira_linha = df_filtrado.iloc[0]

            # 1. Tratamento da Operadora Credora (Coluna Índice 0) -> Empresa e Serviço Operadora
            eot_credora = str(primeira_linha.iloc[layout.credora]).strip()
            nome_fantasia_credora = self.repositorio_tabelas.validar_eot(eot_credora)

            # 2. Tratamento da Operadora Devedora (Coluna Índice 1) -> Serviço Vivo
            eot_devedora = str(primeira_linha.iloc[layout.devedora]).strip()
            nome_fantasia_devedora = self.repositorio_tabelas.validar_eot(eot_devedora)

            # 3. Remunerações do arquivo (Coluna Índice 6) — TODAS as linhas.
            #
            # 🔴 Corrigido em 2026-09-24 (e-mail da Luciana, 23/09/2026:
            # `remuneracoes` nulo nos registros "Validado"). Até aqui só o
            # descritor da PRIMEIRA linha era classificado, e pela regra de
            # tarifa — que devolve `None` para tudo que não termina em V, L,
            # C ou I. Todo Detraf de SMS (`SENS`, final S) ia para o banco
            # sem remuneração, e um arquivo com TU-RL e VU-M saía só com o da
            # linha 1. Agora vai o conjunto distinto, ordenado, unido por `;`
            # (`TU-RL;VU-M`); SMS sai `TIS`; sem regra sai `NAO_REGULADO`.
            remuneracao_classificada = agregar_remuneracoes(
                df_filtrado.iloc[:, layout.descritor], contexto=path_arquivo.name
            )

            # 4. Volumetria Financeira e de Tráfego (Somas das colunas de Índice 9 e 14)
            total_minutos = pd.to_numeric(
                df_filtrado.iloc[:, layout.minutos]
                .astype(str)
                .str.replace(",", ".", regex=False),
                errors="coerce",
            ).sum()

            # ⚠️ A expectativa Vivo NÃO tem coluna de R$_Bruto — termina em
            # `VALOR_LIQUIDO` (pendência N3). Zero aqui é honesto: gravar o
            # líquido numa coluna chamada bruto seria trocar uma coisa por
            # outra em silêncio, e é justamente sobre R$_Bruto que a apuração
            # compara.
            if layout.r_bruto is None:
                logger.info(
                    f"[{path_arquivo.name}] layout sem coluna de R$_Bruto — "
                    f"`valor_bruto_desp` fica 0 (pendência N3, correção na origem)."
                )
                total_valor_bruto = 0.0
            else:
                total_valor_bruto = pd.to_numeric(
                    df_filtrado.iloc[:, layout.r_bruto]
                    .astype(str)
                    .str.replace(",", ".", regex=False),
                    errors="coerce",
                ).sum()

            return {
                "empresa": nome_fantasia_credora,
                "tipo_servico_operadora": self._obter_tipo_servico(
                    nome_fantasia_credora
                ),
                "tipo_servico_vivo": self._obter_tipo_servico(nome_fantasia_devedora),
                "remuneracoes": remuneracao_classificada,
                "minuto_desp": total_minutos,
                "valor_bruto_desp": total_valor_bruto,
                "qtde_desp": qtde_desp,
                "periodo": periodo,
            }

        except Exception as erro:
            raise LeituraDetrafFalhou(
                f"Não foi possível ler o arquivo [{path_arquivo.name}]: {erro}"
            ) from erro

    def preparar_lote(self, lista_arquivos: list[Path], tipo_lote: str) -> pd.DataFrame:
        """
        Método principal: Recebe a lista de Paths e o tipo de lote mapeado pelo RPA,
        retornando o DataFrame estruturado pronto para inserção direta no banco.

        :param tipo_lote: Pode ser 'DETRAF_SUCESSO', 'DETRAF_ERRO', 'EXPECTATIVA_SUCESSO', 'EXPECTATIVA_ERRO'
        """
        registros_processados = []

        agora_formatado = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(
            f"Iniciando transformação de lote tipo [{tipo_lote}] com {len(lista_arquivos)} arquivo(s)."
        )

        for path_obj in lista_arquivos:
            # DETERMINAÇÃO DE MATRIZ DE STATUS E ENUMS CONFORME REGRA DE NEGÓCIO
            logger.warning(
                f"ARQUIVO RECEBIDO PELO TRANSFORMADOR: {path_obj.name}"
            )

            if tipo_lote == "DETRAF_SUCESSO":
                tipo_registro = "DETRAF"
                status = "Validado"
                codigo_erro = None
            elif tipo_lote == "DETRAF_ERRO":
                tipo_registro = "DETRAF"
                status = "Não validado"
                codigo_erro = None
            elif tipo_lote == "EXPECTATIVA_SUCESSO":
                tipo_registro = "EXPECTATIVA"
                status = "Validado"
                codigo_erro = None
            elif tipo_lote == "EXPECTATIVA_ERRO":
                tipo_registro = "ERRO"
                status = "Não validado"
                codigo_erro = obter_codigo_erro(path_obj)
            else:
                logger.warning(
                    f"Tipo de lote desconhecido: {tipo_lote}. Ignorando arquivo."
                )
                continue

            # A falha de leitura não zera o registro: ela o marca como não
            # validado, com código próprio. Zero é resultado legítimo de uma
            # operadora sem tráfego, e confundir os dois apaga a diferença.
            # 🔴 `periodo` = a Referência que está DENTRO do arquivo (2026-09-24,
            # e-mail da Luciana de 23/09): "Arquivos com o período 202608 estão
            # com o campo período na tabela 202607. O período de referência
            # deve ser preenchido de acordo com a referência do arquivo." Até
            # aqui ia `ANO_MES_REFERENCIA`, a competência da execução — fixa em
            # 202607 desde 16/09 para a massa de agosto. Ela continua dizendo
            # ao RPA 2 qual mês apurar; só o carimbo gravado muda. A coluna
            # depende do layout, e o lote só dá o PALPITE inicial: quem decide
            # é o conteúdo do arquivo (ver `_layout_do_conteudo`).
            eh_expectativa = tipo_lote.startswith("EXPECTATIVA")
            layout_do_lote = _LAYOUT_EXPECTATIVA if eh_expectativa else _LAYOUT_DETRAF
            try:
                dados_internos = self._extrair_dados_internos(
                    path_obj, layout=layout_do_lote
                )
            except LeituraDetrafFalhou as erro:
                logger.error(
                    f"[{tipo_lote}] {erro} — registrando como não validado "
                    f"({COD_ERRO_LEITURA}), sem volumetria."
                )
                dados_internos = {
                    "empresa": None,
                    "tipo_servico_operadora": None,
                    "tipo_servico_vivo": None,
                    "remuneracoes": None,
                    "minuto_desp": None,
                    "valor_bruto_desp": None,
                    # `None`, não 0: não conseguimos ler, então não contamos.
                    "qtde_desp": None,
                    # Ilegível: não há referência de dentro do arquivo; cai na
                    # competência da execução (fallback, 2026-09-24).
                    "periodo": self.periodo,
                }
                status = "Não validado"
                codigo_erro = COD_ERRO_LEITURA
                logger.warning(
                    f"[{path_obj.name}] Sem leitura, o campo `periodo` cai na "
                    f"competência da execução: {self.periodo}."
                )

            linha_tabela = {
                "tipo_registro": tipo_registro,
                "nome_arquivo": _nome_com_sufixo(path_obj, tipo_lote),
                "periodo": dados_internos["periodo"],
                "empresa": dados_internos["empresa"],
                "tipo_servico_operadora": dados_internos["tipo_servico_operadora"],
                "tipo_servico_vivo": dados_internos["tipo_servico_vivo"],
                "remuneracoes": dados_internos["remuneracoes"],
                # `None` quando a leitura falhou — distinto do 0.0 de quem foi
                # lido e não tem tráfego.
                "minuto_desp": _arredondar(dados_internos["minuto_desp"]),
                "valor_bruto_desp": _arredondar(dados_internos["valor_bruto_desp"]),
                "qtde_desp": dados_internos["qtde_desp"],
                "status": status,
                "codigo_erro": codigo_erro,
                "created_at": agora_formatado,
            }

            registros_processados.append(linha_tabela)

        # Retorna o lote consolidado em formato estruturado pronto para a Engine do Banco
        return pd.DataFrame(registros_processados)
