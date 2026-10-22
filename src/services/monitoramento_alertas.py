import json
from pathlib import Path

import pandas as pd

from config.config import pasta_historico
from src.services.alerta_email import enviar_alerta_email
from src.services.classificacao_falhas import classificar_falha_completa
from src.services.tratamento_dados import normalizar_descricao


# ==================================================
# CAMINHOS
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent.parent
diretorio_historico = diretorio_raiz / "logs" / pasta_historico
diretorio_base = diretorio_raiz / "base_tratada_rifaina"

arquivo_classificacao = (
    diretorio_base
    / "rifaina_classificacao_falhas.csv"
)

arquivo_controle_alertas = (
    diretorio_historico
    / "controle_alertas.json"
)


# ==================================================
# CONFIGURAÇÕES
# ==================================================

NOME_TABELA = "tbl_rpa_log_rifaina"
NOME_ARQUIVO_TABELA = f"{NOME_TABELA}.csv"

# Limite de segurança para evitar uma quantidade
# inesperada de e-mails na mesma execução.
LIMITE_ALERTAS_POR_EXECUCAO = 10

RESULTADOS_PROCESSADOS = {
    "Enviado",
    "Histórico ignorado",
}


# ==================================================
# FUNÇÕES AUXILIARES
# ==================================================

def valor_texto(valor, padrao=""):
    """
    Converte um valor em texto de forma segura.

    Evita retornar:
        nan
        None
        <NA>
    """

    if valor is None:
        return padrao

    try:
        if pd.isna(valor):
            return padrao
    except (TypeError, ValueError):
        pass

    texto = str(valor).strip()

    if texto.lower() in {
        "",
        "nan",
        "none",
        "<na>",
    }:
        return padrao

    return texto


def valor_float(valor, padrao=0.0):
    """
    Converte um valor em número decimal.
    """

    try:
        if pd.isna(valor):
            return padrao

        return float(valor)

    except (TypeError, ValueError):
        return padrao


def obter_valor_linha(linha, coluna, padrao=""):
    """
    Obtém uma informação de uma linha do pandas.
    """

    if coluna not in linha.index:
        return padrao

    return valor_texto(
        linha.get(coluna),
        padrao,
    )


def formatar_id(valor):
    """
    Padroniza o ID para evitar diferenças como:

        42157
        42157.0
        '42157'
    """

    try:
        return str(int(float(valor)))

    except (TypeError, ValueError):
        return valor_texto(valor, "")


def gerar_chave_alerta(registro):
    """
    Gera uma chave estável para impedir o envio
    duplicado do mesmo registro.

    Exemplo:
        tbl_rpa_log_rifaina_42157
    """

    tabela = valor_texto(
        registro.get("tabela_origem"),
        NOME_TABELA,
    )

    id_formatado = formatar_id(
        registro.get("id")
    )

    if not id_formatado:
        return ""

    return f"{tabela}_{id_formatado}"


def formatar_data_log(valor):
    """
    Formata a data do log para exibição no e-mail.
    """

    if valor is None:
        return ""

    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass

    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%d/%m/%Y %H:%M:%S")

    data_convertida = pd.to_datetime(
        valor,
        errors="coerce",
    )

    if pd.isna(data_convertida):
        return str(valor)

    return data_convertida.strftime(
        "%d/%m/%Y %H:%M:%S"
    )


# ==================================================
# CONTROLE DOS ALERTAS
# ==================================================

def carregar_controle_alertas():
    """
    Carrega o controle dos alertas já processados.

    Se o arquivo existir, mas estiver inválido,
    interrompe o processo por segurança. Isso evita
    o reenvio de todos os alertas históricos.
    """

    if not arquivo_controle_alertas.exists():
        return {}

    try:
        with open(
            arquivo_controle_alertas,
            mode="r",
            encoding="utf-8",
        ) as arquivo:
            controle = json.load(arquivo)

    except json.JSONDecodeError as erro:
        raise RuntimeError(
            "O arquivo controle_alertas.json está inválido. "
            "Corrija ou restaure o arquivo antes de continuar. "
            f"Detalhes: {erro}"
        ) from erro

    except OSError as erro:
        raise OSError(
            "Não foi possível ler o controle de alertas: "
            f"{erro}"
        ) from erro

    if not isinstance(controle, dict):
        raise ValueError(
            "O controle de alertas não possui "
            "um formato válido."
        )

    return controle


def salvar_controle_alertas(controle):
    """
    Salva o controle de alertas utilizando
    um arquivo temporário.
    """

    arquivo_controle_alertas.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    arquivo_temporario = (
        arquivo_controle_alertas
        .with_suffix(".tmp")
    )

    try:
        with open(
            arquivo_temporario,
            mode="w",
            encoding="utf-8",
        ) as arquivo:
            json.dump(
                controle,
                arquivo,
                indent=4,
                ensure_ascii=False,
            )

        arquivo_temporario.replace(
            arquivo_controle_alertas
        )

    except OSError as erro:
        if arquivo_temporario.exists():
            arquivo_temporario.unlink()

        raise OSError(
            "Não foi possível salvar o controle "
            f"de alertas: {erro}"
        ) from erro


def obter_resultado_anterior(
    controle,
    chave_registro,
):
    """
    Retorna o resultado anterior do alerta.
    """

    return (
        controle
        .get(
            chave_registro,
            {},
        )
        .get(
            "resultado",
            "",
        )
    )


def alerta_ja_processado(
    controle,
    chave_registro,
):
    """
    Verifica se o registro já foi enviado ou
    marcado como histórico ignorado.
    """

    resultado = obter_resultado_anterior(
        controle=controle,
        chave_registro=chave_registro,
    )

    return resultado in RESULTADOS_PROCESSADOS


# ==================================================
# BASE DE CLASSIFICAÇÕES
# ==================================================

def carregar_classificacoes():
    """
    Carrega os padrões classificados do RIFAINA.
    """

    if not arquivo_classificacao.exists():
        print(
            "[ALERTA] Base de classificação "
            "não encontrada:"
        )

        print(
            f"[ALERTA] {arquivo_classificacao}"
        )

        return pd.DataFrame()

    try:
        base = pd.read_csv(
            arquivo_classificacao,
            encoding="utf-8-sig",
            low_memory=False,
        )

    except pd.errors.EmptyDataError:
        print(
            "[ALERTA] A base de classificação "
            "está vazia."
        )

        return pd.DataFrame()

    except Exception as erro:
        print(
            "[ALERTA] Não foi possível ler a base "
            "de classificação: "
            f"{type(erro).__name__}: {erro}"
        )

        return pd.DataFrame()

    if base.empty:
        return base

    if "descricao_normalizada" not in base.columns:
        print(
            "[ALERTA] A base de classificação não possui "
            "a coluna descricao_normalizada."
        )

        return pd.DataFrame()

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


def localizar_classificacao_conhecida(
    descricao_normalizada,
    base_classificacao,
):
    """
    Busca uma descrição já conhecida na base
    de classificações.

    Retorna uma linha do pandas ou None.
    """

    if base_classificacao.empty:
        return None

    correspondencias = base_classificacao[
        base_classificacao[
            "descricao_normalizada"
        ].eq(descricao_normalizada)
    ]

    if correspondencias.empty:
        return None

    return correspondencias.iloc[0]


# ==================================================
# LEITURA DOS LOGS SEMANAIS
# ==================================================

def localizar_arquivos_semanais():
    """
    Localiza todos os CSVs semanais do RIFAINA.
    """

    if not diretorio_historico.exists():
        print(
            "[ALERTA] Pasta de histórico "
            "não encontrada:"
        )

        print(
            f"[ALERTA] {diretorio_historico}"
        )

        return []

    return sorted(
        diretorio_historico.glob(
            f"semana_*/{NOME_ARQUIVO_TABELA}"
        )
    )


def preparar_chave_registro(dataframe):
    """
    Garante que todos os registros possuam
    uma chave única e padronizada.
    """

    base = dataframe.copy()

    if "tabela_origem" not in base.columns:
        base["tabela_origem"] = NOME_TABELA

    novas_chaves = base.apply(
        gerar_chave_alerta,
        axis=1,
    )

    if "chave_registro" not in base.columns:
        base["chave_registro"] = novas_chaves
        return base

    mascara_sem_chave = (
        base["chave_registro"].isna()
        | base["chave_registro"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(
            [
                "",
                "nan",
                "none",
                "<na>",
            ]
        )
    )

    base.loc[
        mascara_sem_chave,
        "chave_registro",
    ] = novas_chaves.loc[
        mascara_sem_chave
    ]

    # Padroniza todas as chaves pela tabela e ID.
    # Isso evita chave com ID igual a 42157.0.
    mascara_com_id = base["id"].notna()

    base.loc[
        mascara_com_id,
        "chave_registro",
    ] = novas_chaves.loc[
        mascara_com_id
    ]

    return base


def carregar_erros_semanais():
    """
    Lê os arquivos semanais e retorna apenas
    os registros cujo status oficial é Erro.
    """

    arquivos = localizar_arquivos_semanais()

    if not arquivos:
        print(
            "[ALERTA] Nenhum arquivo semanal "
            "do RIFAINA foi encontrado."
        )

        return pd.DataFrame()

    bases = []

    for arquivo in arquivos:
        try:
            base = pd.read_csv(
                arquivo,
                encoding="utf-8-sig",
                low_memory=False,
            )

            if base.empty:
                continue

            colunas_obrigatorias = {
                "id",
                "rpa",
                "processo",
                "status",
                "descricao",
                "data_log",
            }

            colunas_ausentes = (
                colunas_obrigatorias
                - set(base.columns)
            )

            if colunas_ausentes:
                print(
                    f"[ALERTA] {arquivo.name} não possui: "
                    + ", ".join(
                        sorted(colunas_ausentes)
                    )
                )

                continue

            erros = base[
                base["status"]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.lower()
                .eq("erro")
            ].copy()

            if erros.empty:
                continue

            erros["semana_origem"] = (
                arquivo.parent.name
            )

            erros["arquivo_origem"] = (
                arquivo.name
            )

            bases.append(erros)

        except pd.errors.EmptyDataError:
            print(
                f"[ALERTA] Arquivo vazio: {arquivo}"
            )

        except Exception as erro:
            print(
                f"[ALERTA] Erro ao ler {arquivo}: "
                f"{type(erro).__name__}: {erro}"
            )

    if not bases:
        return pd.DataFrame()

    base_erros = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    base_erros = preparar_chave_registro(
        base_erros
    )

    base_erros = base_erros[
        base_erros["chave_registro"]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    ].copy()

    base_erros = base_erros.drop_duplicates(
        subset=["chave_registro"],
        keep="last",
    )

    base_erros["data_log"] = pd.to_datetime(
        base_erros["data_log"],
        errors="coerce",
    )

    base_erros = (
        base_erros
        .sort_values(
            by=[
                "data_log",
                "id",
            ],
            ascending=True,
            na_position="last",
        )
        .reset_index(drop=True)
    )

    return base_erros


# ==================================================
# CLASSIFICAÇÃO DOS ERROS
# ==================================================

def criar_resultado_padrao_conhecido(
    classificacao,
):
    """
    Cria o resultado para uma descrição já
    conhecida na base de conhecimento.
    """

    confianca = valor_float(
        classificacao.get(
            "confianca_regra",
            1.0,
        ),
        1.0,
    )

    categoria = obter_valor_linha(
        classificacao,
        "categoria_validada",
        "",
    )

    if not categoria:
        categoria = obter_valor_linha(
            classificacao,
            "categoria_sugerida",
            "Desconhecido",
        )

    subcategoria = obter_valor_linha(
        classificacao,
        "subcategoria_validada",
        "",
    )

    if not subcategoria:
        subcategoria = obter_valor_linha(
            classificacao,
            "subcategoria_sugerida",
            "",
        )

    causa = obter_valor_linha(
        classificacao,
        "causa_confirmada",
        "Causa ainda não registrada.",
    )

    acao = obter_valor_linha(
        classificacao,
        "acao_recomendada",
        "Necessária análise técnica.",
    )

    criticidade = obter_valor_linha(
        classificacao,
        "criticidade_validada",
        "",
    )

    if not criticidade:
        criticidade = obter_valor_linha(
            classificacao,
            "criticidade_sugerida",
            "Revisar",
        )

    status_validacao = obter_valor_linha(
        classificacao,
        "status_validacao",
        "Padrão conhecido",
    )

    return {
        "categoria": categoria,
        "subcategoria": subcategoria,
        "causa": causa,
        "acao": acao,
        "criticidade": criticidade,
        "confianca": (
            f"Padrão conhecido ({confianca:.0%})"
        ),
        "confianca_numerica": confianca,
        "decisao": status_validacao,
        "origem_classificacao": (
            "Base de conhecimento"
        ),
    }


def criar_resultado_regra(
    descricao_original,
    descricao_normalizada,
):
    """
    Classifica um erro novo utilizando as regras
    atuais do projeto.
    """

    resultado = classificar_falha_completa(
        descricao_original=descricao_original,
        descricao_normalizada=descricao_normalizada,
    )

    confianca = valor_float(
        resultado.get(
            "confianca",
            0.0,
        ),
        0.0,
    )

    return {
        "categoria": resultado.get(
            "categoria",
            "Desconhecido",
        ),
        "subcategoria": resultado.get(
            "subcategoria",
            "",
        ),
        "causa": resultado.get(
            "causa",
            "Causa não identificada.",
        ),
        "acao": resultado.get(
            "acao",
            "Necessária análise técnica.",
        ),
        "criticidade": resultado.get(
            "criticidade",
            "Revisar",
        ),
        "confianca": (
            f"Regra automática ({confianca:.0%})"
        ),
        "confianca_numerica": confianca,
        "decisao": resultado.get(
            "status_validacao",
            "Revisao Humana",
        ),
        "origem_classificacao": (
            "Motor de regras"
        ),
    }


def classificar_registro_erro(
    registro,
    base_classificacao,
):
    """
    Classifica um registro de erro.

    Prioridade:
        1. Padrão exato já conhecido;
        2. Motor de regras para mensagem nova.
    """

    descricao_original = valor_texto(
        registro.get("descricao"),
        "",
    )

    descricao_normalizada = normalizar_descricao(
        descricao_original
    )

    classificacao_conhecida = (
        localizar_classificacao_conhecida(
            descricao_normalizada=(
                descricao_normalizada
            ),
            base_classificacao=(
                base_classificacao
            ),
        )
    )

    if classificacao_conhecida is not None:
        resultado = criar_resultado_padrao_conhecido(
            classificacao_conhecida
        )

    else:
        resultado = criar_resultado_regra(
            descricao_original=(
                descricao_original
            ),
            descricao_normalizada=(
                descricao_normalizada
            ),
        )

    resultado["descricao_normalizada"] = (
        descricao_normalizada
    )

    return resultado


# ==================================================
# MONTAGEM DO ALERTA
# ==================================================

def montar_alerta(
    registro,
    classificacao,
):
    """
    Junta o registro original e o resultado
    da classificação.
    """

    chave_registro = gerar_chave_alerta(
        registro
    )

    return {
        "chave_registro": chave_registro,
        "id_log": formatar_id(
            registro.get("id")
        ),
        "rpa": valor_texto(
            registro.get("rpa"),
            "RIFAINA",
        ),
        "processo": valor_texto(
            registro.get("processo"),
            "",
        ),
        "status": valor_texto(
            registro.get("status"),
            "Erro",
        ),
        "data_log": formatar_data_log(
            registro.get("data_log")
        ),
        "descricao_original": valor_texto(
            registro.get("descricao"),
            "",
        ),
        "categoria": classificacao[
            "categoria"
        ],
        "subcategoria": classificacao[
            "subcategoria"
        ],
        "causa": classificacao["causa"],
        "acao": classificacao["acao"],
        "criticidade": classificacao[
            "criticidade"
        ],
        "confianca": classificacao[
            "confianca"
        ],
        "confianca_numerica": classificacao[
            "confianca_numerica"
        ],
        "decisao": classificacao[
            "decisao"
        ],
        "origem_classificacao": classificacao[
            "origem_classificacao"
        ],
        "descricao_normalizada": classificacao[
            "descricao_normalizada"
        ],
    }


# ==================================================
# REGISTRO DO RESULTADO
# ==================================================

def registrar_resultado_alerta(
    controle,
    alerta,
    resultado_envio,
):
    """
    Registra o resultado do envio no controle.
    """

    chave_registro = alerta[
        "chave_registro"
    ]

    controle[chave_registro] = {
        "id_log": alerta["id_log"],
        "rpa": alerta["rpa"],
        "data_erro": alerta["data_log"],
        "categoria": alerta["categoria"],
        "subcategoria": alerta[
            "subcategoria"
        ],
        "criticidade": alerta[
            "criticidade"
        ],
        "confianca": alerta[
            "confianca"
        ],
        "decisao": alerta["decisao"],
        "origem_classificacao": alerta[
            "origem_classificacao"
        ],
        "destinatario": resultado_envio.get(
            "destinatario"
        ),
        "assunto": resultado_envio.get(
            "assunto"
        ),
        "data_envio": resultado_envio.get(
            "data_envio"
        ),
        "resultado": (
            "Enviado"
            if resultado_envio.get("enviado")
            else "Erro no envio"
        ),
        "erro_envio": resultado_envio.get(
            "erro"
        ),
    }

    salvar_controle_alertas(
        controle
    )


# ==================================================
# INICIALIZAÇÃO DO HISTÓRICO
# ==================================================

def inicializar_controle_sem_enviar_historico():
    """
    Marca os erros históricos como ignorados.

    Execute esta função uma única vez antes de
    ativar o monitoramento automático.

    Nenhum e-mail é enviado por esta função.
    """

    print("\n========================================")
    print("INICIALIZAÇÃO DOS ALERTAS")
    print("========================================")

    controle = carregar_controle_alertas()
    base_erros = carregar_erros_semanais()

    if base_erros.empty:
        print(
            "[ALERTA] Nenhum erro histórico "
            "encontrado."
        )

        return 0

    quantidade = 0

    for _, registro in base_erros.iterrows():
        chave = gerar_chave_alerta(
            registro
        )

        if not chave:
            continue

        if chave in controle:
            continue

        controle[chave] = {
            "id_log": formatar_id(
                registro.get("id")
            ),
            "rpa": valor_texto(
                registro.get("rpa"),
                "RIFAINA",
            ),
            "data_erro": formatar_data_log(
                registro.get("data_log")
            ),
            "categoria": "",
            "subcategoria": "",
            "criticidade": "",
            "confianca": "",
            "decisao": "",
            "origem_classificacao": "",
            "destinatario": "",
            "assunto": "",
            "data_envio": None,
            "resultado": "Histórico ignorado",
            "erro_envio": None,
        }

        quantidade += 1

    salvar_controle_alertas(
        controle
    )

    print(
        f"[ALERTA] {quantidade} erro(s) histórico(s) "
        "marcado(s) sem envio."
    )

    print(
        f"[ALERTA] Controle: "
        f"{arquivo_controle_alertas}"
    )

    print("========================================")

    return quantidade


# ==================================================
# MONITORAMENTO E ENVIO
# ==================================================

def monitorar_e_enviar_alertas():
    """
    Localiza erros ainda não alertados,
    classifica cada erro e envia e-mail.

    Um registro é ignorado quando estiver marcado:

        Enviado
        Histórico ignorado

    Registros com erro no envio serão tentados
    novamente na próxima execução.
    """

    print("\n========================================")
    print("MONITORAMENTO DE ALERTAS")
    print("========================================")

    controle = carregar_controle_alertas()
    base_erros = carregar_erros_semanais()
    base_classificacao = carregar_classificacoes()

    if base_erros.empty:
        print("[ALERTA] Nenhum erro encontrado.")

        return {
            "erros_encontrados": 0,
            "ja_processados": 0,
            "processados_execucao": 0,
            "alertas_enviados": 0,
            "alertas_com_erro": 0,
            "limite_atingido": False,
        }

    total_processados = 0
    total_enviados = 0
    total_erros_envio = 0
    total_ignorados = 0
    limite_atingido = False

    for _, registro in base_erros.iterrows():
        chave_registro = gerar_chave_alerta(
            registro
        )

        if not chave_registro:
            print(
                "[ALERTA] Registro ignorado porque "
                "não possui tabela ou ID válido."
            )

            continue

        if alerta_ja_processado(
            controle=controle,
            chave_registro=chave_registro,
        ):
            total_ignorados += 1
            continue

        if (
            total_processados
            >= LIMITE_ALERTAS_POR_EXECUCAO
        ):
            limite_atingido = True

            print(
                "[ALERTA] Limite de segurança de "
                f"{LIMITE_ALERTAS_POR_EXECUCAO} alerta(s) "
                "por execução atingido."
            )

            break

        classificacao = classificar_registro_erro(
            registro=registro,
            base_classificacao=(
                base_classificacao
            ),
        )

        alerta = montar_alerta(
            registro=registro,
            classificacao=classificacao,
        )

        print(
            f"[ALERTA] Processando log "
            f"{alerta['id_log']} | "
            f"{alerta['categoria']} | "
            f"{alerta['criticidade']}"
        )

        resultado_envio = enviar_alerta_email(
            alerta
        )

        registrar_resultado_alerta(
            controle=controle,
            alerta=alerta,
            resultado_envio=resultado_envio,
        )

        total_processados += 1

        if resultado_envio.get("enviado"):
            total_enviados += 1
        else:
            total_erros_envio += 1

    print("\n========================================")
    print("RESUMO DOS ALERTAS")
    print("========================================")
    print(f"Erros encontrados: {len(base_erros)}")
    print(f"Já processados: {total_ignorados}")
    print(f"Processados nesta execução: {total_processados}")
    print(f"Alertas enviados: {total_enviados}")
    print(f"Erros de envio: {total_erros_envio}")
    print(f"Limite de segurança atingido: {limite_atingido}")
    print("========================================")

    return {
        "erros_encontrados": len(base_erros),
        "ja_processados": total_ignorados,
        "processados_execucao": total_processados,
        "alertas_enviados": total_enviados,
        "alertas_com_erro": total_erros_envio,
        "limite_atingido": limite_atingido,
    }