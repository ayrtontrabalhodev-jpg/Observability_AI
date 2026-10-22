from pathlib import Path

import pandas as pd


DIRETORIO_RAIZ = Path(__file__).resolve().parent.parent.parent
DIRETORIO_BASE_TRATADA = DIRETORIO_RAIZ / "base_tratada"


def classificar_categoria_inicial(descricao):
    """
    Cria uma sugestão inicial de categoria.

    Essa sugestão deve passar por validação humana
    antes de entrar no treinamento.
    """

    texto = str(descricao).lower()

    if "timeout" in texto:
        return "Timeout"

    if "element click intercepted" in texto:
        return "Interface web"

    if (
        "no such element" in texto
        or "element not found" in texto
        or "unable to locate element" in texto
    ):
        return "Elemento nao encontrado"

    if "invalid selector" in texto:
        return "Seletor invalido"

    if (
        "connection refused" in texto
        or "connection reset" in texto
        or "connection error" in texto
    ):
        return "Conexao"

    if (
        "file not found" in texto
        or "arquivo nao encontrado" in texto
        or "no such file" in texto
    ):
        return "Arquivo"

    if (
        "permission denied" in texto
        or "access is denied" in texto
    ):
        return "Permissao"

    if (
        "missing 1 required positional argument"
        in texto
        or "typeerror" in texto
        or "attributeerror" in texto
    ):
        return "Codigo Python"

    if (
        "webdriver" in texto
        or "chromedriver" in texto
    ):
        return "WebDriver"

    if "capacidade de agendamento" in texto:
        return "Capacidade"

    return "Revisar"


def criar_base_classificacao(base_tratada):
    """
    Seleciona eventos de atenção e cria uma base
    para validação manual.
    """

    if base_tratada.empty:
        return pd.DataFrame()

    eventos = base_tratada[
        base_tratada["necessita_atencao"]
    ].copy()

    eventos["categoria_sugerida"] = (
        eventos["descricao_normalizada"]
        .apply(classificar_categoria_inicial)
    )

    # Campo que será preenchido após validação
    eventos["categoria_validada"] = ""

    eventos["status_validacao"] = "Pendente"

    caminho = (
        DIRETORIO_BASE_TRATADA
        / "base_classificacao.csv"
    )

    eventos.to_csv(
        caminho,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        f"[CLASSIFICACAO] Base para validação: "
        f"{caminho}"
    )

    return eventos