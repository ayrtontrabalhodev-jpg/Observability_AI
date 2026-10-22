import hashlib
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.config import pasta_historico, tabelas_logs


# ==================================================
# CAMINHOS
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent.parent
diretorio_historico = diretorio_raiz / "logs" / pasta_historico
diretorio_saida = diretorio_raiz / "base_tratada_rifaina"

arquivo_consolidado = diretorio_saida / "rifaina_consolidado.csv"
arquivo_falhas = diretorio_saida / "rifaina_falhas.csv"
arquivo_padroes = diretorio_saida / "rifaina_padroes_falha.csv"
arquivo_resumo = diretorio_saida / "resumo_tratamento.csv"

TABELA_RIFAINA = "tbl_rpa_log_rifaina"


# ==================================================
# LOCALIZAÇÃO DOS ARQUIVOS
# ==================================================

def localizar_arquivos_rifaina():
    """
    Localiza todos os CSVs semanais do RIFAINA.
    """

    if not diretorio_historico.exists():
        print(f"[TRATAMENTO] Pasta não encontrada: {diretorio_historico}")
        return []

    arquivos = sorted(
        diretorio_historico.glob(
            f"semana_*/{TABELA_RIFAINA}.csv"
        )
    )

    print(f"[TRATAMENTO] Arquivos RIFAINA encontrados: {len(arquivos)}")

    return arquivos


# ==================================================
# LEITURA DOS ARQUIVOS
# ==================================================

def ler_csv(caminho_arquivo):
    """
    Lê um arquivo CSV tentando codificações comuns.
    """

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
            print(f"[TRATAMENTO] Arquivo vazio: {caminho_arquivo.name}")
            return pd.DataFrame()

        except Exception as erro:
            ultimo_erro = erro
            break

    print(
        f"[TRATAMENTO] Erro ao ler {caminho_arquivo.name}: "
        f"{type(ultimo_erro).__name__}: {ultimo_erro}"
    )

    return pd.DataFrame()


# ==================================================
# VALIDAÇÃO DAS COLUNAS
# ==================================================

def validar_colunas(dataframe, caminho_arquivo):
    """
    Confirma a existência das colunas obrigatórias.
    """

    colunas_obrigatorias = {
        "id",
        "rpa",
        "processo",
        "status",
        "descricao",
        "data_log",
    }

    colunas_ausentes = colunas_obrigatorias - set(dataframe.columns)

    if colunas_ausentes:
        raise ValueError(
            f"{caminho_arquivo.name} não possui as colunas: "
            + ", ".join(sorted(colunas_ausentes))
        )


def validar_status_processo(dataframe):
    """
    Valida os valores permitidos pelo padrão oficial.
    """

    status_validos = {"sucesso", "erro"}
    processos_validos = {"iniciado", "finalizado"}

    status_encontrados = set(
        dataframe["status"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.lower()
        .unique()
    )

    processos_encontrados = set(
        dataframe["processo"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.lower()
        .unique()
    )

    status_invalidos = status_encontrados - status_validos
    processos_invalidos = processos_encontrados - processos_validos

    if status_invalidos:
        raise ValueError(
            "Status inválidos encontrados: "
            + ", ".join(sorted(status_invalidos))
        )

    if processos_invalidos:
        raise ValueError(
            "Processos inválidos encontrados: "
            + ", ".join(sorted(processos_invalidos))
        )


# ==================================================
# CHAVE DO REGISTRO
# ==================================================

def gerar_hash_registro(linha):
    """
    Gera uma chave alternativa quando não houver ID.
    """

    conteudo = "|".join(
        [
            str(linha.get("tabela_origem", "")),
            str(linha.get("rpa", "")),
            str(linha.get("processo", "")),
            str(linha.get("status", "")),
            str(linha.get("descricao_original", "")),
            str(linha.get("data_log", "")),
        ]
    )

    return hashlib.sha256(conteudo.encode("utf-8")).hexdigest()


def garantir_chave_registro(dataframe):
    """
    Garante que todos os registros possuam uma chave.
    """

    base = dataframe.copy()

    if "chave_registro" not in base.columns:
        base["chave_registro"] = pd.NA

    mascara_sem_chave = (
        base["chave_registro"].isna()
        | base["chave_registro"].astype(str).str.strip().isin(
            ["", "nan", "None", "<NA>"]
        )
    )

    mascara_com_id = mascara_sem_chave & base["id"].notna()

    base.loc[mascara_com_id, "chave_registro"] = (
        base.loc[mascara_com_id, "tabela_origem"].astype(str)
        + "_"
        + base.loc[mascara_com_id, "id"].astype(str)
    )

    mascara_sem_chave = (
        base["chave_registro"].isna()
        | base["chave_registro"].astype(str).str.strip().isin(
            ["", "nan", "None", "<NA>"]
        )
    )

    if mascara_sem_chave.any():
        base.loc[mascara_sem_chave, "chave_registro"] = (
            base.loc[mascara_sem_chave].apply(
                lambda linha: (
                    f"{linha['tabela_origem']}_"
                    f"{gerar_hash_registro(linha)}"
                ),
                axis=1,
            )
        )

    return base


# ==================================================
# RESULTADO OFICIAL
# ==================================================

def classificar_resultado(status, processo):
    """
    Classifica o resultado usando os campos oficiais.
    """

    status_texto = str(status).strip().lower()
    processo_texto = str(processo).strip().lower()

    if status_texto == "erro":
        return "FALHA"

    if status_texto == "sucesso" and processo_texto == "iniciado":
        return "INICIADO"

    if status_texto == "sucesso" and processo_texto == "finalizado":
        return "SUCESSO"

    raise ValueError(
        f"Combinação inválida: status={status}, processo={processo}"
    )


# ==================================================
# NÍVEL DA DESCRIÇÃO
# ==================================================

def identificar_nivel_descricao(descricao):
    """
    Identifica o nível escrito na descrição.

    Essa informação não substitui o status oficial.
    """

    texto = str(descricao).strip().upper()

    if texto.startswith("ERROR"):
        return "ERROR"

    if texto.startswith("WARNING") or texto.startswith("WARN"):
        return "WARNING"

    if texto.startswith("INFO"):
        return "INFO"

    if re.search(r"\bERROR\b", texto):
        return "ERROR"

    if re.search(r"\bWARNING\b|\bWARN\b", texto):
        return "WARNING"

    if re.search(r"\bINFO\b", texto):
        return "INFO"

    return "SEM_NIVEL"


# ==================================================
# NORMALIZAÇÃO DO TEXTO
# ==================================================

def remover_acentos(texto):
    """
    Remove acentos para facilitar a comparação.
    """

    texto_normalizado = unicodedata.normalize("NFKD", texto)

    return "".join(
        caractere
        for caractere in texto_normalizado
        if not unicodedata.combining(caractere)
    )


def normalizar_descricao(descricao):
    """
    Normaliza a descrição para agrupamento e ML.

    A descrição original permanece preservada.
    """

    texto = str(descricao).strip().lower()

    # Remove acentos
    texto = remover_acentos(texto)

    # Remove quebras de linha e tabulações
    texto = re.sub(r"[\r\n\t]+", " ", texto)

    # Remove os níveis do começo da mensagem
    texto = re.sub(r"^\s*(info|warning|warn|error)\s*[-:|]*\s*", "", texto)

    # Mascara e-mails
    texto = re.sub(
        r"\b[\w.\-+]+@[\w.\-]+\.\w+\b",
        " email ",
        texto,
    )

    # Mascara URLs
    texto = re.sub(r"https?://\S+", " url ", texto)

    # Mascara IPs
    texto = re.sub(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        " ip ",
        texto,
    )

    # Mascara caminhos do Windows
    texto = re.sub(
        r"[a-z]:\\(?:[^\\\s]+\\)*[^\\\s]*",
        " caminho ",
        texto,
        flags=re.IGNORECASE,
    )

    # Mascara datas no texto
    texto = re.sub(
        r"\b\d{2}[/-]\d{2}[/-]\d{2,4}\b",
        " data ",
        texto,
    )

    texto = re.sub(
        r"\b\d{4}[/-]\d{2}[/-]\d{2}\b",
        " data ",
        texto,
    )

    # Mascara horários
    texto = re.sub(
        r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
        " horario ",
        texto,
    )

    # Mascara números longos, normalmente IDs
    texto = re.sub(r"\b\d{5,}\b", " id ", texto)

    # Mascara endereços hexadecimais
    texto = re.sub(r"\b0x[0-9a-f]+\b", " endereco ", texto)

    # Mascara threads com números variáveis
    texto = re.sub(
        r"threadpoolexecutor-\d+_\d+",
        " thread ",
        texto,
    )

    # Remove conteúdo posterior ao Stacktrace
    texto = re.split(r"\bstacktrace\s*:", texto, maxsplit=1)[0]

    # Remove símbolos pouco úteis, preservando palavras
    texto = re.sub(r"[^a-z0-9_\[\]\- ]", " ", texto)

    # Remove excesso de espaços
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


# ==================================================
# PREPARAÇÃO DE UM ARQUIVO
# ==================================================

def preparar_arquivo(caminho_arquivo):
    """
    Prepara um CSV semanal do RIFAINA.
    """

    dataframe = ler_csv(caminho_arquivo)

    if dataframe.empty:
        return pd.DataFrame()

    dataframe.columns = [
        str(coluna).strip().lower()
        for coluna in dataframe.columns
    ]

    validar_colunas(
        dataframe=dataframe,
        caminho_arquivo=caminho_arquivo,
    )

    validar_status_processo(dataframe)

    base = dataframe.copy()

    if "tabela_origem" not in base.columns:
        base["tabela_origem"] = TABELA_RIFAINA

    if "chave_registro" not in base.columns:
        base["chave_registro"] = pd.NA

    if "data_extracao" not in base.columns:
        base["data_extracao"] = pd.NaT

    base = base.rename(
        columns={
            "descricao": "descricao_original"
        }
    )

    base["semana_origem"] = caminho_arquivo.parent.name
    base["arquivo_origem"] = caminho_arquivo.name

    base["data_log"] = pd.to_datetime(
        base["data_log"],
        errors="coerce",
    )

    base["data_extracao"] = pd.to_datetime(
        base["data_extracao"],
        errors="coerce",
    )

    base = base.dropna(subset=["data_log"])
    base = garantir_chave_registro(base)

    base["resultado_evento"] = base.apply(
        lambda linha: classificar_resultado(
            status=linha["status"],
            processo=linha["processo"],
        ),
        axis=1,
    )

    base["nivel_descricao"] = base["descricao_original"].apply(
        identificar_nivel_descricao
    )

    base["descricao_normalizada"] = base["descricao_original"].apply(
        normalizar_descricao
    )

    base["necessita_atencao"] = base["status"].str.lower() == "erro"

    return base


# ==================================================
# CONSOLIDAÇÃO DOS LOGS
# ==================================================

def consolidar_logs_rifaina():
    """
    Consolida todos os arquivos semanais do RIFAINA.
    """

    arquivos = localizar_arquivos_rifaina()

    resumo = {
        "arquivos_encontrados": len(arquivos),
        "arquivos_processados": 0,
        "arquivos_com_erro": 0,
        "registros_antes_duplicidade": 0,
        "duplicidades_removidas": 0,
    }

    if not arquivos:
        return pd.DataFrame(), resumo

    bases = []

    for numero, arquivo in enumerate(arquivos, start=1):
        print(
            f"[TRATAMENTO] Processando {numero}/{len(arquivos)}: "
            f"{arquivo.parent.name}/{arquivo.name}"
        )

        try:
            base_arquivo = preparar_arquivo(arquivo)

            if base_arquivo.empty:
                continue

            bases.append(base_arquivo)
            resumo["arquivos_processados"] += 1

        except Exception as erro:
            resumo["arquivos_com_erro"] += 1

            print(
                f"[TRATAMENTO] Erro em {arquivo}: "
                f"{type(erro).__name__}: {erro}"
            )

    if not bases:
        return pd.DataFrame(), resumo

    base_consolidada = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    registros_antes = len(base_consolidada)
    resumo["registros_antes_duplicidade"] = registros_antes

    base_consolidada = (
        base_consolidada
        .drop_duplicates(
            subset=["chave_registro"],
            keep="last",
        )
        .sort_values(
            by=["data_log", "id"],
            ascending=True,
        )
        .reset_index(drop=True)
    )

    duplicidades = registros_antes - len(base_consolidada)
    resumo["duplicidades_removidas"] = duplicidades

    print(f"[TRATAMENTO] Registros encontrados: {registros_antes}")
    print(f"[TRATAMENTO] Duplicidades removidas: {duplicidades}")
    print(f"[TRATAMENTO] Registros consolidados: {len(base_consolidada)}")

    return base_consolidada, resumo


# ==================================================
# AGRUPAMENTO DE PADRÕES
# ==================================================

def criar_base_padroes(base_falhas):
    """
    Agrupa descrições normalizadas iguais.

    Essa base ajudará a identificar os erros
    mais recorrentes antes da classificação manual.
    """

    if base_falhas.empty:
        return pd.DataFrame(
            columns=[
                "id_padrao",
                "descricao_normalizada",
                "quantidade_ocorrencias",
                "primeira_ocorrencia",
                "ultima_ocorrencia",
                "rpas",
                "exemplo_descricao_original",
                "categoria_sugerida",
                "categoria_validada",
                "causa_confirmada",
                "acao_recomendada",
                "status_validacao",
            ]
        )

    padroes = (
        base_falhas
        .groupby(
            "descricao_normalizada",
            dropna=False,
        )
        .agg(
            quantidade_ocorrencias=(
                "chave_registro",
                "count",
            ),
            primeira_ocorrencia=(
                "data_log",
                "min",
            ),
            ultima_ocorrencia=(
                "data_log",
                "max",
            ),
            rpas=(
                "rpa",
                lambda valores: ", ".join(
                    sorted(
                        set(
                            valores
                            .dropna()
                            .astype(str)
                        )
                    )
                ),
            ),
            exemplo_descricao_original=(
                "descricao_original",
                "first",
            ),
        )
        .reset_index()
    )

    padroes = padroes.sort_values(
        by="quantidade_ocorrencias",
        ascending=False,
    ).reset_index(drop=True)

    padroes.insert(
        0,
        "id_padrao",
        range(1, len(padroes) + 1),
    )

    padroes["categoria_sugerida"] = ""
    padroes["categoria_validada"] = ""
    padroes["causa_confirmada"] = ""
    padroes["acao_recomendada"] = ""
    padroes["status_validacao"] = "Pendente"

    return padroes


# ==================================================
# SALVAMENTO
# ==================================================

def salvar_csv_seguro(dataframe, caminho_arquivo):
    """
    Salva o CSV usando um arquivo temporário.
    """

    diretorio_saida.mkdir(parents=True, exist_ok=True)

    caminho_temporario = caminho_arquivo.with_suffix(".tmp")

    dataframe.to_csv(
        caminho_temporario,
        index=False,
        encoding="utf-8-sig",
    )

    caminho_temporario.replace(caminho_arquivo)


# ==================================================
# RESUMO
# ==================================================

def criar_resumo_tratamento(base, falhas, padroes, resumo_leitura):
    """
    Cria os indicadores principais do tratamento.
    """

    return {
        "data_processamento": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "arquivos_encontrados": resumo_leitura[
            "arquivos_encontrados"
        ],
        "arquivos_processados": resumo_leitura[
            "arquivos_processados"
        ],
        "arquivos_com_erro": resumo_leitura[
            "arquivos_com_erro"
        ],
        "registros_antes_duplicidade": resumo_leitura[
            "registros_antes_duplicidade"
        ],
        "duplicidades_removidas": resumo_leitura[
            "duplicidades_removidas"
        ],
        "total_registros": len(base),
        "total_iniciado": int(
            (base["resultado_evento"] == "INICIADO").sum()
        ),
        "total_sucesso": int(
            (base["resultado_evento"] == "SUCESSO").sum()
        ),
        "total_falha": len(falhas),
        "descricao_info": int(
            (base["nivel_descricao"] == "INFO").sum()
        ),
        "descricao_warning": int(
            (base["nivel_descricao"] == "WARNING").sum()
        ),
        "descricao_error": int(
            (base["nivel_descricao"] == "ERROR").sum()
        ),
        "descricao_sem_nivel": int(
            (base["nivel_descricao"] == "SEM_NIVEL").sum()
        ),
        "padroes_falha": len(padroes),
        "data_inicial": base["data_log"].min(),
        "data_final": base["data_log"].max(),
    }


# ==================================================
# FUNÇÃO PRINCIPAL
# ==================================================

def tratar_dados_rifaina():
    """
    Executa todo o tratamento do histórico RIFAINA.
    """

    print("\n========================================")
    print("TRATAMENTO DOS LOGS RIFAINA")
    print("========================================")

    base_consolidada, resumo_leitura = consolidar_logs_rifaina()

    if base_consolidada.empty:
        print("[TRATAMENTO] Nenhum registro válido foi encontrado.")
        return pd.DataFrame()

    # Base com todos os eventos
    salvar_csv_seguro(
        dataframe=base_consolidada,
        caminho_arquivo=arquivo_consolidado,
    )

    # Base exclusiva dos erros oficiais
    base_falhas = base_consolidada[
        base_consolidada["status"].str.strip().str.lower() == "erro"
    ].copy()

    salvar_csv_seguro(
        dataframe=base_falhas,
        caminho_arquivo=arquivo_falhas,
    )

    # Padrões de descrições de erro
    base_padroes = criar_base_padroes(base_falhas)

    salvar_csv_seguro(
        dataframe=base_padroes,
        caminho_arquivo=arquivo_padroes,
    )

    # Resumo final
    resumo = criar_resumo_tratamento(
        base=base_consolidada,
        falhas=base_falhas,
        padroes=base_padroes,
        resumo_leitura=resumo_leitura,
    )

    salvar_csv_seguro(
        dataframe=pd.DataFrame([resumo]),
        caminho_arquivo=arquivo_resumo,
    )

    print("\n========================================")
    print("RESUMO DO TRATAMENTO")
    print("========================================")

    print(f"Arquivos encontrados: {resumo['arquivos_encontrados']}")
    print(f"Arquivos processados: {resumo['arquivos_processados']}")
    print(f"Arquivos com erro: {resumo['arquivos_com_erro']}")
    print(f"Total de registros: {resumo['total_registros']}")
    print(f"Processos iniciados: {resumo['total_iniciado']}")
    print(f"Processos finalizados com sucesso: {resumo['total_sucesso']}")
    print(f"Falhas oficiais: {resumo['total_falha']}")
    print(f"Padrões diferentes de falha: {resumo['padroes_falha']}")

    print("\nNíveis encontrados na descrição:")
    print(f"INFO: {resumo['descricao_info']}")
    print(f"WARNING: {resumo['descricao_warning']}")
    print(f"ERROR: {resumo['descricao_error']}")
    print(f"SEM_NIVEL: {resumo['descricao_sem_nivel']}")

    print(
        f"\nPeríodo: {resumo['data_inicial']} "
        f"até {resumo['data_final']}"
    )

    print("\nArquivos gerados:")
    print(f"- Base consolidada: {arquivo_consolidado}")
    print(f"- Falhas: {arquivo_falhas}")
    print(f"- Padrões de falha: {arquivo_padroes}")
    print(f"- Resumo: {arquivo_resumo}")

    print("\n========================================")
    print("TRATAMENTO FINALIZADO")
    print("========================================")

    return base_consolidada