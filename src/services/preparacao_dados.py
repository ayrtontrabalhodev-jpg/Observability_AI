import hashlib
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


# ==================================================
# CAMINHOS DO PROJETO
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent.parent
diretorio_historico = diretorio_raiz / "logs" / "historico"
diretorio_base_tratada = diretorio_raiz / "base_tratada"

arquivo_logs_consolidados = diretorio_base_tratada / "logs_consolidados.csv"
arquivo_eventos_atencao = diretorio_base_tratada / "eventos_atencao.csv"
arquivo_resumo_preparacao = diretorio_base_tratada / "resumo_preparacao.csv"


# ==================================================
# COLUNAS PADRONIZADAS
# ==================================================

colunas_padrao = [
    "chave_registro",
    "tabela_origem",
    "id",
    "rpa",
    "processo",
    "status",
    "resultado_evento",
    "descricao_original",
    "nivel_descricao",
    "necessita_atencao",
    "data_log",
    "data_extracao",
    "semana_origem",
    "arquivo_origem",
]


# ==================================================
# LOCALIZAÇÃO DOS ARQUIVOS
# ==================================================

def localizar_arquivos_csv():
    """
    Localiza os CSVs dentro das pastas semanais.

    Padrão:
        logs/historico/semana_*/*.csv
    """

    if not diretorio_historico.exists():
        print("[PREPARAÇÃO] A pasta de histórico não foi encontrada:")
        print(f"[PREPARAÇÃO] {diretorio_historico}")
        return []

    arquivos = sorted(diretorio_historico.glob("semana_*/*.csv"))

    nomes_ignorados = {
        "resumo_historico.csv",
        "resumo_preparacao.csv",
        "log_execucao.csv",
        "controle_coleta.csv",
    }

    arquivos_validos = [
        arquivo
        for arquivo in arquivos
        if arquivo.name.lower() not in nomes_ignorados
    ]

    print(f"[PREPARAÇÃO] Arquivos semanais encontrados: {len(arquivos_validos)}")

    return arquivos_validos


# ==================================================
# LEITURA SEGURA DOS ARQUIVOS
# ==================================================

def ler_arquivo_csv(caminho_arquivo):
    """
    Lê um CSV tentando diferentes codificações.
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
            continue

        except pd.errors.EmptyDataError:
            print(f"[PREPARAÇÃO] Arquivo vazio: {caminho_arquivo}")
            return pd.DataFrame()

        except Exception as erro:
            ultimo_erro = erro
            break

    print(
        f"[PREPARAÇÃO] Erro ao ler {caminho_arquivo.name}: "
        f"{type(ultimo_erro).__name__}: {ultimo_erro}"
    )

    return pd.DataFrame()


# ==================================================
# PADRONIZAÇÃO DOS NOMES DAS COLUNAS
# ==================================================

def padronizar_nome_colunas(dataframe):
    """
    Padroniza os nomes das colunas.

    Exemplo:
        Data Log -> data_log
    """

    base = dataframe.copy()
    novas_colunas = []

    for coluna in base.columns:
        nome = str(coluna).strip().lower()
        nome = re.sub(r"\s+", "_", nome)
        nome = re.sub(r"[^a-z0-9_]", "", nome)
        novas_colunas.append(nome)

    base.columns = novas_colunas

    return base


# ==================================================
# IDENTIFICAÇÃO DA ORIGEM
# ==================================================

def identificar_tabela_origem(dataframe, caminho_arquivo):
    """
    Garante a existência da coluna tabela_origem.
    """

    base = dataframe.copy()

    if "tabela_origem" not in base.columns:
        base["tabela_origem"] = caminho_arquivo.stem

    base["tabela_origem"] = (
        base["tabela_origem"]
        .fillna(caminho_arquivo.stem)
        .astype(str)
        .str.strip()
    )

    return base


def adicionar_origem_arquivo(dataframe, caminho_arquivo):
    """
    Adiciona a semana e o arquivo de origem.
    """

    base = dataframe.copy()
    base["semana_origem"] = caminho_arquivo.parent.name
    base["arquivo_origem"] = caminho_arquivo.name

    return base


# ==================================================
# PADRONIZAÇÃO DAS COLUNAS PRINCIPAIS
# ==================================================

def padronizar_colunas_log(dataframe):
    """
    Padroniza as colunas principais.

    A descrição original fica preservada em:
        descricao_original
    """

    base = dataframe.copy()
    renomear = {}

    if "descricao" in base.columns and "descricao_original" not in base.columns:
        renomear["descricao"] = "descricao_original"

    if "data" in base.columns and "data_log" not in base.columns:
        renomear["data"] = "data_log"

    if "dat_log" in base.columns and "data_log" not in base.columns:
        renomear["dat_log"] = "data_log"

    if "id_origem" in base.columns and "id" not in base.columns:
        renomear["id_origem"] = "id"

    base = base.rename(columns=renomear)

    colunas_necessarias = [
        "id",
        "rpa",
        "processo",
        "status",
        "descricao_original",
        "data_log",
        "data_extracao",
    ]

    for coluna in colunas_necessarias:
        if coluna not in base.columns:
            base[coluna] = pd.NA

    return base


# ==================================================
# VALIDAÇÃO DOS CAMPOS OFICIAIS
# ==================================================

def validar_status_e_processo(dataframe):
    """
    Valida os valores oficiais definidos no banco.

    status:
        Sucesso
        Erro

    processo:
        Iniciado
        Finalizado
    """

    base = dataframe.copy()

    status_validos = {"sucesso", "erro"}
    processos_validos = {"iniciado", "finalizado"}

    if base["status"].isna().any():
        raise ValueError("Existem registros sem status.")

    if base["processo"].isna().any():
        raise ValueError("Existem registros sem processo.")

    status_encontrados = set(
        base["status"]
        .astype(str)
        .str.strip()
        .str.lower()
        .unique()
    )

    processos_encontrados = set(
        base["processo"]
        .astype(str)
        .str.strip()
        .str.lower()
        .unique()
    )

    status_invalidos = status_encontrados - status_validos
    processos_invalidos = processos_encontrados - processos_validos

    if status_invalidos:
        raise ValueError(
            "Valores inválidos na coluna status: "
            + ", ".join(sorted(status_invalidos))
        )

    if processos_invalidos:
        raise ValueError(
            "Valores inválidos na coluna processo: "
            + ", ".join(sorted(processos_invalidos))
        )

    return base


# ==================================================
# TRATAMENTO DAS DATAS
# ==================================================

def tratar_datas(dataframe):
    """
    Converte as colunas de data.
    """

    base = dataframe.copy()

    base["data_log"] = pd.to_datetime(base["data_log"], errors="coerce")
    base["data_extracao"] = pd.to_datetime(
        base["data_extracao"],
        errors="coerce",
    )

    return base


# ==================================================
# CRIAÇÃO DA CHAVE ÚNICA
# ==================================================

def gerar_hash_registro(linha):
    """
    Gera uma chave estável para registros sem ID.
    """

    valores = [
        linha.get("tabela_origem", ""),
        linha.get("rpa", ""),
        linha.get("processo", ""),
        linha.get("status", ""),
        linha.get("descricao_original", ""),
        linha.get("data_log", ""),
    ]

    conteudo = "|".join(str(valor) for valor in valores)
    hash_registro = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
    tabela = linha.get("tabela_origem", "tabela")

    return f"{tabela}_{hash_registro}"


def valor_esta_ausente(valor):
    """
    Verifica se um valor está ausente.
    """

    if pd.isna(valor):
        return True

    return str(valor).strip() in {
        "",
        "nan",
        "None",
        "<NA>",
    }


def garantir_chave_registro(dataframe):
    """
    Garante uma chave única para cada registro.

    Com ID:
        tabela_origem + ID

    Sem ID:
        hash do conteúdo
    """

    base = dataframe.copy()

    if "chave_registro" not in base.columns:
        base["chave_registro"] = pd.NA

    for indice, linha in base.iterrows():
        chave_atual = linha.get("chave_registro")

        if not valor_esta_ausente(chave_atual):
            continue

        id_registro = linha.get("id")

        if not valor_esta_ausente(id_registro):
            tabela = linha.get("tabela_origem", "tabela")
            base.at[indice, "chave_registro"] = f"{tabela}_{id_registro}"
        else:
            base.at[indice, "chave_registro"] = gerar_hash_registro(linha)

    return base


# ==================================================
# RESULTADO OFICIAL DO EVENTO
# ==================================================

def classificar_resultado_evento(status, processo):
    """
    Classifica o evento usando status e processo.

    Erro:
        FALHA

    Sucesso + Iniciado:
        INICIADO

    Sucesso + Finalizado:
        SUCESSO
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
# NÍVEL ENCONTRADO NA DESCRIÇÃO
# ==================================================

def identificar_nivel_descricao(descricao):
    """
    Identifica INFO, WARNING ou ERROR quando
    essas palavras estiverem na descrição.

    O resultado não substitui o status oficial.
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

    if re.search(r"\bWARNING\b", texto) or re.search(r"\bWARN\b", texto):
        return "WARNING"

    if re.search(r"\bINFO\b", texto):
        return "INFO"

    return "SEM_NIVEL"


def adicionar_classificacao_evento(dataframe):
    """
    Adiciona:

        resultado_evento
        nivel_descricao
        necessita_atencao
    """

    base = dataframe.copy()

    base["resultado_evento"] = base.apply(
        lambda linha: classificar_resultado_evento(
            status=linha["status"],
            processo=linha["processo"],
        ),
        axis=1,
    )

    base["nivel_descricao"] = base["descricao_original"].apply(
        identificar_nivel_descricao
    )

    # Apenas status Erro entra na base para classificação
    base["necessita_atencao"] = base["resultado_evento"] == "FALHA"

    return base


# ==================================================
# PREPARAÇÃO DE UM ARQUIVO
# ==================================================

def preparar_arquivo(caminho_arquivo):
    """
    Lê e prepara um arquivo semanal.
    """

    dataframe = ler_arquivo_csv(caminho_arquivo)

    if dataframe.empty:
        return pd.DataFrame()

    dataframe = padronizar_nome_colunas(dataframe)

    dataframe = identificar_tabela_origem(
        dataframe=dataframe,
        caminho_arquivo=caminho_arquivo,
    )

    dataframe = adicionar_origem_arquivo(
        dataframe=dataframe,
        caminho_arquivo=caminho_arquivo,
    )

    dataframe = padronizar_colunas_log(dataframe)
    dataframe = validar_status_e_processo(dataframe)
    dataframe = tratar_datas(dataframe)
    dataframe = garantir_chave_registro(dataframe)
    dataframe = adicionar_classificacao_evento(dataframe)

    return dataframe


# ==================================================
# CONSOLIDAÇÃO DOS ARQUIVOS
# ==================================================

def consolidar_logs_historicos():
    """
    Consolida todos os arquivos semanais.

    Retorna:
        DataFrame consolidado
        Resumo da consolidação
    """

    arquivos = localizar_arquivos_csv()

    resumo_consolidacao = {
        "arquivos_encontrados": len(arquivos),
        "arquivos_processados": 0,
        "arquivos_com_erro": 0,
        "registros_antes_duplicidade": 0,
        "duplicidades_removidas": 0,
    }

    if not arquivos:
        print("[PREPARAÇÃO] Nenhum arquivo CSV foi encontrado.")
        return pd.DataFrame(), resumo_consolidacao

    bases = []

    for numero, caminho_arquivo in enumerate(arquivos, start=1):
        print(
            f"[PREPARAÇÃO] Processando {numero}/{len(arquivos)}: "
            f"{caminho_arquivo.name}"
        )

        try:
            base_arquivo = preparar_arquivo(caminho_arquivo)

            if base_arquivo.empty:
                continue

            bases.append(base_arquivo)
            resumo_consolidacao["arquivos_processados"] += 1

        except Exception as erro:
            resumo_consolidacao["arquivos_com_erro"] += 1

            print(
                f"[PREPARAÇÃO] Erro em {caminho_arquivo}: "
                f"{type(erro).__name__}: {erro}"
            )

    if not bases:
        return pd.DataFrame(), resumo_consolidacao

    base_consolidada = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    registros_antes = len(base_consolidada)

    resumo_consolidacao["registros_antes_duplicidade"] = registros_antes

    base_consolidada = (
        base_consolidada
        .drop_duplicates(
            subset=["chave_registro"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    duplicidades_removidas = registros_antes - len(base_consolidada)

    resumo_consolidacao["duplicidades_removidas"] = duplicidades_removidas

    base_consolidada = (
        base_consolidada
        .sort_values(
            by=[
                "data_log",
                "tabela_origem",
                "chave_registro",
            ],
            ascending=True,
            na_position="last",
        )
        .reset_index(drop=True)
    )

    for coluna in colunas_padrao:
        if coluna not in base_consolidada.columns:
            base_consolidada[coluna] = pd.NA

    colunas_adicionais = [
        coluna
        for coluna in base_consolidada.columns
        if coluna not in colunas_padrao
    ]

    base_consolidada = base_consolidada[
        colunas_padrao + colunas_adicionais
    ]

    print(f"[PREPARAÇÃO] Registros antes da deduplicação: {registros_antes}")
    print(f"[PREPARAÇÃO] Duplicidades removidas: {duplicidades_removidas}")
    print(f"[PREPARAÇÃO] Registros consolidados: {len(base_consolidada)}")

    return base_consolidada, resumo_consolidacao


# ==================================================
# SALVAMENTO SEGURO
# ==================================================

def salvar_base_tratada(dataframe, caminho_arquivo):
    """
    Salva um DataFrame usando arquivo temporário.
    """

    diretorio_base_tratada.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho_temporario = caminho_arquivo.with_suffix(".tmp")

    dataframe.to_csv(
        caminho_temporario,
        index=False,
        encoding="utf-8-sig",
    )

    caminho_temporario.replace(caminho_arquivo)


# ==================================================
# RESUMO DA PREPARAÇÃO
# ==================================================

def criar_resumo_preparacao(base, resumo_consolidacao):
    """
    Cria os indicadores da preparação.
    """

    return {
        "data_processamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "arquivos_encontrados": resumo_consolidacao["arquivos_encontrados"],
        "arquivos_processados": resumo_consolidacao["arquivos_processados"],
        "arquivos_com_erro": resumo_consolidacao["arquivos_com_erro"],
        "registros_antes_duplicidade": (
            resumo_consolidacao["registros_antes_duplicidade"]
        ),
        "duplicidades_removidas": (
            resumo_consolidacao["duplicidades_removidas"]
        ),
        "total_registros": len(base),
        "total_tabelas": int(base["tabela_origem"].nunique()),
        "total_sucesso": int(
            (base["resultado_evento"] == "SUCESSO").sum()
        ),
        "total_falha": int(
            (base["resultado_evento"] == "FALHA").sum()
        ),
        "total_iniciado": int(
            (base["resultado_evento"] == "INICIADO").sum()
        ),
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
        "eventos_atencao": int(
            base["necessita_atencao"].sum()
        ),
        "data_inicial": base["data_log"].min(),
        "data_final": base["data_log"].max(),
    }


def salvar_resumo_preparacao(resumo):
    """
    Salva o resumo em CSV.
    """

    dataframe_resumo = pd.DataFrame([resumo])

    salvar_base_tratada(
        dataframe=dataframe_resumo,
        caminho_arquivo=arquivo_resumo_preparacao,
    )


# ==================================================
# FUNÇÃO PRINCIPAL
# ==================================================

def preparar_dados():
    """
    Executa todo o processo de preparação.

    O status determina sucesso ou falha.
    O processo informa início ou finalização.
    A descrição será usada para classificar
    a natureza da falha.
    """

    print("\n========================================")
    print("PREPARAÇÃO DOS DADOS")
    print("========================================")

    base_consolidada, resumo_consolidacao = consolidar_logs_historicos()

    if base_consolidada is None or base_consolidada.empty:
        print("[PREPARAÇÃO] Nenhum registro válido foi encontrado.")
        return pd.DataFrame()

    # Base completa
    salvar_base_tratada(
        dataframe=base_consolidada,
        caminho_arquivo=arquivo_logs_consolidados,
    )

    # Somente registros cujo status oficial é Erro
    eventos_atencao = base_consolidada[
        base_consolidada["necessita_atencao"]
    ].copy()

    salvar_base_tratada(
        dataframe=eventos_atencao,
        caminho_arquivo=arquivo_eventos_atencao,
    )

    resumo = criar_resumo_preparacao(
        base=base_consolidada,
        resumo_consolidacao=resumo_consolidacao,
    )

    salvar_resumo_preparacao(resumo)

    print("\n========================================")
    print("RESUMO DA PREPARAÇÃO")
    print("========================================")

    print(f"Arquivos encontrados: {resumo['arquivos_encontrados']}")
    print(f"Arquivos processados: {resumo['arquivos_processados']}")
    print(f"Arquivos com erro: {resumo['arquivos_com_erro']}")
    print(
        f"Registros antes da deduplicação: "
        f"{resumo['registros_antes_duplicidade']}"
    )
    print(f"Duplicidades removidas: {resumo['duplicidades_removidas']}")
    print(f"Total consolidado: {resumo['total_registros']}")
    print(f"Tabelas processadas: {resumo['total_tabelas']}")

    print("\nResultados oficiais:")
    print(f"SUCESSO FINALIZADO: {resumo['total_sucesso']}")
    print(f"PROCESSO INICIADO: {resumo['total_iniciado']}")
    print(f"FALHA: {resumo['total_falha']}")

    print("\nNíveis encontrados na descrição:")
    print(f"INFO: {resumo['descricao_info']}")
    print(f"WARNING: {resumo['descricao_warning']}")
    print(f"ERROR: {resumo['descricao_error']}")
    print(f"SEM_NIVEL: {resumo['descricao_sem_nivel']}")

    print(
        f"\nEventos separados para classificação: "
        f"{resumo['eventos_atencao']}"
    )

    print(
        f"\nPeríodo analisado: "
        f"{resumo['data_inicial']} até {resumo['data_final']}"
    )

    print("\nArquivos gerados:")
    print(f"- Base consolidada: {arquivo_logs_consolidados}")
    print(f"- Eventos com status Erro: {arquivo_eventos_atencao}")
    print(f"- Resumo: {arquivo_resumo_preparacao}")

    print("\n========================================")
    print("PREPARAÇÃO FINALIZADA")
    print("========================================")

    return base_consolidada