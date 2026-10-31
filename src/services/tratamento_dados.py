import re
import time
from pathlib import Path

import pandas as pd


# Raiz do projeto
DIRETORIO_RAIZ = Path(__file__).resolve().parent.parent.parent

# Pasta onde o coletor salva os arquivos
DIRETORIO_LOGS = DIRETORIO_RAIZ / "logs"

# Pasta onde serão salvas as bases tratadas
DIRETORIO_BASE_TRATADA = (
    DIRETORIO_RAIZ / "base_tratada"
)


def localizar_arquivos_csv():
    """
    Localiza todos os arquivos CSV dentro das
    pastas semanais da pasta logs.
    """

    arquivos = list(
        DIRETORIO_LOGS.glob(
            "semana_*/*.csv"
        )
    )

    return sorted(arquivos)


def ler_csv_com_tentativas(
    caminho_arquivo,
    tentativas=3,
    intervalo=2,
):
    """
    Lê um CSV com novas tentativas.

    Isso reduz o risco de erro caso o app_coleta
    esteja gravando no arquivo no mesmo momento.
    """

    for tentativa in range(
        1,
        tentativas + 1,
    ):
        try:
            dataframe = pd.read_csv(
                caminho_arquivo,
                encoding="utf-8-sig",
            )

            return dataframe

        except Exception as erro:
            print(
                f"[LEITURA] Tentativa "
                f"{tentativa}/{tentativas} falhou "
                f"para {caminho_arquivo.name}: "
                f"{erro}"
            )

            time.sleep(intervalo)

    print(
        f"[LEITURA] Arquivo ignorado após "
        f"{tentativas} tentativas: "
        f"{caminho_arquivo}"
    )

    return pd.DataFrame()


def consolidar_logs():
    """
    Consolida todos os arquivos CSV semanais
    em um único DataFrame.
    """

    arquivos = localizar_arquivos_csv()

    if not arquivos:
        print(
            "[CONSOLIDAÇÃO] Nenhum arquivo CSV "
            "foi encontrado."
        )

        return pd.DataFrame()

    bases = []

    for arquivo in arquivos:
        dataframe = ler_csv_com_tentativas(
            arquivo
        )

        if dataframe.empty:
            continue

        # Registra de qual pasta semanal veio o dado
        dataframe["semana_origem"] = (
            arquivo.parent.name
        )

        # Caso o CSV não tenha a tabela de origem,
        # utiliza o nome do próprio arquivo
        if "tabela_origem" not in dataframe.columns:
            dataframe["tabela_origem"] = (
                arquivo.stem
            )

        bases.append(dataframe)

        print(
            f"[CONSOLIDAÇÃO] "
            f"{arquivo.name}: "
            f"{len(dataframe)} registro(s)."
        )

    if not bases:
        print(
            "[CONSOLIDAÇÃO] Nenhuma base válida "
            "foi encontrada."
        )

        return pd.DataFrame()

    base_consolidada = pd.concat(
        bases,
        ignore_index=True,
    )

    # Converte as colunas de data
    base_consolidada["data_log"] = pd.to_datetime(
        base_consolidada["data_log"],
        errors="coerce",
    )

    if "data_extracao" in base_consolidada.columns:
        base_consolidada["data_extracao"] = (
            pd.to_datetime(
                base_consolidada["data_extracao"],
                errors="coerce",
            )
        )

    # Remove registros duplicados
    if "chave_registro" in base_consolidada.columns:
        base_consolidada = (
            base_consolidada
            .drop_duplicates(
                subset=["chave_registro"],
                keep="last",
            )
        )
    else:
        base_consolidada = (
            base_consolidada
            .drop_duplicates(
                subset=[
                    "tabela_origem",
                    "id",
                ],
                keep="last",
            )
        )

    base_consolidada = (
        base_consolidada
        .sort_values(
            by="data_log",
            ascending=True,
            na_position="last",
        )
        .reset_index(drop=True)
    )

    print(
        f"[CONSOLIDAÇÃO] Total consolidado: "
        f"{len(base_consolidada)} registro(s)."
    )

    return base_consolidada

def identificar_nivel_log(descricao):
    """
    Identifica se o registro é INFO,
    WARNING, ERROR ou não identificado.
    """

    texto = str(descricao).strip().upper()

    if texto.startswith("ERROR"):
        return "ERROR"

    if texto.startswith("WARNING"):
        return "WARNING"

    if texto.startswith("INFO"):
        return "INFO"

    # Usa o status textual como apoio
    if "ERROR" in texto:
        return "ERROR"

    if "WARNING" in texto:
        return "WARNING"

    return "NAO_IDENTIFICADO"


def classificar_evento(nivel_log):
    """
    Converte o nível técnico em uma
    classificação operacional.
    """

    classificacoes = {
        "INFO": "Normal",
        "WARNING": "Atencao",
        "ERROR": "Falha",
        "NAO_IDENTIFICADO": "Revisar",
    }

    return classificacoes.get(
        nivel_log,
        "Revisar",
    )

def normalizar_descricao(descricao):
        """
        Cria uma versão simplificada da descrição
        para análise e futuro Machine Learning.

        A descrição original não é alterada.
        """

        texto = str(descricao).lower()

        # Remove quebras de linha e tabulações
        texto = re.sub(
            r"[\r\n\t]+",
            " ",
            texto,
        )

        # Remove endereços de e-mail
        texto = re.sub(
            r"\b[\w\.-]+@[\w\.-]+\.\w+\b",
            " email_removido ",
            texto,
        )

        # Remove URLs
        texto = re.sub(
            r"https?://\S+",
            " url_removida ",
            texto,
        )

        # Remove caminhos do Windows
        texto = re.sub(
            r"[a-zA-Z\]:\\(?:[^\\\s]+\\)*[^\\\s]*",
            " caminho_removido ",
            texto,
        )

        # Remove números longos, como IDs de instâncias
        texto = re.sub(
            r"\b\d{5,}\b",
            " id_removido ",
            texto,
        )

        # Remove endereços hexadecimais
        texto = re.sub(
            r"0x[0-9a-f]+",
            " endereco_removido ",
            texto,
        )

        # Remove linhas repetitivas do ChromeDriver
        texto = re.sub(
            r"chromedriver![^\s]+",
            " ",
            texto,
        )

        # Remove o conteúdo após Stacktrace
        texto = re.split(
            r"stacktrace:",
            texto,
            maxsplit=1,
        )[0]

        # Remove espaços repetidos
        texto = re.sub(
            r"\s+",
            " ",
            texto,
        )

        return texto.strip()

def criar_base_tratada():
    """
    Consolida os logs e cria a base tratada.
    """

    base = consolidar_logs()

    if base.empty:
        return pd.DataFrame()

    # Preserva a descrição original
    base = base.rename(
        columns={
            "descricao": "descricao_original"
        }
    )

    # Identifica o nível do log
    base["nivel_log"] = (
        base["descricao_original"]
        .apply(identificar_nivel_log)
    )

    # Classificação operacional
    base["classificacao_evento"] = (
        base["nivel_log"]
        .apply(classificar_evento)
    )

    # Cria a descrição tratada
    base["descricao_normalizada"] = (
        base["descricao_original"]
        .apply(normalizar_descricao)
    )

    # Variáveis temporais
    base["hora"] = (
        base["data_log"].dt.hour
    )

    base["dia_semana"] = (
        base["data_log"].dt.dayofweek
    )

    base["data_evento"] = (
        base["data_log"].dt.date
    )

    # Indica quais registros exigem atenção
    base["necessita_atencao"] = (
        base["nivel_log"]
        .isin(
            [
                "WARNING",
                "ERROR",
            ]
        )
    )

    DIRETORIO_BASE_TRATADA.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho_completo = (
        DIRETORIO_BASE_TRATADA
        / "base_logs_tratada.csv"
    )

    caminho_atencao = (
        DIRETORIO_BASE_TRATADA
        / "eventos_atencao.csv"
    )

    # Salva todos os registros tratados
    base.to_csv(
        caminho_completo,
        index=False,
        encoding="utf-8-sig",
    )

    # Salva somente WARNING e ERROR
    eventos_atencao = base[
        base["necessita_atencao"]
    ].copy()

    eventos_atencao.to_csv(
        caminho_atencao,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        f"[TRATAMENTO] Base tratada: "
        f"{caminho_completo}"
    )

    print(
        f"[TRATAMENTO] Eventos de atenção: "
        f"{caminho_atencao}"
    )

    return base
