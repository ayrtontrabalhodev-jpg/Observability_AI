from datetime import datetime
from pathlib import Path

import pandas as pd


# ==================================================
# CAMINHOS
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent.parent
diretorio_base = diretorio_raiz / "base_tratada_rifaina"

arquivo_falhas = diretorio_base / "rifaina_falhas.csv"
arquivo_classificacao = diretorio_base / "rifaina_classificacao_falhas.csv"

arquivo_base_completa = (
    diretorio_base / "rifaina_base_classificada_completa.csv"
)

arquivo_base_treinamento = (
    diretorio_base / "rifaina_base_treinamento.csv"
)

arquivo_revisao_humana = (
    diretorio_base / "rifaina_revisao_humana.csv"
)

arquivo_resumo_treinamento = (
    diretorio_base / "resumo_base_treinamento.csv"
)


# ==================================================
# LEITURA SEGURA
# ==================================================

def ler_csv(caminho_arquivo):
    """
    Lê um arquivo CSV usando codificações comuns.
    """

    if not caminho_arquivo.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho_arquivo}"
        )

    codificacoes = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1",
    ]

    ultimo_erro = None

    for codificacao in codificacoes:
        try:
            return pd.read_csv(
                caminho_arquivo,
                encoding=codificacao,
                low_memory=False,
            )

        except UnicodeDecodeError as erro:
            ultimo_erro = erro

        except pd.errors.EmptyDataError:
            print(
                f"[TREINAMENTO] Arquivo vazio: "
                f"{caminho_arquivo.name}"
            )

            return pd.DataFrame()

        except Exception as erro:
            ultimo_erro = erro
            break

    raise RuntimeError(
        f"Não foi possível ler {caminho_arquivo.name}: "
        f"{type(ultimo_erro).__name__}: {ultimo_erro}"
    )


# ==================================================
# VALIDAÇÃO DAS BASES
# ==================================================

def validar_base_falhas(base):
    """
    Valida as colunas necessárias da base
    de ocorrências de falha.
    """

    colunas_obrigatorias = {
        "chave_registro",
        "descricao_original",
        "descricao_normalizada",
        "data_log",
        "rpa",
        "status",
    }

    colunas_ausentes = (
        colunas_obrigatorias
        - set(base.columns)
    )

    if colunas_ausentes:
        raise ValueError(
            "Colunas ausentes em rifaina_falhas.csv: "
            + ", ".join(
                sorted(colunas_ausentes)
            )
        )


def validar_base_classificacao(base):
    """
    Valida as colunas necessárias da base
    de padrões classificados.
    """

    colunas_obrigatorias = {
        "descricao_normalizada",
        "categoria_validada",
        "causa_confirmada",
        "acao_recomendada",
        "criticidade_validada",
        "status_validacao",
    }

    colunas_ausentes = (
        colunas_obrigatorias
        - set(base.columns)
    )

    if colunas_ausentes:
        raise ValueError(
            "Colunas ausentes em "
            "rifaina_classificacao_falhas.csv: "
            + ", ".join(
                sorted(colunas_ausentes)
            )
        )


# ==================================================
# PREPARAÇÃO DA CLASSIFICAÇÃO
# ==================================================

def preparar_classificacoes(base_classificacao):
    """
    Organiza a base de padrões e mantém somente
    uma classificação por descrição normalizada.
    """

    base = base_classificacao.copy()

    colunas_classificacao = [
        "descricao_normalizada",
        "categoria_validada",
        "causa_confirmada",
        "acao_recomendada",
        "criticidade_validada",
        "validado_por",
        "data_validacao",
        "observacao_validacao",
        "status_validacao",
    ]

    if "subcategoria_validada" in base.columns:
        colunas_classificacao.insert(
            2,
            "subcategoria_validada",
        )

    for coluna in colunas_classificacao:
        if coluna not in base.columns:
            base[coluna] = ""

    base = base[
        colunas_classificacao
    ].copy()

    base["descricao_normalizada"] = (
        base["descricao_normalizada"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    base = base[
        base["descricao_normalizada"] != ""
    ].copy()

    base = base.drop_duplicates(
        subset=["descricao_normalizada"],
        keep="last",
    )

    return base


# ==================================================
# RELACIONAMENTO DAS BASES
# ==================================================

def relacionar_falhas_classificacoes(
    base_falhas,
    base_classificacao,
):
    """
    Relaciona cada ocorrência real com o padrão
    classificado correspondente.
    """

    falhas = base_falhas.copy()
    classificacoes = preparar_classificacoes(
        base_classificacao
    )

    falhas["descricao_normalizada"] = (
        falhas["descricao_normalizada"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    base_completa = falhas.merge(
        classificacoes,
        on="descricao_normalizada",
        how="left",
        validate="many_to_one",
    )

    base_completa["classificacao_encontrada"] = (
        base_completa[
            "categoria_validada"
        ].notna()
        & base_completa[
            "categoria_validada"
        ].astype(str).str.strip().ne("")
    )

    base_completa["data_log"] = pd.to_datetime(
        base_completa["data_log"],
        errors="coerce",
    )

    base_completa = (
        base_completa
        .sort_values(
            by=[
                "data_log",
                "chave_registro",
            ],
            ascending=True,
            na_position="last",
        )
        .reset_index(drop=True)
    )

    return base_completa


# ==================================================
# SELEÇÃO PARA TREINAMENTO
# ==================================================

def selecionar_base_treinamento(
    base_completa,
):
    """
    Seleciona apenas registros classificados
    e permitidos para treinamento.

    Entram:
        Validado
        Validado Automaticamente

    Não entram:
        Revisao Humana
        Pendente
        Sem classificação
    """

    status_permitidos = {
        "Validado",
        "Validado Automaticamente",
    }

    mascara_classificada = (
        base_completa[
            "classificacao_encontrada"
        ]
    )

    mascara_status = (
        base_completa[
            "status_validacao"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .isin(status_permitidos)
    )

    mascara_categoria = (
        base_completa[
            "categoria_validada"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    )

    mascara_desconhecido = (
        base_completa[
            "categoria_validada"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("Desconhecido")
    )

    base_treinamento = base_completa[
        mascara_classificada
        & mascara_status
        & mascara_categoria
        & mascara_desconhecido
    ].copy()

    colunas_treinamento = [
        "chave_registro",
        "tabela_origem",
        "id",
        "rpa",
        "processo",
        "status",
        "resultado_evento",
        "descricao_original",
        "descricao_normalizada",
        "nivel_descricao",
        "data_log",
        "semana_origem",
        "categoria_validada",
        "subcategoria_validada",
        "causa_confirmada",
        "acao_recomendada",
        "criticidade_validada",
        "status_validacao",
    ]

    for coluna in colunas_treinamento:
        if coluna not in base_treinamento.columns:
            base_treinamento[coluna] = ""

    base_treinamento = base_treinamento[
        colunas_treinamento
    ]

    return base_treinamento


# ==================================================
# BASE PARA REVISÃO HUMANA
# ==================================================

def selecionar_revisao_humana(
    base_completa,
):
    """
    Separa os registros que ainda não podem
    entrar no treinamento.
    """

    status = (
        base_completa[
            "status_validacao"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    mascara = (
        ~base_completa[
            "classificacao_encontrada"
        ]
        | status.isin(
            [
                "",
                "Pendente",
                "Revisao Humana",
            ]
        )
        | (
            base_completa[
                "categoria_validada"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .isin(
                [
                    "",
                    "Desconhecido",
                ]
            )
        )
    )

    return base_completa[
        mascara
    ].copy()


# ==================================================
# SALVAMENTO
# ==================================================

def salvar_csv_seguro(
    dataframe,
    caminho_arquivo,
):
    """
    Salva o CSV por meio de arquivo temporário.
    """

    diretorio_base.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho_temporario = (
        caminho_arquivo.with_suffix(".tmp")
    )

    dataframe.to_csv(
        caminho_temporario,
        index=False,
        encoding="utf-8-sig",
    )

    caminho_temporario.replace(
        caminho_arquivo
    )


# ==================================================
# RESUMO DA BASE DE TREINAMENTO
# ==================================================

def criar_resumo(
    base_completa,
    base_treinamento,
    base_revisao,
):
    """
    Cria os principais indicadores da base.
    """

    categorias = (
        base_treinamento[
            "categoria_validada"
        ]
        .value_counts()
        .to_dict()
    )

    resumo = {
        "data_processamento": (
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ),
        "total_falhas": len(
            base_completa
        ),
        "falhas_classificadas": int(
            base_completa[
                "classificacao_encontrada"
            ].sum()
        ),
        "falhas_sem_classificacao": int(
            (
                ~base_completa[
                    "classificacao_encontrada"
                ]
            ).sum()
        ),
        "registros_treinamento": len(
            base_treinamento
        ),
        "registros_revisao_humana": len(
            base_revisao
        ),
        "quantidade_categorias": int(
            base_treinamento[
                "categoria_validada"
            ].nunique()
        ),
        "data_inicial": (
            base_treinamento[
                "data_log"
            ].min()
            if not base_treinamento.empty
            else ""
        ),
        "data_final": (
            base_treinamento[
                "data_log"
            ].max()
            if not base_treinamento.empty
            else ""
        ),
        "distribuicao_categorias": str(
            categorias
        ),
    }

    return resumo


# ==================================================
# FUNÇÃO PRINCIPAL
# ==================================================

def preparar_base_treinamento():
    """
    Executa a preparação da base de treinamento.

    Etapas:
        1. Lê as falhas reais;
        2. Lê os padrões classificados;
        3. Relaciona ocorrência e classificação;
        4. Separa registros aptos para treinamento;
        5. Separa registros para revisão humana;
        6. Salva as bases e o resumo.
    """

    print("\n========================================")
    print("PREPARAÇÃO DA BASE DE TREINAMENTO")
    print("========================================")

    base_falhas = ler_csv(
        arquivo_falhas
    )

    base_classificacao = ler_csv(
        arquivo_classificacao
    )

    if base_falhas.empty:
        print(
            "[TREINAMENTO] A base de falhas está vazia."
        )

        return pd.DataFrame()

    if base_classificacao.empty:
        print(
            "[TREINAMENTO] A base de classificação "
            "está vazia."
        )

        return pd.DataFrame()

    validar_base_falhas(
        base_falhas
    )

    validar_base_classificacao(
        base_classificacao
    )

    base_completa = relacionar_falhas_classificacoes(
        base_falhas=base_falhas,
        base_classificacao=base_classificacao,
    )

    base_treinamento = selecionar_base_treinamento(
        base_completa
    )

    base_revisao = selecionar_revisao_humana(
        base_completa
    )

    salvar_csv_seguro(
        dataframe=base_completa,
        caminho_arquivo=arquivo_base_completa,
    )

    salvar_csv_seguro(
        dataframe=base_treinamento,
        caminho_arquivo=arquivo_base_treinamento,
    )

    salvar_csv_seguro(
        dataframe=base_revisao,
        caminho_arquivo=arquivo_revisao_humana,
    )

    resumo = criar_resumo(
        base_completa=base_completa,
        base_treinamento=base_treinamento,
        base_revisao=base_revisao,
    )

    salvar_csv_seguro(
        dataframe=pd.DataFrame(
            [resumo]
        ),
        caminho_arquivo=(
            arquivo_resumo_treinamento
        ),
    )

    print(f"Total de falhas: {resumo['total_falhas']}")
    print(
        "Falhas classificadas: "
        f"{resumo['falhas_classificadas']}"
    )
    print(
        "Falhas sem classificação: "
        f"{resumo['falhas_sem_classificacao']}"
    )
    print(
        "Registros para treinamento: "
        f"{resumo['registros_treinamento']}"
    )
    print(
        "Registros para revisão humana: "
        f"{resumo['registros_revisao_humana']}"
    )
    print(
        "Quantidade de categorias: "
        f"{resumo['quantidade_categorias']}"
    )

    print("\nDistribuição da base de treinamento:")

    if not base_treinamento.empty:
        print(
            base_treinamento[
                "categoria_validada"
            ]
            .value_counts()
            .to_string()
        )

    print("\nArquivos gerados:")
    print(
        f"- Base classificada completa: "
        f"{arquivo_base_completa}"
    )
    print(
        f"- Base para treinamento: "
        f"{arquivo_base_treinamento}"
    )
    print(
        f"- Revisão humana: "
        f"{arquivo_revisao_humana}"
    )
    print(
        f"- Resumo: "
        f"{arquivo_resumo_treinamento}"
    )

    print("\n========================================")
    print("BASE DE TREINAMENTO PREPARADA")
    print("========================================")

    return base_treinamento