import pandas as pd
from pathlib import Path
from comum.config.logger_config import logger
"""HU-09 e HU-10 — comparativo do apresentado × esperado, direto no banco.

**A Base de Contestação é uma tabela, não um arquivo** (decisão do cliente,
2026-08-04). É o que a V2 já dizia:

    "O robô atualiza as tabelas dinâmicas das abas 'RESUMO TBRA' e
     'RESUMO AMPERNET' (exemplo) para que reflitam o total das colunas
     'Minutos' e 'R$ Bruto' (…). **Não é necessário gerar o arquivo**, mas usar
     a lógica e popular a tabela 'tbl_rpa_log_detraf_despesa_contestacao'"

Até 2026-08-04 este serviço gravava um `.xlsx` `Base_Contestação_{OP}_{aaaamm}`
com cinco abas — e **ninguém o lia**: o `_EXP` do RPA 3 é montado a partir de
DataFrames, não daquele arquivo. A lógica de agregação continua aqui (é ela que
produz o comparativo); o que saiu foi a exportação.
"""

from comum.arquivos.gerenciador import carregar_dados
from comum.config.configuration import ANO_MES_REFERENCIA
from comum.dados import tabelas
from comum.dados.repositorio_tabelas import bd_tabelas
from comum.dados.tabelas import CARGA_AGI_NAO_CARREGADO
from comum.dominio.variacao import calcular_variacao, deve_contestar
from comum.dominio import mapa_remuneracao as mr
from comum.dominio.classificadores import remuneracao_sem_catalogo


class CriacaoArquivoContestacao:

    def __init__(self) -> None:
        #: Memorizado por instância — ver `_indice_remuneracao`.
        self.__indice_remuneracao: dict[str, list[str]] | None = None

    def _carregar_dataframe_filtrado(
        self,
        arquivo: Path,
        operadora: str,
        debug: bool = False,
    ) -> pd.DataFrame | None:
        """
        Carrega um arquivo e remove linhas de totais.
        """

        df = carregar_dados(arquivo)

        if df is None or df.empty:
            return None

        df_filtrado = df[
            df.iloc[:, 5].isin(["00", "0", 0])
        ].copy()

        if debug:
            logger.info(
                "[DEBUG] Operadora=%s | Arquivo=%s | Linhas originais=%s | Linhas após filtro=%s",
                operadora,
                arquivo.name,
                len(df),
                len(df_filtrado),
            )

        return df_filtrado

    def _consolidar_arquivos(
        self,
        arquivos: list[Path],
        operadora: str,
        debug: bool = False,
    ) -> pd.DataFrame:
        """
        Carrega, filtra e consolida arquivos de uma operadora.
        """

        dfs_validos: list[pd.DataFrame] = []

        for arquivo in arquivos:
            df = self._carregar_dataframe_filtrado(
                arquivo=arquivo,
                operadora=operadora,
                debug=debug,
            )

            if df is not None and not df.empty:
                dfs_validos.append(df)

        df_consolidado = (
            pd.concat(dfs_validos, ignore_index=True)
            if dfs_validos
            else pd.DataFrame()
        )

        if debug:
            logger.info(
                "[DEBUG] Operadora=%s | Arquivos válidos=%s | Linhas consolidadas=%s",
                operadora,
                len(dfs_validos),
                len(df_consolidado),
            )

        return df_consolidado

    def _obter_operadoras(
        self,
        arquivos_detraf: dict[str, list[Path]],
        arquivos_expectativa: dict[str, list[Path]],
    ) -> set[str]:
        """
        Retorna a união das operadoras encontradas nos dois dicionários.
        """

        chave_ignorada = "OPERADORA_NAO_IDENTIFICADA"

        detraf_normalizado = {
            chave.upper(): arquivos
            for chave, arquivos in arquivos_detraf.items()
        }

        expectativa_normalizado = {
            chave.upper(): arquivos
            for chave, arquivos in arquivos_expectativa.items()
        }

        arquivos_detraf.clear()
        arquivos_detraf.update(detraf_normalizado)

        arquivos_expectativa.clear()
        arquivos_expectativa.update(expectativa_normalizado)

        chaves_detraf = {
            chave
            for chave in detraf_normalizado
            if chave != chave_ignorada
        }

        chaves_expectativa = {
            chave
            for chave in expectativa_normalizado
            if chave != chave_ignorada
        }

        return chaves_detraf | chaves_expectativa

    @staticmethod
    def _converter_coluna_numerica(
        serie: pd.Series, rotulo: str = "coluna numérica"
    ) -> pd.Series:
        """
        Converte texto em formato brasileiro (vírgula decimal) para float.

        Valor que não converte vira **zero** — e isso é perigoso o bastante para
        merecer o aviso que esta função passou a emitir em 2026-08-06.

        🔴 **O caso que motivou o aviso: separador de milhar.** ``"1.234,56"``
        vira ``"1.234.56"`` depois do `replace`, o `to_numeric` desiste, e o
        `fillna(0)` transforma **mil duzentos e trinta e quatro reais em zero**,
        sem uma linha de log. Numa apuração de contestação, isso é uma diferença
        inventada — e a V2 **não define separador de milhar** para estes campos
        (pendência aberta), então não dá para simplesmente removê-lo aqui: uma
        planilha que use ponto como decimal viraria outro erro, silencioso do
        mesmo jeito.

        O comportamento **não muda** — zerar continua sendo o que acontece. O que
        muda é que passa a ser visível: quem homologa vê quantos valores caíram
        e quais eram, e pode dizer se o arquivo está errado ou se o código está.

        Args:
            serie: Coluna a converter.
            rotulo: Nome da coluna no aviso. Sem ele, "3 valores viraram zero"
                não diz em qual das duas colunas isso aconteceu.
        """
        original = serie.astype(str).str.strip()
        convertida = pd.to_numeric(
            original.str.replace(",", ".", regex=False), errors="coerce"
        )

        # Vazio já era zero antes desta função existir; não é perda de dado.
        perdidos = convertida.isna() & original.ne("") & original.str.lower().ne("nan")

        if perdidos.any():
            exemplos = original[perdidos].drop_duplicates().head(5).tolist()
            logger.error(
                f"[{rotulo}] {int(perdidos.sum())} valor(es) não puderam ser "
                f"convertidos para número e viraram ZERO: {exemplos}. "
                f"A causa mais comum é separador de milhar ('1.234,56'), que a "
                f"V2 não define para estes campos. Um valor zerado aqui vira "
                f"diferença inventada na contestação — confira o arquivo antes "
                f"de aceitar a apuração."
            )

        return convertida.fillna(0)

    def _enriquecer_com_tipo(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Acrescenta ``tipo_operacao`` e ``tipo_produto`` (a remuneração).

        - ``tipo_operacao``: tipo de serviço da **Credora** (col 0), do Anexo 5.
        - ``tipo_produto``: remuneração, classificada pelo **descritor** — a 7ª
          coluna, índice 6.

        🐛 **Corrigido em 2026-08-04 — a HU-09/HU-10 não executava.** Este método
        chamava ``bd_tabelas.obter_tipo_produto_por_poi``, que **não existe**: a
        unificação deliberadamente não migrou aquele método do Projeto 3, porque
        ele lia a coluna **POI** (índice 4) e tratava o valor como descritor (ver
        ``inventario-projeto-3.md``, achado B). O chamador ficou para trás, então
        toda execução real estourava com ``AttributeError`` — e, sem a tabela de
        contestação, o RPA 3 nunca receberia linha nenhuma.

        A fonte certa é a que a V2 nomeia:

            "A identificação da Remuneração regulada para a busca da tarifa deve
             ser baseada no campo DESC (descritor) **ou 7ª coluna** do arquivo
             de Detraf"

        🔴 **Corrigido em 2026-08-06 — defeito A4.** Até aqui a remuneração saía de
        ``classificar_descritor_remuneracao``, a regra fixa do Épico 2. O RPA 3,
        porém, monta a remuneração pelo **catálogo D-5**
        (``tbl_detraf_mapeamento_descritores``) e a usa como **parte da chave** do
        sinal do analista, comparando por igualdade exata de string.

        Os dois vocabulários só coincidem em ``TU-RL`` e ``VU-M``:

        ============  =================  ===============
        Fim do desc.  regra fixa (aqui)  catálogo (RPA 3)
        ============  =================  ===============
        ``L``         ``TU-RL``          ``TU-RL``
        ``V``         ``VU-M``           ``VU-M``
        ``C``         ``TUCOM``          ``TU-COM``
        ``I``         ``TU-RIU1/2``      ``TU-RIU``
        17 outros     ``None``           valor real
        ============  =================  ===============

        Ou seja: **para todo descritor que não terminasse em L ou V, o RPA 3 não
        encontrava o sinal** — e o sintoma era indistinguível de "o analista não
        sinalizou". Nenhum erro, nenhum aviso.

        Agora quem grava e quem lê usam a **mesma** fonte,
        `comum.dominio.mapa_remuneracao`, que é o que a V2 manda (*"validados a
        partir da tabela Descritor_Remuneração"*).

        ⚠️ A regra fixa **continua existindo e continua certa** — para a validação
        de tarifa, onde o vocabulário é o de ``tbl_detraf_tarifas``. Ver
        ``comum/dominio/classificadores.py``.
        """
        if df.empty:
            return df.copy()

        df = df.copy()

        credoras = df.iloc[:, 0].astype(str).str.strip()
        df["tipo_operacao"] = credoras.map(
            {eot: bd_tabelas.obter_tipo_servico_por_eot(eot) for eot in credoras.unique()}
        )

        df["tipo_produto"] = mr.resolver_series(
            df.iloc[:, 6], self._indice_remuneracao()
        )

        sem_catalogo = df["tipo_produto"].isna()
        nao_mapeados = int(sem_catalogo.sum())
        if nao_mapeados:
            # Descritor não mapeado é ignorado por regra (AI/09 §7), mas em
            # silêncio ele vira linha sem remuneração — que o RPA 3 nunca
            # encontra. Nomear os descritores é o que permite dizer se falta
            # linha na tabela ou se o arquivo veio com descritor inválido.
            exemplos = (
                df.loc[sem_catalogo]
                .iloc[:, 6]
                .astype(str)
                .str.strip()
                .drop_duplicates()
                .head(5)
                .tolist()
            )
            logger.warning(
                f"[HU-09] {nao_mapeados} linha(s) com descritor sem remuneração "
                f"na tabela `tbl_detraf_mapeamento_descritores`: {exemplos}. "
                f"Vão ao banco como TIS (final S) ou NAO_REGULADO e não serão "
                f"encontradas pelo RPA 3 — confira se falta linha na tabela."
            )
            # 🔴 2026-09-24 (e-mail da Luciana, 23/09/2026: `remuneracoes`
            # nulo). Descritor fora do catálogo continua "ignorado" para a
            # tarifa (AI/09 §7), mas a linha da contestação não pode ir ao
            # banco com `remuneracoes` NULL: SMS com final S sai `TIS` (o
            # mesmo valor do catálogo), o resto sai `NAO_REGULADO`.
            df.loc[sem_catalogo, "tipo_produto"] = (
                df.loc[sem_catalogo].iloc[:, 6].map(remuneracao_sem_catalogo)
            )

        return df

    def _indice_remuneracao(self) -> dict[str, list[str]]:
        """
        Índice ``descritor final -> remuneração``, memorizado por execução.

        É uma leitura de tabela inteira e a apuração roda por operadora — montá-lo
        a cada uma multiplicaria o custo pelo número de operadoras sem mudar o
        resultado. Mesmo motivo do `indice_remuneracao` do controller do RPA 3.
        """
        if self.__indice_remuneracao is None:
            mapa = mr.carregar_mapa_descritores(bd_tabelas.obter_mapa_descritores())
            self.__indice_remuneracao = mr.construir_indice_remuneracao(mapa)
        return self.__indice_remuneracao

    def _aplicar_analise_contestacao(self, df_contest: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica a camada analítica H10 sobre o df_contest montado na H9.

        Adiciona:
        - flag_contestacao: "S" se a variação atingir o limiar, "N" caso contrário.
        - modalidade_tarifa: somente para linhas VU-M em GH Reduzido (R).
          Depende do tipo de serviço da EOT Devedora (operadora), não da Credora.
          STFC → "NR" (não reduzido); SMP → "R" (reduzido).
        """
        df = df_contest.copy()

        # O limiar deixou de ser o literal `1.0` embutido aqui e passou a vir de
        # `comum.dominio.variacao`, junto com a regra (duplicação D-13).
        df["flag_contestacao"] = deve_contestar(df["variacao_pct"])

        mapa_tipo_serv = {
            eot: bd_tabelas.obter_tipo_servico_por_eot(eot)
            for eot in df["Devedora"].unique()
        }
        tipo_serv_devedora = df["Devedora"].map(mapa_tipo_serv)

        mascara_vum_r = (
            (df["tipo_produto"] == "VU-M") &
            (df["GH"].str.upper() == "R")
        )
        df["modalidade_tarifa"] = None
        df.loc[mascara_vum_r & (tipo_serv_devedora == "STFC"), "modalidade_tarifa"] = "NR"
        df.loc[mascara_vum_r & (tipo_serv_devedora == "SMP"),  "modalidade_tarifa"] = "R"

        return df

    @staticmethod
    def _preparar_dados_persistencia_contestacao(
        df_contest: pd.DataFrame, operadora: str
    ) -> pd.DataFrame:
        """
        Monta o DataFrame no formato de colunas da tabela
        'tbl_rpa_log_detraf_despesa_contestacao' — schema confirmado em
        'DOCS/Outros arquivos auxiliares/Tabelas para o RPA alimentar o
        Webfat - despesa.xlsx' (aba 'Contestação'). Colunas 'id' (AI PK) e
        'created_at' (default do banco) não são preenchidas aqui.

        **Quem é quem** (V2, seção *Regras de negócio*):

            "1ª coluna ou 'Credora' deve estar preenchida com uma EOT
             relacionada **à operadora**."
            "2ª coluna ou 'Devedora' deve estar preenchida com uma das EOTs
             **da Vivo**."

        Daí: ``eot_operadora`` ← Credora e ``eot_tbra`` ← Devedora, que é o que o
        schema descreve. `validacao_colunas._mascara_col_2_eot_vivo` confirma —
        ela valida a coluna de índice 1 (Devedora) contra os nomes fantasia da
        Vivo.

        ⚠️ Esta docstring afirmava a convenção **invertida** ("Credora = EOT
        Vivo, Devedora = EOT da operadora"), e era dela que vinha o defeito de
        ``tipo_servico_vivo`` corrigido abaixo. Os EOTs sempre estiveram certos;
        a explicação é que estava trocada.

        'carga_agi' e 'tipo_contestacao' ficam com valores iniciais, pois
        são preenchidos/atualizados posteriormente (HU-18 e HU-11/HU-16).
        """
        if df_contest.empty:
            return pd.DataFrame()

        minutos_diferenca = df_contest["Minutos_op"] - df_contest["Minutos_tbra"]

        # Mesma reconciliação aplicada ao valor bruto: a base do percentual
        # passou da expectativa para o lado operadora (duplicação D-13).
        minutos_variacao_perc = calcular_variacao(
            df_contest["Minutos_op"], df_contest["Minutos_tbra"]
        )

        # 🐛 Corrigido em 2026-08-04. A coluna recebia `tipo_operacao`, que
        # `_enriquecer_com_tipo` deriva da **Credora** — ou seja, o tipo de
        # serviço da *operadora*, gravado numa coluna chamada "vivo".
        #
        # A prova de que estava errado é interna ao próprio RPA 2:
        # `resultado_validacao.py` preenche a mesma coluna a partir da
        # **Devedora**. Dois módulos do mesmo robô gravavam lados opostos.
        tipo_servico_vivo = df_contest["Devedora"].map(
            {
                eot: bd_tabelas.obter_tipo_servico_por_eot(eot)
                for eot in df_contest["Devedora"].unique()
            }
        )

        return pd.DataFrame({
            "tipo_servico_vivo": tipo_servico_vivo,
            "eot_tbra": df_contest["Devedora"],
            "eot_operadora": df_contest["Credora"],
            "empresa": operadora,
            "referencia": df_contest["Referencia"],
            "trafego": df_contest["Trafego"],
            # ACRÉSCIMO DA UNIFICAÇÃO — o Projeto 3 não gravava a remuneração,
            # mas o Projeto 4 lê esta tabela por uma chave que a inclui
            # (`COLUNAS_CHAVE_DESPESA_CONTESTACAO`). Sem esta coluna o RPA 3
            # nunca casaria uma linha escrita pelo RPA 2 — ver duplicação D-15.
            # O dado já existia aqui, com outro nome (`tipo_produto`).
            #
            # ⚠️ A chave é o nome da COLUNA NO BANCO: `remuneracoes`, plural.
            # Até 2026-08-06 gravava-se `remuneracao`, que não existe lá — o
            # INSERT inteiro falhava. Ver `tabelas.COL_CONTESTACAO_REMUNERACOES`.
            tabelas.COL_CONTESTACAO_REMUNERACOES: df_contest["tipo_produto"],
            "minutos_tbra": df_contest["Minutos_tbra"],
            "vb_tbra": df_contest["RS_tbra"],
            "minutos_operadora": df_contest["Minutos_op"],
            "vb_operadora": df_contest["RS_op"],
            "minutos_diferenca": minutos_diferenca,
            "vb_diferenca": df_contest["variacao_rs"],
            "minutos_variacao_perc": minutos_variacao_perc,
            "vb_variacao_perc": df_contest["variacao_pct"],
            "carga_agi": CARGA_AGI_NAO_CARREGADO,
            "tipo_contestacao": None,
        })

    def _comparar_e_persistir(
        self,
        df_detraf: pd.DataFrame,
        df_expectativa: pd.DataFrame,
        operadora: str,
    ) -> None:
        """
        Compara o Detraf da operadora com a expectativa Vivo e grava no banco.

        Era `_gerar_aba_contest`: o resultado ia para a aba "Contest" de um
        `.xlsx` **e** para o banco. A aba deixou de existir (a Base de Contestação
        é a tabela), então o nome passou a dizer o que o método faz.

        Dimensões do agrupamento: Devedora, tipo_operacao, tipo_produto, Trafego, GH
        Métricas: Minutos e R$_Bruto (somados por dimensão)
        Colunas de saída adicionais: variacao_rs (absoluta) e variacao_pct (percentual)

        Índices de coluna usados:
            1 → Devedora | 3 → Trafego | 7 → GH | 9 → Minutos | 14 → R$_Bruto
        """
        DIMS = ["Devedora", "tipo_operacao", "tipo_produto", "Trafego", "GH"]

        def _preparar_agregado(df_enr: pd.DataFrame, sufixo: str) -> pd.DataFrame:
            if df_enr.empty:
                return pd.DataFrame(
                    columns=DIMS
                    + ["Credora", "Referencia", f"Minutos_{sufixo}", f"RS_{sufixo}"]
                )

            df_work = df_enr.copy()
            df_work["Credora"] = df_work.iloc[:, 0].astype(str).str.strip()
            df_work["Devedora"] = df_work.iloc[:, 1].astype(str).str.strip()
            df_work["Referencia"] = df_work.iloc[:, 2].astype(str).str.strip()
            df_work["Trafego"] = df_work.iloc[:, 3].astype(str).str.strip()
            df_work["GH"] = df_work.iloc[:, 7].astype(str).str.strip()
            df_work["Minutos"] = self._converter_coluna_numerica(
                df_work.iloc[:, 9], rotulo="Minutos (coluna 10)"
            )
            df_work["R$_Bruto"] = self._converter_coluna_numerica(
                df_work.iloc[:, 14], rotulo="R$_Bruto (coluna 15)"
            )

            return (
                df_work
                .groupby(DIMS, dropna=False)
                .agg(
                    Credora=("Credora", "first"),
                    Referencia=("Referencia", "first"),
                    **{
                        f"Minutos_{sufixo}": ("Minutos", "sum"),
                        f"RS_{sufixo}": ("R$_Bruto", "sum"),
                    },
                )
                .reset_index()
            )

        df_det_enr = self._enriquecer_com_tipo(df_detraf)
        df_exp_enr = self._enriquecer_com_tipo(df_expectativa)

        df_agg_det = _preparar_agregado(df_det_enr, "op")
        df_agg_exp = _preparar_agregado(df_exp_enr, "tbra")

        if df_agg_det.empty and df_agg_exp.empty:
            logger.warning(
                "Nenhum dado para gerar aba Contest da operadora '%s'.", operadora
            )
            return

        df_contest = df_agg_det.merge(
            df_agg_exp, on=DIMS, how="outer", suffixes=("_op", "_tbra")
        )

        # Credora e Referencia não fazem parte das dimensões de agrupamento
        # (assumidas constantes por lado), mas são necessárias para a
        # persistência em tbl_rpa_log_detraf_despesa_contestacao.
        df_contest["Credora"] = df_contest["Credora_op"].fillna(
            df_contest["Credora_tbra"]
        )
        df_contest["Referencia"] = df_contest["Referencia_op"].fillna(
            df_contest["Referencia_tbra"]
        )
        df_contest = df_contest.drop(
            columns=["Credora_op", "Credora_tbra", "Referencia_op", "Referencia_tbra"]
        )

        colunas_numericas = ["Minutos_op", "RS_op", "Minutos_tbra", "RS_tbra"]
        df_contest[colunas_numericas] = df_contest[colunas_numericas].fillna(0)

        df_contest["variacao_rs"] = df_contest["RS_op"] - df_contest["RS_tbra"]

        # MUDANÇA DE COMPORTAMENTO DA UNIFICAÇÃO — a variação passou a ser
        # calculada por `comum.dominio.variacao`, que é o único ponto do
        # repositório a implementar a regra.
        #
        # A implementação anterior era:
        #     variacao_pct = variacao_rs / RS_tbra.replace(0, pd.NA) * 100
        #
        # Diferenças em relação a ela (ver duplicação D-13 e pendência Q2):
        #   - base do percentual: passou de RS_tbra (expectativa) para RS_op
        #     (operadora), porque a V2 diz que o Detraf oficial da operadora é a
        #     origem dos dados;
        #   - expectativa ausente: antes virava NA -> flag "N", ou seja, deixava
        #     de contestar o caso mais contestável; agora dá 100% -> "S", como a
        #     V2 determina ("apresentar os valores zerados de expectativas").
        #
        # O sinal continua importando, como já era aqui — só se contesta quando
        # a operadora apresentou mais que a expectativa.
        df_contest["variacao_pct"] = calcular_variacao(
            df_contest["RS_op"], df_contest["RS_tbra"]
        )

        # H10 — flag de contestação e modalidade de tarifa VU-M
        df_contest = self._aplicar_analise_contestacao(df_contest)

        df_persistencia = self._preparar_dados_persistencia_contestacao(
            df_contest, operadora
        )
        bd_tabelas.salvar_dados_tabela_contestacao(df_persistencia)

        logger.info(
            "Contestação de '%s' gravada em tbl_rpa_log_detraf_despesa_contestacao "
            "| Linhas: %s",
            operadora,
            len(df_persistencia),
        )

    def _organizar_arquivos_por_operadora(
        self,
        arquivos_detraf: dict[str, list[Path]],
        arquivos_expectativa: dict[str, list[Path]],
        debug: bool = False,
    ) -> None:
        """
        Consolida os arquivos de cada operadora e grava o comparativo no banco.
        """

        operadoras = self._obter_operadoras(
            arquivos_detraf,
            arquivos_expectativa,
        )

        for operadora in operadoras:
            df_detraf = self._consolidar_arquivos(
                arquivos=arquivos_detraf.get(operadora, []),
                operadora=operadora,
                debug=debug,
            )

            df_expectativa = self._consolidar_arquivos(
                arquivos=arquivos_expectativa.get(operadora, []),
                operadora=operadora,
                debug=debug,
            )

            self._comparar_e_persistir(df_detraf, df_expectativa, operadora)

    def apurar_contestacao(
        self,
        arquivos_detraf: dict[str, list[Path]],
        arquivos_expectativa: dict[str, list[Path]],
    ) -> None:
        """
        Ponto de entrada da HU-09/HU-10.

        Era `criar_arquivo_contestacao`, e recebia a pasta de saída do `.xlsx`.
        Não há mais arquivo — o resultado é a tabela.
        """
        logger.info("Iniciando a apuração da contestação.")
        self._organizar_arquivos_por_operadora(
            arquivos_detraf, arquivos_expectativa, debug=True
        )
