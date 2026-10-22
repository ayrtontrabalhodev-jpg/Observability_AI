from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline


# ==================================================
# CAMINHOS
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent.parent
diretorio_base = diretorio_raiz / "base_tratada_rifaina"
diretorio_modelos = diretorio_raiz / "modelos"

arquivo_base_treinamento = (
    diretorio_base / "rifaina_base_treinamento.csv"
)

arquivo_modelo = (
    diretorio_modelos / "classificador_rifaina.joblib"
)

arquivo_previsoes_teste = (
    diretorio_base / "rifaina_previsoes_teste.csv"
)

arquivo_metricas = (
    diretorio_base / "metricas_modelo_rifaina.csv"
)

arquivo_relatorio = (
    diretorio_base / "relatorio_classificacao_rifaina.csv"
)

arquivo_matriz_confusao = (
    diretorio_base / "matriz_confusao_rifaina.csv"
)

arquivo_distribuicao = (
    diretorio_base / "distribuicao_treino_teste.csv"
)


# ==================================================
# CONFIGURAÇÕES
# ==================================================

TAMANHO_TESTE = 0.25
SEMENTE_ALEATORIA = 42
MINIMO_REGISTROS_CATEGORIA = 2


# ==================================================
# LEITURA DA BASE
# ==================================================

def carregar_base_treinamento():
    """
    Carrega a base preparada na etapa anterior.
    """

    if not arquivo_base_treinamento.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {arquivo_base_treinamento}"
        )

    base = pd.read_csv(
        arquivo_base_treinamento,
        encoding="utf-8-sig",
        low_memory=False,
    )

    if base.empty:
        print("[MODELO] A base de treinamento está vazia.")
        return pd.DataFrame()

    colunas_obrigatorias = {
        "descricao_normalizada",
        "categoria_validada",
        "chave_registro",
        "data_log",
    }

    colunas_ausentes = colunas_obrigatorias - set(base.columns)

    if colunas_ausentes:
        raise ValueError(
            "Colunas ausentes na base de treinamento: "
            + ", ".join(sorted(colunas_ausentes))
        )

    return base


# ==================================================
# LIMPEZA DA BASE
# ==================================================

def preparar_base_modelo(base):
    """
    Limpa e valida os registros que serão usados
    no treinamento.
    """

    dados = base.copy()

    dados["descricao_normalizada"] = (
        dados["descricao_normalizada"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    dados["categoria_validada"] = (
        dados["categoria_validada"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    dados = dados[
        (dados["descricao_normalizada"] != "")
        & (dados["categoria_validada"] != "")
        & (dados["categoria_validada"] != "Desconhecido")
    ].copy()

    dados = dados.drop_duplicates(
        subset=[
            "chave_registro",
            "descricao_normalizada",
            "categoria_validada",
        ],
        keep="last",
    )

    dados["data_log"] = pd.to_datetime(
        dados["data_log"],
        errors="coerce",
    )

    contagem_categorias = (
        dados["categoria_validada"]
        .value_counts()
    )

    categorias_validas = contagem_categorias[
        contagem_categorias >= MINIMO_REGISTROS_CATEGORIA
    ].index

    dados = dados[
        dados["categoria_validada"].isin(
            categorias_validas
        )
    ].copy()

    dados = dados.reset_index(drop=True)

    if dados["categoria_validada"].nunique() < 2:
        raise ValueError(
            "O modelo precisa de pelo menos duas categorias."
        )

    return dados


# ==================================================
# DIVISÃO POR PADRÕES
# ==================================================

def dividir_treino_teste(base):
    """
    Separa treino e teste utilizando a descrição
    normalizada como grupo.

    O mesmo padrão nunca ficará simultaneamente
    no treino e no teste.
    """

    grupos = base["descricao_normalizada"]

    separador = GroupShuffleSplit(
        n_splits=30,
        test_size=TAMANHO_TESTE,
        random_state=SEMENTE_ALEATORIA,
    )

    categorias_totais = set(
        base["categoria_validada"].unique()
    )

    melhor_divisao = None
    melhor_quantidade_categorias = -1

    for indices_treino, indices_teste in separador.split(
        base,
        base["categoria_validada"],
        groups=grupos,
    ):
        treino = base.iloc[indices_treino].copy()
        teste = base.iloc[indices_teste].copy()

        categorias_treino = set(
            treino["categoria_validada"].unique()
        )

        categorias_teste = set(
            teste["categoria_validada"].unique()
        )

        categorias_teste_conhecidas = (
            categorias_teste & categorias_treino
        )

        quantidade_categorias = len(
            categorias_teste_conhecidas
        )

        if quantidade_categorias > melhor_quantidade_categorias:
            melhor_quantidade_categorias = quantidade_categorias
            melhor_divisao = (
                indices_treino,
                indices_teste,
            )

        if categorias_treino == categorias_totais:
            melhor_divisao = (
                indices_treino,
                indices_teste,
            )
            break

    if melhor_divisao is None:
        raise ValueError(
            "Não foi possível criar a divisão de treino e teste."
        )

    indices_treino, indices_teste = melhor_divisao

    treino = base.iloc[indices_treino].copy()
    teste = base.iloc[indices_teste].copy()

    # O modelo não consegue avaliar no teste uma
    # categoria inexistente no conjunto de treino.
    categorias_treino = set(
        treino["categoria_validada"].unique()
    )

    teste["categoria_disponivel_no_treino"] = (
        teste["categoria_validada"].isin(
            categorias_treino
        )
    )

    teste_avaliavel = teste[
        teste["categoria_disponivel_no_treino"]
    ].copy()

    teste_nao_avaliavel = teste[
        ~teste["categoria_disponivel_no_treino"]
    ].copy()

    return (
        treino,
        teste_avaliavel,
        teste_nao_avaliavel,
    )


# ==================================================
# CRIAÇÃO DO MODELO
# ==================================================

def criar_pipeline_modelo():
    """
    Cria o pipeline de vetorização e classificação.

    TF-IDF:
        transforma texto em atributos numéricos.

    Regressão logística:
        classifica a categoria da descrição.
    """

    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    min_df=1,
                    max_df=1.0,
                    sublinear_tf=True,
                    max_features=10000,
                ),
            ),
            (
                "classificador",
                LogisticRegression(
                    max_iter=3000,
                    class_weight="balanced",
                    random_state=SEMENTE_ALEATORIA,
                ),
            ),
        ]
    )


# ==================================================
# AVALIAÇÃO
# ==================================================

def avaliar_modelo(modelo, base_teste):
    """
    Avalia o modelo e gera previsões detalhadas.
    """

    if base_teste.empty:
        raise ValueError(
            "O conjunto de teste avaliável ficou vazio."
        )

    x_teste = base_teste[
        "descricao_normalizada"
    ]

    y_real = base_teste[
        "categoria_validada"
    ]

    y_previsto = modelo.predict(
        x_teste
    )

    probabilidades = modelo.predict_proba(
        x_teste
    )

    confiancas = probabilidades.max(
        axis=1
    )

    previsoes = base_teste.copy()

    previsoes["categoria_real"] = (
        y_real.values
    )

    previsoes["categoria_prevista"] = (
        y_previsto
    )

    previsoes["confianca_modelo"] = (
        confiancas
    )

    previsoes["acertou"] = (
        previsoes["categoria_real"]
        == previsoes["categoria_prevista"]
    )

    metricas = {
        "data_treinamento": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "registros_teste": len(
            base_teste
        ),
        "acuracia": accuracy_score(
            y_real,
            y_previsto,
        ),
        "precisao_macro": precision_score(
            y_real,
            y_previsto,
            average="macro",
            zero_division=0,
        ),
        "recall_macro": recall_score(
            y_real,
            y_previsto,
            average="macro",
            zero_division=0,
        ),
        "f1_macro": f1_score(
            y_real,
            y_previsto,
            average="macro",
            zero_division=0,
        ),
        "precisao_weighted": precision_score(
            y_real,
            y_previsto,
            average="weighted",
            zero_division=0,
        ),
        "recall_weighted": recall_score(
            y_real,
            y_previsto,
            average="weighted",
            zero_division=0,
        ),
        "f1_weighted": f1_score(
            y_real,
            y_previsto,
            average="weighted",
            zero_division=0,
        ),
        "confianca_media": float(
            confiancas.mean()
        ),
    }

    relatorio = classification_report(
        y_real,
        y_previsto,
        output_dict=True,
        zero_division=0,
    )

    dataframe_relatorio = (
        pd.DataFrame(relatorio)
        .transpose()
        .reset_index()
        .rename(
            columns={
                "index": "categoria",
            }
        )
    )

    categorias_matriz = sorted(
        set(y_real)
        | set(y_previsto)
    )

    matriz = confusion_matrix(
        y_real,
        y_previsto,
        labels=categorias_matriz,
    )

    dataframe_matriz = pd.DataFrame(
        matriz,
        index=categorias_matriz,
        columns=categorias_matriz,
    )

    dataframe_matriz.index.name = (
        "categoria_real"
    )

    dataframe_matriz = (
        dataframe_matriz
        .reset_index()
    )

    return (
        metricas,
        previsoes,
        dataframe_relatorio,
        dataframe_matriz,
    )


# ==================================================
# DISTRIBUIÇÃO TREINO E TESTE
# ==================================================

def criar_distribuicao(
    base_treino,
    base_teste,
):
    """
    Mostra quantos registros de cada categoria
    ficaram em treino e teste.
    """

    distribuicao_treino = (
        base_treino[
            "categoria_validada"
        ]
        .value_counts()
        .rename("treino")
    )

    distribuicao_teste = (
        base_teste[
            "categoria_validada"
        ]
        .value_counts()
        .rename("teste")
    )

    distribuicao = pd.concat(
        [
            distribuicao_treino,
            distribuicao_teste,
        ],
        axis=1,
    ).fillna(0)

    distribuicao = distribuicao.astype(int)
    distribuicao = distribuicao.reset_index()
    distribuicao = distribuicao.rename(
        columns={
            "categoria_validada": "categoria",
            "index": "categoria",
        }
    )

    return distribuicao


# ==================================================
# SALVAMENTO
# ==================================================

def salvar_csv_seguro(
    dataframe,
    caminho_arquivo,
):
    """
    Salva o CSV usando arquivo temporário.
    """

    caminho_arquivo.parent.mkdir(
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


def salvar_modelo(
    modelo,
    metadados,
):
    """
    Salva modelo e metadados no mesmo arquivo.
    """

    diretorio_modelos.mkdir(
        parents=True,
        exist_ok=True,
    )

    pacote_modelo = {
        "modelo": modelo,
        "metadados": metadados,
    }

    joblib.dump(
        pacote_modelo,
        arquivo_modelo,
    )


# ==================================================
# FUNÇÃO PRINCIPAL
# ==================================================

def treinar_modelo_rifaina():
    """
    Executa o treinamento e a avaliação do
    primeiro classificador RIFAINA.
    """

    print("\n========================================")
    print("TREINAMENTO DO MODELO RIFAINA")
    print("========================================")

    base_original = carregar_base_treinamento()

    if base_original.empty:
        return None

    base_modelo = preparar_base_modelo(
        base_original
    )

    print(
        f"Registros disponíveis: "
        f"{len(base_modelo)}"
    )

    print(
        f"Padrões únicos: "
        f"{base_modelo['descricao_normalizada'].nunique()}"
    )

    print(
        f"Categorias: "
        f"{base_modelo['categoria_validada'].nunique()}"
    )

    (
        base_treino,
        base_teste,
        base_teste_nao_avaliavel,
    ) = dividir_treino_teste(
        base_modelo
    )

    print(
        f"Registros de treino: "
        f"{len(base_treino)}"
    )

    print(
        f"Registros de teste avaliáveis: "
        f"{len(base_teste)}"
    )

    print(
        f"Registros de teste não avaliáveis: "
        f"{len(base_teste_nao_avaliavel)}"
    )

    modelo_avaliacao = criar_pipeline_modelo()

    modelo_avaliacao.fit(
        base_treino["descricao_normalizada"],
        base_treino["categoria_validada"],
    )

    (
        metricas,
        previsoes,
        relatorio,
        matriz,
    ) = avaliar_modelo(
        modelo=modelo_avaliacao,
        base_teste=base_teste,
    )

    distribuicao = criar_distribuicao(
        base_treino=base_treino,
        base_teste=base_teste,
    )

    metricas.update(
        {
            "registros_totais": len(
                base_modelo
            ),
            "registros_treino": len(
                base_treino
            ),
            "registros_teste_nao_avaliaveis": len(
                base_teste_nao_avaliavel
            ),
            "padroes_totais": int(
                base_modelo[
                    "descricao_normalizada"
                ].nunique()
            ),
            "padroes_treino": int(
                base_treino[
                    "descricao_normalizada"
                ].nunique()
            ),
            "padroes_teste": int(
                base_teste[
                    "descricao_normalizada"
                ].nunique()
            ),
            "quantidade_categorias": int(
                base_modelo[
                    "categoria_validada"
                ].nunique()
            ),
        }
    )

    salvar_csv_seguro(
        dataframe=pd.DataFrame(
            [metricas]
        ),
        caminho_arquivo=arquivo_metricas,
    )

    salvar_csv_seguro(
        dataframe=previsoes,
        caminho_arquivo=(
            arquivo_previsoes_teste
        ),
    )

    salvar_csv_seguro(
        dataframe=relatorio,
        caminho_arquivo=arquivo_relatorio,
    )

    salvar_csv_seguro(
        dataframe=matriz,
        caminho_arquivo=(
            arquivo_matriz_confusao
        ),
    )

    salvar_csv_seguro(
        dataframe=distribuicao,
        caminho_arquivo=(
            arquivo_distribuicao
        ),
    )

    # Após avaliar, treina o modelo final com
    # todos os registros disponíveis.
    modelo_final = criar_pipeline_modelo()

    modelo_final.fit(
        base_modelo["descricao_normalizada"],
        base_modelo["categoria_validada"],
    )

    metadados = {
        "data_treinamento": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "quantidade_registros": len(
            base_modelo
        ),
        "quantidade_padroes": int(
            base_modelo[
                "descricao_normalizada"
            ].nunique()
        ),
        "categorias": sorted(
            base_modelo[
                "categoria_validada"
            ].unique().tolist()
        ),
        "acuracia_teste": metricas[
            "acuracia"
        ],
        "f1_macro_teste": metricas[
            "f1_macro"
        ],
        "versao_modelo": "1.0.0",
    }

    salvar_modelo(
        modelo=modelo_final,
        metadados=metadados,
    )

    print("\n========================================")
    print("RESULTADO DO MODELO")
    print("========================================")

    print(
        f"Acurácia: "
        f"{metricas['acuracia']:.2%}"
    )

    print(
        f"Precisão macro: "
        f"{metricas['precisao_macro']:.2%}"
    )

    print(
        f"Recall macro: "
        f"{metricas['recall_macro']:.2%}"
    )

    print(
        f"F1 macro: "
        f"{metricas['f1_macro']:.2%}"
    )

    print(
        f"F1 ponderado: "
        f"{metricas['f1_weighted']:.2%}"
    )

    print(
        f"Confiança média: "
        f"{metricas['confianca_media']:.2%}"
    )

    print("\nArquivos gerados:")
    print(f"- Modelo: {arquivo_modelo}")
    print(f"- Métricas: {arquivo_metricas}")
    print(f"- Previsões: {arquivo_previsoes_teste}")
    print(f"- Relatório: {arquivo_relatorio}")
    print(f"- Matriz: {arquivo_matriz_confusao}")
    print(f"- Distribuição: {arquivo_distribuicao}")

    print("\n========================================")
    print("TREINAMENTO FINALIZADO")
    print("========================================")

    return {
        "modelo": modelo_final,
        "metricas": metricas,
    }