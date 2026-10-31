from pathlib import Path
import pandas as pd
from comum.config.logger_config import logger
from comum.arquivos.gerenciador import carregar_dados, salvar_dados
from comum.dados.repositorio_tabelas import bd_tabelas


class LimpadorTrafegos:
    """
    Classe responsável por:

    - Carregar um arquivo CSV/XLSX através da função carregar_dados
    - Separar linhas válidas e inválidas baseado em fluxos dinâmicos (BK, LL, etc.)
    - Remover linhas com coluna index 5 (Rel) == 01/1
    - Adicionar linha de totalização
    - Sobrescrever o arquivo original com linhas válidas
    - Criar arquivo de backup com as linhas filtradas conforme o fluxo selecionado
    """

    COLUNA_REL = 5
    COLUNAS_SOMAR = [8, 9, 11, 12, 13, 14]

    def __init__(self):
        """
        Inicializa o mapeamento de fluxos. Para adicionar futuros novos fluxos,
        basta criar o método correspondente e registrá-lo neste dicionário.
        """
        self._fluxos_disponiveis = {
            "BK": self.separar_linhas_bk,
            "LL": self.separar_linhas_ll,  # Novo fluxo adicionado como template
        }

    def executar(
        self,
        caminho_arquivo: Path,
        tipo_fluxo: str,
        sufixo: str,
        debug: bool = False,
        gerar_arquivos: bool = True,
    ) -> bool:
        """
        Separa os tráfegos de um fluxo (`_BK`, `_LL`) e grava o arquivo de backup.

        Returns:
            ``True`` se o arquivo atende ao fluxo; ``False`` caso contrário.

        Raises:
            RuntimeError: Se a leitura, a separação ou a gravação falharem.

        ⚠️ **Não engula a exceção aqui.** Até 2026-08-04 o ``except`` logava e o
        método caía num ``return True`` no fim — ou seja, reportava que a limpeza
        deu certo mesmo com o arquivo falhado, e o Detraf seguia para a validação
        como se estivesse íntegro. Quem chama (`validacao_detrafs._validar_fluxo`)
        **já** trata exceção marcando o arquivo em ``arquivos_invalidos``; propagar
        é o que aciona esse caminho.
        """
        try:
            fluxo_formatado = tipo_fluxo.upper()

            df = carregar_dados(caminho_arquivo)
            total_linhas_original = len(df)

            if debug:
                logger.info(f"Arquivo carregado com {total_linhas_original} linhas")

            self._filtrar_rel(df)

            if debug:
                logger.info(
                    f"Linhas removidas do arquivo válido por Rel=01: "
                    f"{total_linhas_original - len(df)}"
                )

            # Executa dinamicamente a função correspondente ao fluxo selecionado
            funcao_separadora = self._fluxos_disponiveis[fluxo_formatado]
            resultado = funcao_separadora(df, debug=debug)

            # Centraliza a verificação do tipo de retorno
            arquivo_atende_fluxo = not isinstance(resultado, pd.DataFrame)

            if debug:
                if arquivo_atende_fluxo:
                    logger.info(f"Arquivo atende ao fluxo {fluxo_formatado}.")
                else:
                    logger.info(f"Arquivo NÃO atende ao fluxo {fluxo_formatado}.")

            # Se não for para gerar arquivos, encerra aqui
            if not gerar_arquivos:
                return arquivo_atende_fluxo

            if not arquivo_atende_fluxo:
                if debug:
                    logger.info(
                        f"Arquivo não possui linhas para segregação no fluxo _{fluxo_formatado}: {caminho_arquivo}"
                    )
                return False

            # Desempacota com segurança e aplica a função de totalização
            df_valido, df_backup = resultado
            df_valido = self._adicionar_linha_total(df_valido)
            df_backup = self._adicionar_linha_total(df_backup)

            # O sufixo do backup passa a ser dinâmico (_BK, _LL, etc.)
            caminho_backup = self._gerar_caminho_backup(caminho_arquivo, sufixo=sufixo)

            salvar_dados(df_valido, caminho_arquivo)
            salvar_dados(df_backup, caminho_backup)

            if debug:
                logger.info(
                    f"Arquivo original sobrescrito: {caminho_arquivo} "
                    f"({len(df_valido)} linhas)"
                )

                logger.info(
                    f"Arquivo backup criado: {caminho_backup} "
                    f"({len(df_backup)} linhas)"
                )

        except Exception as erro:
            raise RuntimeError(
                f"Falha ao separar os tráfegos do fluxo {tipo_fluxo.upper()} em "
                f"[{caminho_arquivo}]: {erro}"
            ) from erro

        return True

    def separar_linhas_bk(
        self,
        df: pd.DataFrame,
        debug: bool = False,
    ) -> tuple[pd.DataFrame, pd.DataFrame] | pd.DataFrame:
        """
        Identifica e separa as linhas que pertencem ao fluxo _BK com base em 3 condições:
        1. Coluna DESC inicia com 'L' e termina com 'V'.
        2. Tipo de serviço da EOT é igual a 'SMP'.
        3. Tipo de concessão da EOT é diferente de 'P'.
        Apresenta um relatório estatístico no final caso o parâmetro debug esteja ativo.
        """
        linhas_original = df.shape[0]

        if linhas_original == 0:
            if debug:
                logger.info(
                    "Resumo_BK -> DataFrame original está vazio. 0 linhas processadas."
                )
            return df

        # --- CONDIÇÃO 1: Validação da coluna DESC (Índice 6) ---
        coluna_desc = df.iloc[:, 6].astype(str).str.strip()
        mascara_desc = coluna_desc.str.upper().str.startswith(
            "L"
        ) & coluna_desc.str.upper().str.endswith("V")

        if not mascara_desc.any():
            if debug:
                logger.info(
                    f"Resumo_BK -> Total Original: {linhas_original} | "
                    f"Linhas _BK encontradas: 0 | df_filtrado: {linhas_original} | df_bk: 0"
                )
            return df

        # --- PREPARAÇÃO PARA AS CONDIÇÕES 2 e 3 (Otimização de Banco) ---
        eots_candidatos = (
            df.loc[mascara_desc, df.columns[0]].astype(str).unique().tolist()
        )

        mapa_servico = {}
        mapa_concessao = {}

        for eot in eots_candidatos:
            mapa_servico[eot] = bd_tabelas.obter_tipo_servico_por_eot(eot)
            mapa_concessao[eot] = bd_tabelas.obter_concessao_por_eot(eot)

        coluna_eot_str = df.iloc[:, 0].astype(str)
        valores_servico = coluna_eot_str.map(mapa_servico)
        valores_concessao = coluna_eot_str.map(mapa_concessao)

        # --- CONDIÇÃO 2 & 3: Verificação dos dados do banco ---
        mascara_servico = valores_servico == "SMP"
        mascara_concessao = valores_concessao != "P"

        # --- MÁSCARA FINAL DO FLUXO _BK ---
        mascara_fluxo_bk = mascara_desc & mascara_servico & mascara_concessao

        if not mascara_fluxo_bk.any():
            if debug:
                logger.info(
                    f"Resumo_BK -> Total Original: {linhas_original} | "
                    f"Linhas _BK encontradas: 0 | df_filtrado: {linhas_original} | df_bk: 0"
                )
            return df

        # --- SEPARAÇÃO DOS DATAFRAMES ---
        df_bk = df[mascara_fluxo_bk].reset_index(drop=True)
        df_filtrado = df[~mascara_fluxo_bk].reset_index(drop=True)

        if debug:
            logger.info(
                f"Resumo_BK -> Total Original: {linhas_original} | "
                f"Linhas _BK encontradas: {df_bk.shape[0]} | "
                f"df_filtrado: {df_filtrado.shape[0]} | "
                f"df_bk: {df_bk.shape[0]}"
            )

        return df_filtrado, df_bk

    def _filtrar_rel(self, df: pd.DataFrame) -> int:
        """
        Remove linhas onde coluna Rel (index 5) possui valor: 1, 01, 1.0, etc.
        """
        total_antes = len(df)

        valores_rel = (
            df.iloc[:, self.COLUNA_REL]
            .astype(str)
            .str.strip()
            .str.lstrip("0")
            .replace("", "0")
        )

        mascara_remover = valores_rel == "1"
        df.drop(index=df[mascara_remover].index, inplace=True)
        df.reset_index(drop=True, inplace=True)

        return total_antes - len(df)

    def _adicionar_linha_total(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adiciona linha final com totalização.
        """
        if df.empty:
            linha_total = [""] * len(df.columns)
            if len(df.columns) > self.COLUNA_REL:
                linha_total[self.COLUNA_REL] = "01"

            return pd.concat(
                [df, pd.DataFrame([linha_total], columns=df.columns)],
                ignore_index=True,
            )

        linha_total = {}

        for idx, coluna in enumerate(df.columns):
            if idx == self.COLUNA_REL:
                linha_total[coluna] = "01"
                continue

            if idx in self.COLUNAS_SOMAR:
                valores = pd.to_numeric(
                    df[coluna]
                    .astype(str)
                    .str.strip()
                    .str.replace(".", "", regex=False)
                    .str.replace(",", ".", regex=False),
                    errors="coerce",
                )
                linha_total[coluna] = round(valores.sum(), 5)
            else:
                linha_total[coluna] = ""

        df_total = pd.DataFrame([linha_total], columns=df.columns)
        return pd.concat([df, df_total], ignore_index=True)

    def _gerar_caminho_backup(self, caminho_arquivo: Path, sufixo: str) -> Path:
        """
        Gera caminho dinamicamente colocando o sufixo do fluxo atual antes da extensão.
        Exemplo: arquivo.csv -> arquivo_BK.csv
        """
        path = Path(caminho_arquivo)
        return path.with_name(f"{path.stem}{sufixo.upper()}{path.suffix}")

    def separar_linhas_ll(
        self,
        df: pd.DataFrame,
        debug: bool = False,
    ) -> tuple[pd.DataFrame, pd.DataFrame] | pd.DataFrame:
        """
        Identifica e separa as linhas que pertencem ao fluxo _LL com base em 2 condições:
        1. Coluna DESC inicia e termina com 'L'.
        2. Tipo de serviço da EOT é igual a 'STFC'.
        Apresenta um relatório estatístico no final caso o parâmetro debug esteja ativo.
        """
        linhas_original = df.shape[0]

        if linhas_original == 0:
            if debug:
                logger.info(
                    "Resumo_LL -> DataFrame original está vazio. 0 linhas processadas."
                )
            return df

        # --- CONDIÇÃO 1: Validação da coluna DESC (Índice 6) ---
        # Verifica se inicia com 'L' e termina com 'L'
        coluna_desc = df.iloc[:, 6].astype(str).str.strip().str.upper()
        mascara_desc = coluna_desc.str.startswith("L") & coluna_desc.str.endswith("L")

        if not mascara_desc.any():
            if debug:
                logger.info(
                    f"Resumo_LL -> Total Original: {linhas_original} | "
                    f"Linhas _LL encontradas: 0 | df_filtrado: {linhas_original} | df_ll: 0"
                )
            return df

        # --- PREPARAÇÃO PARA A CONDIÇÃO 2 (Otimização de Banco) ---
        eots_candidatos = (
            df.loc[mascara_desc, df.columns[0]].astype(str).unique().tolist()
        )

        mapa_servico = {}
        for eot in eots_candidatos:
            mapa_servico[eot] = bd_tabelas.obter_tipo_servico_por_eot(eot)

        coluna_eot_str = df.iloc[:, 0].astype(str)
        valores_servico = coluna_eot_str.map(mapa_servico)

        # --- CONDIÇÃO 2: Verificação dos dados do banco ---
        mascara_servico = valores_servico == "STFC"

        # --- MÁSCARA FINAL DO FLUXO _LL ---
        mascara_fluxo_ll = mascara_desc & mascara_servico

        if not mascara_fluxo_ll.any():
            if debug:
                logger.info(
                    f"Resumo_LL -> Total Original: {linhas_original} | "
                    f"Linhas _LL encontradas: 0 | df_filtrado: {linhas_original} | df_ll: 0"
                )
            return df

        # --- SEPARAÇÃO DOS DATAFRAMES ---
        df_ll = df[mascara_fluxo_ll].reset_index(drop=True)
        df_filtrado = df[~mascara_fluxo_ll].reset_index(drop=True)

        if debug:
            logger.info(
                f"Resumo_LL -> Total Original: {linhas_original} | "
                f"Linhas _LL encontradas: {df_ll.shape[0]} | "
                f"df_filtrado: {df_filtrado.shape[0]} | "
                f"df_ll: {df_ll.shape[0]}"
            )

        return df_filtrado, df_ll
