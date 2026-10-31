from comum.config.logger_config import logger
from src.services.expectativa import acusar_expectativa_ausente
from comum.arquivos.recusa import registrar_recusa
from comum.dominio.diagnostico_de_recusa import Diagnostico
from comum.utils.decoradores import log_execucao
from pathlib import Path
import pandas as pd
from comum.config.configuration import (
    CAMINHO_DETRAF_RECEBIDO,
    CAMINHO_EXPECTATIVA_DETRAF,
    ANO_MES_REFERENCIA,
    EXTENSOES_PERMITIDAS,
    PASTAS_EXPECTATIVAS,
    EXPECTATIVA_SUBSTRING,
    IGNORAR_ARQUIVOS,
    SUBPASTA_DETRAFS_RECEBIDOS,
    DIRETORIO_TEMP,
    DIRETORIO_SAIDA_VALIDACAO,
)
from comum.arquivos.area_de_trabalho import AreaDeTrabalho
from comum.dados.repositorio_tabelas import bd_tabelas
from comum.dominio.validacao_colunas import ValidadorColunas
from src.services.validacao_inicial.limpeza_trafegos import LimpadorTrafegos
from comum.arquivos.gerenciador import (
    carregar_dados,
    manter_linhas_por_lista_valores,
    separar_e_salvar_por_mascara,
    salvar_dados,
)
from comum.arquivos import estrutura_pastas as ep
from comum.arquivos.historico import ValidadorHistoricoRPA
from comum.integracoes.rede import garantir_conexao_autenticada
from comum.dominio.layout_detraf import validar_layout
from comum.utils.debug import salvar_debug_log
from src.services.resultado_validacao import TransformadorRelatorioRPA
from comum.arquivos.gerenciador import renomear_arquivo_com_sufixo


def _carregar_para_diagnostico(arquivo: Path) -> pd.DataFrame | None:
    """
    Recarrega um arquivo só para as linhas de exemplo do `_RECUSADO.md`.

    Nunca levanta: perder a amostra é aceitável (o `.md` sai sem ela); travar
    a recusa por causa do diagnóstico não seria — é a mesma regra de
    `registrar_recusa`, aplicada aqui um passo antes.
    """
    try:
        return carregar_dados(arquivo)
    except Exception as erro:
        logger.warning(
            f"Não foi possível reler [{arquivo}] para a amostra do diagnóstico "
            f"de recusa: {erro}. O `_RECUSADO.md` sai sem as linhas de exemplo."
        )
        return None


class ValidacaoDetrafsService:
    def __init__(self):
        garantir_conexao_autenticada(CAMINHO_DETRAF_RECEBIDO)
        self.repositorio_tabelas = bd_tabelas
        self.operadoras_sem_detraf: list[str] = []
        self.validador_colunas = ValidadorColunas()
        self.validador_separar_trafegos = LimpadorTrafegos()
        self.arquivos_invalidos: set[Path] = set()
        self.historico_rpa = ValidadorHistoricoRPA()
        #: `nome_arquivo` já gravados no banco para o mês — segunda fonte do
        #: filtro anti-reprocessamento (2026-09-24). Resolvido uma vez por
        #: execução, no primeiro uso.
        self._nomes_no_banco_cache: set[str] | None = None
        self._nomes_no_banco_resolvido = False
        self.resultado_validacao = TransformadorRelatorioRPA()
        #: Resumo da última execução, para a parada entre etapas mostrar.
        self.resumo: list[str] = []
        #: Onde esta etapa escreve, e para onde ela entrega. O insumo original
        #: não é tocado, e os artefatos vão para `DIRETORIO_SAIDA_VALIDACAO` — não para a
        #: pasta de entrada. Quem lê do outro lado é o batimento, pela MESMA
        #: função `caminho_de_saida`.
        self.area = AreaDeTrabalho(
            DIRETORIO_TEMP,
            ANO_MES_REFERENCIA,
            destino_de=lambda pasta: ep.caminho_de_saida(
                pasta, ANO_MES_REFERENCIA, raiz_saida=DIRETORIO_SAIDA_VALIDACAO
            ),
        )

    @log_execucao
    def _preparar_arquivos_detrafs(self) -> list[Path]:
        """
        Varre o diretório raiz buscando arquivos (CSV ou Planilhas) dentro da estrutura
        de pastas de cada operadora para o ano e mês de referência informados.

        Returns:
            list[Path]: Lista contendo os caminhos completos (Path) de todos os arquivos válidos encontrados.
        """
        logger.info("Preparando os detrafs para validação...")

        ano_mes = ANO_MES_REFERENCIA

        caminhos_encontrados: list[Path] = []

        # Dicionário para rastrear a contagem de arquivos válidos por operadora
        arquivos_por_operadora: dict[str, int] = {}

        # Conjunto de extensões permitidas para validação rápida O(1)
        extensoes_validas = EXTENSOES_PERMITIDAS

        logger.info(
            f"Iniciando busca de arquivos para o período {ano_mes} no diretório: '{CAMINHO_DETRAF_RECEBIDO}'"
        )

        try:
            # A varredura de `{operadora}/{ano}/{aaaamm}` vem de `comum`: ela
            # estava duplicada aqui e em `batimento_detraf`, e o RPA 3 precisava
            # da mesma coisa. A subpasta é exigida pela V2 (HU-03) e é onde o
            # RPA 1 grava — os dois lados usam a mesma constante para não
            # divergirem.
            com_detraf = ep.listar_operadoras_do_mes(
                ano_mes,
                raiz_operadoras=CAMINHO_DETRAF_RECEBIDO,
                subpasta=SUBPASTA_DETRAFS_RECEBIDOS,
            )

            # "Sem Detraf no mês" é o complemento das pastas de operadora que
            # existem na raiz — inclusive as que só têm meses anteriores. É esta
            # lista que denuncia a operadora que simplesmente não enviou.
            todas = sorted(
                pasta.name
                for pasta in CAMINHO_DETRAF_RECEBIDO.iterdir()
                if pasta.is_dir()
            )
            self.operadoras_sem_detraf.extend(
                operadora for operadora in todas if operadora not in com_detraf
            )

            for nome_operadora in com_detraf:
                logger.info(f"Varrendo arquivos da operadora: [{nome_operadora}]")
                arquivos_por_operadora[nome_operadora] = 0

                pasta_alvo = ep.caminho_detrafs_recebidos(
                    nome_operadora, ano_mes, raiz_operadoras=CAMINHO_DETRAF_RECEBIDO
                )

                for arquivo in pasta_alvo.iterdir():
                    if not arquivo.is_file():
                        continue

                    # Ignora arquivos contendo substrings proibidas
                    if any(sub in arquivo.name for sub in IGNORAR_ARQUIVOS):
                        continue

                    if arquivo.suffix.lower() not in extensoes_validas:
                        continue

                    caminhos_encontrados.append(arquivo)
                    arquivos_por_operadora[nome_operadora] += 1

        except Exception as erro:
            logger.excecao(
                f"Erro inesperado durante a varredura dos diretórios: {erro}"
            )
            raise RuntimeError(f"Falha ao mapear arquivos detrafs: {erro}")

        # Gera o log final com os indicadores de volumetria solicitados
        total_operadoras_encontradas = len(arquivos_por_operadora)
        logger.info(
            f"Mapeamento concluído com sucesso. "
            f"Total de operadoras processadas com dados: {total_operadoras_encontradas}. "
            f"Total geral de arquivos encontrados: {len(caminhos_encontrados)}"
        )

        # Exibe o detalhamento por operadora no log
        for operadora, qtd_arquivos in arquivos_por_operadora.items():
            logger.info(
                f"-> Operadora [{operadora}]: {qtd_arquivos} arquivo(s) encontrado(s)"
            )

        return self.historico_rpa.filtrar_arquivos_novos(
            caminhos_encontrados, nomes_no_banco=self._nomes_no_banco()
        )

    @log_execucao
    def _preparar_arquivos_expectativa(self,) -> list[Path]:
        """
        Varre as pastas de expectativa Vivo na estrutura:

            CAMINHO_EXPECTATIVA_DETRAF
            └── AAAAMM
                ├── Vivo
                ├── TLF
                ├── Detraf TRP
                └── MVNO

        Retorna os arquivos com extensão permitida e cujo nome contém
        uma das marcas configuradas em EXPECTATIVA_SUBSTRING.

        Ao final, registra no log a quantidade de arquivos válidos e
        inválidos por pasta.
        """
        logger.info(
            "Preparando os arquivos de expectativa para validação..."
        )

        caminhos_encontrados: list[Path] = []
        extensoes_validas = EXTENSOES_PERMITIDAS

        # ============================================================
        # 1. Validar a configuração da raiz
        # ============================================================
        if CAMINHO_EXPECTATIVA_DETRAF is None:
            raise FileNotFoundError(
                "CAMINHO_EXPECTATIVA_DETRAF não está configurado. "
                "Essa variável deve apontar para a raiz da expectativa "
                "Vivo. Sem essa pasta não há arquivos para comparação."
            )

        raiz_expectativa = Path(
            CAMINHO_EXPECTATIVA_DETRAF
        )

        if (
            not raiz_expectativa.exists()
            or not raiz_expectativa.is_dir()
        ):
            raise FileNotFoundError(
                "O caminho de expectativa não foi encontrado ou não é "
                f"um diretório: [{raiz_expectativa}]"
            )

        # ============================================================
        # 2. Validar a competência
        # ============================================================
        periodo = str(
            ANO_MES_REFERENCIA
        ).strip()

        if not (
            len(periodo) == 6
            and periodo.isdigit()
        ):
            raise ValueError(
                f"ANO_MES_REFERENCIA inválido: [{periodo}]. "
                "Esperado o formato AAAAMM, por exemplo 202609."
            )

        # A competência agora fica antes das pastas Vivo, TLF etc.
        raiz_expectativa_periodo = (
            raiz_expectativa
            / periodo
        )

        logger.info(
            f"Buscando expectativas do período [{periodo}] em "
            f"[{raiz_expectativa_periodo}]."
        )

        if (
            not raiz_expectativa_periodo.exists()
            or not raiz_expectativa_periodo.is_dir()
        ):
            raise FileNotFoundError(
                f"A pasta da competência [{periodo}] não existe em "
                f"[{raiz_expectativa}]. Caminho esperado: "
                f"[{raiz_expectativa_periodo}]"
            )

        # ============================================================
        # 3. Percorrer as pastas de expectativa do período
        # ============================================================
        try:
            for pasta in PASTAS_EXPECTATIVAS:
                # Estrutura nova:
                #
                # DETRAF_EXPECTATIVA_VIVO
                #     / AAAAMM
                #     / Vivo, TLF, Detraf TRP ou MVNO
                pasta_operadora = (
                    raiz_expectativa_periodo
                    / pasta
                )

                arquivos_validos_pasta = 0
                arquivos_invalidos_pasta = 0

                if (
                    not pasta_operadora.exists()
                    or not pasta_operadora.is_dir()
                ):
                    acusar_expectativa_ausente(
                        pasta_operadora,
                        "não existe",
                    )
                    continue

                # Os arquivos ficam diretamente dentro da pasta.
                for arquivo in pasta_operadora.iterdir():
                    if not arquivo.is_file():
                        continue

                    nome_arquivo = arquivo.name
                    extensao = arquivo.suffix.lower()

                    # Ignora produtos gerados pelo próprio fluxo, como
                    # _BK, _ERRO e _EXP, conforme a configuração.
                    deve_ignorar = any(
                        substring in nome_arquivo
                        for substring in IGNORAR_ARQUIVOS
                    )

                    if deve_ignorar:
                        arquivos_invalidos_pasta += 1
                        continue

                    possui_extensao_valida = (
                        extensao in extensoes_validas
                    )

                    possui_substring = any(
                        substring in nome_arquivo
                        for substring in EXPECTATIVA_SUBSTRING
                    )

                    if (
                        possui_extensao_valida
                        and possui_substring
                    ):
                        caminhos_encontrados.append(
                            arquivo
                        )
                        arquivos_validos_pasta += 1

                    else:
                        arquivos_invalidos_pasta += 1

                logger.info(
                    f"Pasta [{periodo}/{pasta}] processada -> "
                    f"Válidos: {arquivos_validos_pasta} | "
                    f"Inválidos/Ignorados: "
                    f"{arquivos_invalidos_pasta}"
                )

                if arquivos_validos_pasta == 0:
                    acusar_expectativa_ausente(
                        pasta_operadora,
                        (
                            "existe, mas nenhum dos "
                            f"{arquivos_invalidos_pasta} arquivo(s) "
                            "passou nos filtros"
                        ),
                    )

        except Exception as erro:
            logger.error(
                "Erro inesperado durante a varredura das "
                f"expectativas: {erro}"
            )
            raise RuntimeError(
                f"Falha ao mapear arquivos de expectativa: {erro}"
            ) from erro

        logger.info(
            "Mapeamento de expectativa concluído. "
            f"Período: [{periodo}] | "
            "Total geral de arquivos válidos: "
            f"{len(caminhos_encontrados)}"
        )

        return self.historico_rpa.filtrar_arquivos_novos(
            caminhos_encontrados,
            nomes_no_banco=self._nomes_no_banco(),
        )
    def _validar_layout_arquivos(self, arquivos: list[Path]) -> None:
        """
        Confere se cada arquivo tem o layout documentado na V2, **antes** de
        qualquer validação linha a linha.

        É a diferença entre "este arquivo tem uma linha ruim" e "este arquivo
        não é o arquivo que eu esperava". Sem esta camada, um arquivo com layout
        diferente passa direto e é lido por posição — o código pega o índice 14
        achando que é `R$_Bruto` e recebe minutos, sem nada indicar o problema.

        A regra vale para os DOIS tipos de arquivo, operadora e expectativa,
        porque a V2 diz que as regras de validação valem para ambos (decisão do
        cliente, 2026-07-31).

        ⚠️ Consequência conhecida: os arquivos de expectativa Vivo atuais NÃO
        conformam com a V2 e passam a ser rejeitados. É o comportamento pedido —
        falhar alto é melhor que comparar coluna errada em silêncio —, mas
        significa que não haverá comparação até a geração ser corrigida no ICT.
        O diagnóstico no log identifica esse caso pelo nome.
        """
        for arquivo in arquivos:
            try:
                df = carregar_dados(arquivo)
                resultado = validar_layout(df)

                if not resultado.conforme:
                    logger.error(resultado.mensagem(arquivo))
                    self.arquivos_invalidos.add(arquivo)
                    registrar_recusa(arquivo, resultado, df)

            except Exception as erro:
                logger.excecao(
                    f"Erro ao validar o layout do arquivo [{arquivo}]: {erro}"
                )
                self.arquivos_invalidos.add(arquivo)

    def _verificar_formato_col5(self, arquivos: list[Path]) -> None:
        valores_manter = ["00", "0", 0]
        for arquivo in arquivos:
            try:
                df = carregar_dados(arquivo)
                if df is None or df.empty:
                    continue
                df_filtrado = df[df.iloc[:, 5].isin(valores_manter)]
                if df_filtrado.empty:
                    logger.warning(
                        f"Arquivo [{arquivo.name}] marcado como inválido: "
                        f"possuía {len(df)} linha(s) antes do filtro e 0 após — "
                        f"o filtro da coluna Rel (índice 5) zerou o arquivo, "
                        f"provavelmente porque está fora do padrão esperado."
                    )
                    self.arquivos_invalidos.add(arquivo)
            except Exception as e:
                logger.excecao(f"Erro ao verificar col 5 do arquivo [{arquivo}]: {e}")
                self.arquivos_invalidos.add(arquivo)

    def _validar_colunas_arquivos(
        self, arquivos: list[Path], tipo_arquivo: str, debug: bool = False
    ):
        for arquivo in arquivos:
            logger.info(f"Validando as colunas do arquivo de {tipo_arquivo}: {arquivo}")
            try:
                # Carrega o arquivo bruto
                df = carregar_dados(arquivo)

                # Remover as linhas de totais porque elas não seguem as regras de negócio e podem causar falhas na validação
                df_filtrado = manter_linhas_por_lista_valores(
                    df=df, indice_coluna=5, valores_manter=["00", "0", 0, 00]
                )

                if debug:
                    linhas_antes = df.shape[0]
                    linhas_depois = df_filtrado.shape[0]
                    linhas_removidas = linhas_antes - linhas_depois

                    # Dispara o aviso caso de fato alguma linha de faturamento/total tenha sido removida
                    if linhas_removidas > 0:
                        logger.warning(
                            f"Linhas de totais/resumos descartadas no arquivo [{arquivo.name}]. "
                            f"Total antes: {linhas_antes} | Total depois: {linhas_depois} | "
                            f"Diferença (linhas removidas): {linhas_removidas}"
                        )

                if df_filtrado is None:
                    logger.error(
                        f"Falha ao carregar o arquivo [{arquivo}]. Verifique o formato e o conteúdo."
                    )
                    self.arquivos_invalidos.add(arquivo)
                    continue

                if tipo_arquivo == "expectativa":
                    self._validar_colunas_expectativa(
                        arquivo, df, df_filtrado, debug=debug
                    )
                    continue

                resultado_colunas = self.validador_colunas.validar_tudo_detalhado(
                    df_filtrado, tipo_arquivo, debug=debug
                )
                if resultado_colunas.conforme:
                    logger.info(
                        f"Arquivo [{arquivo}] passou em todas as validações."
                    )
                else:
                    # `error`, e nao `warning`: desde 2026-08-06 o RPA 1 valida
                    # ANTES de salvar, e nada reprovado deveria chegar ate aqui.
                    # Um arquivo reprovado neste ponto e uma ANOMALIA — ou o
                    # portao da captura falhou, ou alguem pos o arquivo na pasta
                    # a mao. Nos dois casos, alguem precisa olhar.
                    logger.error(
                        f"Arquivo [{arquivo}] falhou em uma ou mais validações "
                        "APÓS ter passado pelo portão do RPA 1 — investigar por "
                        "que ele chegou à pasta da operadora."
                    )
                    self.arquivos_invalidos.add(arquivo)
                    # Achado em 2026-08-12: até aqui esta era a ÚNICA recusa de
                    # Detraf sem `_RECUSADO.md` — o resumo da execução promete
                    # "cada um tem um *_RECUSADO.md ao lado" para todo item de
                    # `arquivos_invalidos`, e este caminho nunca gravava nada.
                    registrar_recusa(
                        arquivo,
                        resultado_colunas.diagnostico(
                            total_colunas=df_filtrado.shape[1]
                        ),
                        df_filtrado,
                    )
            except Exception as erro:
                logger.excecao(f"Erro ao validar o arquivo [{arquivo}]: {erro}")
                self.arquivos_invalidos.add(arquivo)

    def _validar_colunas_expectativa(
        self,
        arquivo: Path,
        df: pd.DataFrame,
        df_filtrado: pd.DataFrame,
        debug: bool = False,
    ) -> None:
        """
        Para arquivos de expectativa, separa linha a linha as que falham em
        qualquer regra de validação de coluna, mantendo as linhas válidas
        (mais as linhas de totalização, removidas antes da validação) no
        arquivo original. O arquivo original NÃO é marcado inválido — só as
        linhas ruins são movidas para um arquivo `_ERRO` à parte.
        """
        if df_filtrado.empty:
            return

        mascaras = self.validador_colunas.mascaras_por_criterio(df_filtrado)
        mascara_valida = pd.concat(mascaras, axis=1).all(axis=1)
        mascara_valida.index = df_filtrado.index

        df_validas, df_invalidas, caminho_erro = separar_e_salvar_por_mascara(
            df_filtrado, mascara_valida, arquivo
        )

        if df_invalidas.empty:
            logger.info(f"Arquivo [{arquivo}] passou em todas as validações.")
            return

        # Linhas de totalização removidas antes da validação nunca são
        # inválidas por essas regras — voltam para o arquivo original.
        df_linhas_totais = df.loc[df.index.difference(df_filtrado.index)]
        df_validas_final = pd.concat([df_validas, df_linhas_totais]).sort_index()
        salvar_dados(df_validas_final, arquivo)

        # 🔴 Dizer QUANTAS linhas caíram sem dizer ONDE não resolve nada: em
        # 25/09 arquivos inteiros foram para `_ERRO` (DATORA: 45 de 45) e não
        # havia como saber qual regra reprovou sem reexecutar com `debug`.
        # O detalhamento sai junto da contagem, sempre que houver recusa.
        total = len(df_filtrado)
        reprovadas = {
            criterio: total - int(mascara.sum())
            for criterio, mascara in mascaras.items()
            if int(mascara.sum()) < total
        }
        detalhe = ", ".join(
            f"{criterio}={quantas}"
            for criterio, quantas in sorted(
                reprovadas.items(), key=lambda item: -item[1]
            )
        )
        if not detalhe:
            detalhe = "(nenhum critério isolado — combinação de regras)"
        logger.warning(
            f"Arquivo [{arquivo}] teve {len(df_invalidas)} de {total} linha(s) "
            f"movida(s) para [{caminho_erro.name if caminho_erro else '?'}] por "
            f"falha de validação de coluna. Reprovaram em: {detalhe}."
        )

    def _validar_fluxo(
        self,
        arquivos: list[Path],
        tipo_fluxo: str,
        sufixo: str = "",
        debug: bool = False,
        gerar_arquivos: bool = True,
        sinalizar_como_invalido: bool = False,
    ):
        """
        Valida um fluxo específico para uma lista de arquivos.
        """
        for arquivo in arquivos:
            logger.info(f"Validando o fluxo {tipo_fluxo} do arquivo: {arquivo}")
            try:
                arquivo_com_fluxo_especial = self.validador_separar_trafegos.executar(
                    caminho_arquivo=arquivo,
                    tipo_fluxo=tipo_fluxo,
                    sufixo=sufixo,
                    debug=debug,
                    gerar_arquivos=gerar_arquivos,
                )
                if sinalizar_como_invalido and arquivo_com_fluxo_especial:
                    logger.warning(
                        f"Arquivo [{arquivo}] atende ao fluxo {tipo_fluxo} e foi sinalizado como inválido conforme configuração."
                    )
                    self.arquivos_invalidos.add(arquivo)
                    # Mesmo achado do outro ponto sem `_RECUSADO.md` (2026-08-12):
                    # `gerar_arquivos=False` nesta chamada (só para Detraf) garante
                    # que o arquivo em `arquivo` continua intacto, seguro para reler.
                    registrar_recusa(
                        arquivo,
                        Diagnostico(
                            motivo=(
                                f"O arquivo tem linha(s) que atendem ao fluxo "
                                f"{tipo_fluxo} (descritor iniciado e terminado em "
                                f"'L', serviço STFC) — para arquivo de Detraf "
                                f"(diferente de expectativa), isso marca o "
                                f"arquivo **inteiro** como inválido, por decisão "
                                f"de configuração: tráfegos deste fluxo não são "
                                f"separados de arquivos de operadora."
                            )
                        ),
                        _carregar_para_diagnostico(arquivo),
                    )

            except Exception as erro:
                logger.excecao(
                    f"Erro ao validar o fluxo {tipo_fluxo} do arquivo [{arquivo}]: {erro}"
                )
                self.arquivos_invalidos.add(arquivo)

    def _nomes_no_banco(self) -> set[str] | None:
        """
        Os arquivos que a tabela de log já tem para o mês (2026-09-24).

        🔴 Por que o JSON sozinho não basta: a Vivo limpou
        `tbl_rpa_log_detraf_despesa_arquivos` para refazer a massa de 202607,
        o JSON continuou dizendo "já processado", e o RPA 2 regravou só 8 dos
        73 aprovados (e-mail da Luciana, 23/09/2026). Arquivo que está no JSON
        mas não no banco volta a ser processado.

        Se o banco não responder, devolve `None` — o filtro cai no
        comportamento antigo (só o JSON) e avisa. Não derruba a etapa aqui
        porque a validação vai bater no banco logo em seguida e falhar com a
        mensagem certa, se for o caso.
        """
        if self._nomes_no_banco_resolvido:
            return self._nomes_no_banco_cache

        self._nomes_no_banco_resolvido = True
        try:
            self._nomes_no_banco_cache = (
                self.repositorio_tabelas.nomes_arquivos_no_log_despesa(ANO_MES_REFERENCIA)
            )
            logger.info(
                f"{len(self._nomes_no_banco_cache)} arquivo(s) já no banco para "
                f"{ANO_MES_REFERENCIA} — quem está no histórico e não aqui será "
                f"processado de novo."
            )
        except Exception as erro:
            logger.warning(
                f"Não foi possível ler o log de arquivos no banco para "
                f"{ANO_MES_REFERENCIA}: {erro}. O filtro anti-reprocessamento "
                f"vai usar só o histórico JSON nesta execução."
            )
            self._nomes_no_banco_cache = None

        return self._nomes_no_banco_cache

    def _salvar_historico_arquivos_processados(self, todos_arquivos: set[Path]):
        """
        Registra o resultado por arquivo, sempre pelo caminho do **insumo**.

        `todos_arquivos` já chega traduzido; `self.arquivos_invalidos` guarda
        cópias de trabalho e precisa ser traduzido aqui — sem isso a subtração
        não casaria nenhum caminho e todo arquivo entraria como válido.
        """
        invalidos = set(self.area.origens(self.arquivos_invalidos))
        arquivos_validos = todos_arquivos - invalidos
        self.historico_rpa.registrar_arquivos(
            lista_caminhos=list(arquivos_validos), status_valido=True
        )
        self.historico_rpa.registrar_arquivos(
            lista_caminhos=list(invalidos), status_valido=False
        )

    def _eh_arquivo_expectativa(self, arquivo: Path) -> bool:
        return any(sub in arquivo.name for sub in EXPECTATIVA_SUBSTRING)

    def separar_arquivos_por_categoria(
        self,
        arquivos_detraf: list[Path],
        arquivos_expectativa: list[Path],
        debug: bool = False,
    ) -> dict[str, list[Path]]:
        """
        Separa os arquivos gerados em 4 categorias distintas cruza-referenciando
        o histórico de inválidos e a função de identificação de tipo.

        Retorna um dicionário contendo:
        {
            "detraf_validos": [...],
            "detraf_invalidos": [...],
            "expectativa_validos": [...],
            "expectativa_invalidos": [...],
        """
        todos_arquivos = set(arquivos_detraf + arquivos_expectativa)

        invalidos_do_lote = todos_arquivos.intersection(self.arquivos_invalidos)
        validos_do_lote = todos_arquivos - invalidos_do_lote

        # Separação por Tipo utilizando a sua função de identificação do projeto
        # Categoria: Detraf
        detraf_validos = [
            arq for arq in validos_do_lote if not self._eh_arquivo_expectativa(arq)
        ]
        detraf_invalidos = [
            arq for arq in invalidos_do_lote if not self._eh_arquivo_expectativa(arq)
        ]

        # Categoria: Expectativa
        expectativa_validos = [
            arq for arq in validos_do_lote if self._eh_arquivo_expectativa(arq)
        ]
        expectativa_invalidos = [
            arq for arq in invalidos_do_lote if self._eh_arquivo_expectativa(arq)
        ]

        resultado = {
            "detraf_validos": detraf_validos,
            "detraf_invalidos": detraf_invalidos,
            "expectativa_validos": expectativa_validos,
            "expectativa_invalidos": expectativa_invalidos,
        }
        if debug:
            logger.debug(
                f"Resultado da separação de arquivos por categoria: {resultado}"
            )

            linhas = [
                "RESULTADO DA VALIDAÇÃO",
                "=" * 80,
                f"TOTAL DE ARQUIVOS: {sum(len(v) for v in resultado.values())}",
                "=" * 80,
                "",
            ]

            categorias = [
                ("DETRAF VÁLIDOS", resultado["detraf_validos"]),
                ("DETRAF INVÁLIDOS", resultado["detraf_invalidos"]),
                ("EXPECTATIVA VÁLIDOS", resultado["expectativa_validos"]),
                ("EXPECTATIVA INVÁLIDOS", resultado["expectativa_invalidos"]),
            ]

            for titulo, arquivos in categorias:
                linhas.append(f"{titulo} ({len(arquivos)})")
                linhas.append("-" * 80)

                if arquivos:
                    for path in arquivos:
                        linhas.append(f"  • {path.name}")
                else:
                    linhas.append("  Nenhum arquivo")

                linhas.append("")

            linhas.append("=" * 80)

            conteudo = "\n".join(linhas)

            salvar_debug_log(
                nome_arquivo="RESULTADO_VALIDACAO",
                conteudo=conteudo,
            )

        return resultado

    def renomear_arquivos_processados(
        self, arquivos_validos: set[Path], arquivos_invalidos: set[Path]
    ):
        """Acrescenta `_EXP`/`_ERRO` na cópia de trabalho **e na origem**.

        🔴 Ponto 2.1/2.2 do e-mail da Luciana de 29/09/2026:

            "Arquivo na pasta 33 sem o _EXP e no banco de dados com. O nome do
             arquivo deve seguir o nome do banco." (CITTA_TELECOM, TELECALL)

        Até aqui só a cópia era renomeada. A promoção entrega o arquivo
        renomeado em `DIRETORIO_SAIDA_VALIDACAO`, não de volta na pasta de
        origem — então o banco gravava `X_EXP.txt` e a pasta 33 continuava com
        `X.txt`. Renomear os dois é o que faz disco e banco contarem a mesma
        história.

        ⚠️ **Só os arquivos de origem Vivo chegam aqui.** O Detraf recebido por
        e-mail é insumo de terceiro e não pode ser tocado — ver o corte em
        `executar` e o mapa `_SUFIXO_POR_LOTE`.

        A cópia continua sendo renomeada porque é dela que sai o artefato
        promovido para `_SAIDA`; parar de renomeá-la esvaziaria aquela pasta,
        que é de onde o RPA 3 lê a expectativa validada.
        """
        for arquivos, sufixo, rotulo in (
            (arquivos_validos, "_EXP", "validados"),
            (arquivos_invalidos, "_ERRO", "inválidos"),
        ):
            if not arquivos:
                continue

            logger.info(
                f"Renomeando {len(arquivos)} arquivo(s) {rotulo} adicionando "
                f"{sufixo} (cópia de trabalho e origem)"
            )
            for copia in arquivos:
                renomear_arquivo_com_sufixo(copia, sufixo=sufixo)

                origem = self.area.origem_de(copia)
                if origem == copia:
                    # Não veio da área de trabalho: não há origem separada.
                    continue
                try:
                    renomear_arquivo_com_sufixo(origem, sufixo=sufixo)
                except (FileNotFoundError, OSError) as erro:
                    # O insumo pode ter sumido da rede entre a cópia e agora.
                    # Perder o sufixo na origem é ruim; derrubar a execução
                    # depois de tudo apurado seria pior.
                    logger.warning(
                        f"Não foi possível renomear o arquivo de origem "
                        f"[{origem.name}] para {sufixo}: {erro}"
                    )

    @log_execucao
    def executar(self):
        logger.info("Executando a validação dos detrafs...")
        arquivos_detraf = self._preparar_arquivos_detrafs()
        arquivos_expectativa = self._preparar_arquivos_expectativa()
        if not arquivos_detraf:
            logger.warning(
                "Nenhum arquivo de detraf encontrado para validação. Verifique os logs anteriores para detalhes."
            )
        if not arquivos_expectativa:
            logger.warning(
                "Nenhum arquivo de expectativa encontrado para validação. Verifique os logs anteriores para detalhes."
            )

        # A partir daqui, TUDO opera sobre a cópia. A troca acontece num ponto
        # só, e de propósito: as validações não sabem — e não precisam saber —
        # que estão escrevendo na área de trabalho, porque cada uma escreve ao
        # lado do arquivo que recebeu. É o que mantém a proteção do insumo sem
        # espalhar o assunto por dez funções.
        arquivos_detraf = self.area.acolher(arquivos_detraf)
        arquivos_expectativa = self.area.acolher(arquivos_expectativa)

        # Validação de LAYOUT — vem antes de tudo. Um arquivo com layout errado
        # é lido por posição e produz números sem sentido silenciosamente; não
        # faz sentido aplicar as demais regras sobre ele.
        self._validar_layout_arquivos(arquivos_detraf + arquivos_expectativa)

        # Fluxo _BK — vale para os DOIS tipos de arquivo (corrigido 2026-08-10).
        #
        # Rodava só na expectativa. A V2 é explícita na HU-06: o tráfego L→V de
        # EOTs SMP não-PMS é separado numa cópia com `_BK`, e *"vale tanto para o
        # arquivo da operadora quanto para o de expectativa Vivo"*. Enquanto só a
        # expectativa era tratada, o mesmo tráfego ficava separado de um lado e
        # inteiro do outro — e a comparação da HU-10 passava a somar coisas
        # diferentes sem nada indicar.
        self._validar_fluxo(
            arquivos_expectativa + arquivos_detraf, tipo_fluxo="BK", sufixo="_BK"
        )

        # Verificar se existe fluxo LL nos arquivos de expectativa e de detraf
        self._validar_fluxo(arquivos_expectativa, tipo_fluxo="LL", sufixo="_ERRO")
        self._validar_fluxo(
            arquivos_detraf,
            tipo_fluxo="LL",
            gerar_arquivos=False,
            sinalizar_como_invalido=True,  # Unico caso em que é necessario sinalizar o arquivo como invalido
        )  # Não separar os trafegos nos detrafs ja que são arquivos de outras operadorsa

        # Descartar antecipadamente arquivos cujo filtro de col 5 zera todas as linhas
        self._verificar_formato_col5(arquivos_detraf + arquivos_expectativa)

        # Validar os arquivos de detraf encontrados (exclui os já marcados inválidos)
        self._validar_colunas_arquivos(
            [a for a in arquivos_detraf if a not in self.arquivos_invalidos],
            tipo_arquivo="detraf",
            debug=False,
        )

        # Validar os arquivos de expectativa encontrados (exclui os já marcados inválidos)
        self._validar_colunas_arquivos(
            [a for a in arquivos_expectativa if a not in self.arquivos_invalidos],
            tipo_arquivo="expectativa",
        )

        # Inserir no banco o resultado das validações
        arquivos_processados = self.separar_arquivos_por_categoria(
            arquivos_detraf, arquivos_expectativa, debug=True
        )

        detraf_sucesso = self.resultado_validacao.preparar_lote(
            lista_arquivos=arquivos_processados["detraf_validos"],
            tipo_lote="DETRAF_SUCESSO",
        )
        detraf_erro = self.resultado_validacao.preparar_lote(
            lista_arquivos=arquivos_processados["detraf_invalidos"],
            tipo_lote="DETRAF_ERRO",
        )
        expectativa_sucesso = self.resultado_validacao.preparar_lote(
            lista_arquivos=arquivos_processados["expectativa_validos"],
            tipo_lote="EXPECTATIVA_SUCESSO",
        )
        expectativa_erro = self.resultado_validacao.preparar_lote(
            lista_arquivos=arquivos_processados["expectativa_invalidos"],
            tipo_lote="EXPECTATIVA_ERRO",
        )

        lotes_preparados = [
            detraf_sucesso,
            detraf_erro,
            expectativa_sucesso,
            expectativa_erro,
        ]

        df_consolidado_final = pd.concat(lotes_preparados, ignore_index=True)

        if not df_consolidado_final.empty:
            self.repositorio_tabelas.salvar_dados_tabela_despesa(df_consolidado_final)  # type: ignore

        todos_arquivos = set(arquivos_detraf + arquivos_expectativa)

        # 🔴 Só o arquivo de origem VIVO é renomeado (29/09/2026).
        #
        # O Detraf que a operadora manda por e-mail é insumo de terceiro, e o
        # e-mail da Luciana de 29/09 é explícito: *"o RPA não pode promover
        # nenhuma alteração nos arquivos recebidos nos e-mails"*. O sufixo do
        # ponto 5 de 23/09 estava na seção da expectativa; aplicá-lo aos dois
        # foi generalização nossa.
        #
        # Ver o mapa `_SUFIXO_POR_LOTE` em `resultado_validacao`, que faz o
        # mesmo corte do lado do nome gravado no banco — os dois têm que contar
        # a mesma história, senão o banco volta a divergir do disco.
        de_origem_vivo = set(arquivos_expectativa)
        self.renomear_arquivos_processados(
            arquivos_validos=de_origem_vivo - self.arquivos_invalidos,
            arquivos_invalidos=de_origem_vivo & self.arquivos_invalidos,
        )

        # Devolver os artefatos às pastas de origem. Vem DEPOIS da renomeação,
        # senão o que sobe é a cópia de trabalho crua, sem o `_EXP`/`_ERRO` que
        # diz o que aconteceu com ela.
        self.area.promover()

        # O histórico é indexado pelo caminho ABSOLUTO, e quem precisa constar
        # nele é o insumo — não a cópia. Registrar a cópia deixaria o original
        # invisível ao filtro anti-reprocessamento, e ele voltaria inteiro na
        # execução seguinte.
        self._salvar_historico_arquivos_processados(
            set(self.area.origens(todos_arquivos))
        )

        # Resumo estruturado para a parada entre etapas. Montado aqui, junto da
        # categorização, para não existirem duas versões da mesma contagem.
        self.resumo = [
            f"Detraf válidos:           {len(arquivos_processados['detraf_validos'])}",
            f"Detraf inválidos:         {len(arquivos_processados['detraf_invalidos'])}",
            f"Expectativa válidos:      {len(arquivos_processados['expectativa_validos'])}",
            f"Expectativa inválidos:    {len(arquivos_processados['expectativa_invalidos'])}",
        ]
        if self.operadoras_sem_detraf:
            self.resumo += [
                "",
                f"Operadoras sem Detraf no mês ({len(self.operadoras_sem_detraf)}):",
                "  " + ", ".join(sorted(self.operadoras_sem_detraf)),
            ]
        if self.arquivos_invalidos:
            self.resumo += [
                "",
                "Recusados (cada um tem um *_RECUSADO.md ao lado):",
            ]
            self.resumo += [f"  {caminho.name}" for caminho in sorted(self.arquivos_invalidos)]

        ...
