import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from Banco_de_Dados.conexao import conectar_banco
from config.config import (
    data_inicio_projeto,
    tabelas,
)


# =====================================================
# CAMINHOS E CONFIGURAÇÕES
# =====================================================

diretorio_raiz = Path(__file__).resolve().parent.parent

diretorio_logs = diretorio_raiz / "logs"

arquivo_controle = (
    diretorio_logs / "controle_coleta.json"
)

load_dotenv(diretorio_raiz / ".env")


limite_registros = int(
    os.getenv("LIMITE_REGISTROS", "1000")
)


# Cria a pasta logs automaticamente
diretorio_logs.mkdir(
    parents=True,
    exist_ok=True,
)


# =====================================================
# CONTROLE DAS SEMANAS
# =====================================================

def calcular_semana_atual():
    """
    Calcula a semana do projeto.

    Semana 1:
    06/10/2026 até 12/10/2026

    Semana 2:
    13/10/2026 até 19/10/2026
    """

    data_inicial = datetime.strptime(
        data_inicio_projeto,
        "%Y-%m-%d",
    ).date()

    data_atual = date.today()

    if data_atual < data_inicial:
        raise ValueError(
            "A data atual é anterior ao início do projeto."
        )

    dias_decorridos = (
        data_atual - data_inicial
    ).days

    numero_semana = (
        dias_decorridos // 7
    ) + 1

    inicio_semana = (
        data_inicial
        + timedelta(
            days=(numero_semana - 1) * 7
        )
    )

    fim_semana = (
        inicio_semana
        + timedelta(days=6)
    )

    return (
        numero_semana,
        inicio_semana,
        fim_semana,
    )


def obter_pasta_semana():
    """
    Cria e retorna a pasta da semana atual.
    """

    (
        numero_semana,
        inicio_semana,
        fim_semana,
    ) = calcular_semana_atual()

    nome_pasta = (
        f"semana_{numero_semana:02d}_"
        f"{inicio_semana:%Y-%m-%d}_a_"
        f"{fim_semana:%Y-%m-%d}"
    )

    pasta_semana = (
        diretorio_logs / nome_pasta
    )

    pasta_semana.mkdir(
        parents=True,
        exist_ok=True,
    )

    return pasta_semana


# =====================================================
# CONTROLE DO ÚLTIMO ID COLETADO
# =====================================================

def carregar_controle():
    """
    Carrega o último ID coletado de cada tabela.
    """

    if not arquivo_controle.exists():
        return {}

    try:
        with open(
            arquivo_controle,
            "r",
            encoding="utf-8",
        ) as arquivo:

            return json.load(arquivo)

    except (
        json.JSONDecodeError,
        OSError,
    ):
        print(
            "[CONTROLE] Arquivo de controle inválido. "
            "Um novo controle será criado."
        )

        return {}


def salvar_controle(controle):
    """
    Salva o último ID coletado de cada tabela.
    """

    with open(
        arquivo_controle,
        "w",
        encoding="utf-8",
    ) as arquivo:

        json.dump(
            controle,
            arquivo,
            indent=4,
            ensure_ascii=False,
        )


def buscar_ultimo_id(nome_tabela):
    """
    Retorna o último ID coletado da tabela.
    """

    controle = carregar_controle()

    dados_tabela = controle.get(
        nome_tabela,
        {},
    )

    return int(
        dados_tabela.get(
            "ultimo_id",
            0,
        )
    )


def atualizar_ultimo_id(
    nome_tabela,
    ultimo_id,
):
    """
    Atualiza o último ID coletado da tabela.
    """

    controle = carregar_controle()

    controle[nome_tabela] = {
        "ultimo_id": int(ultimo_id),
        "ultima_coleta": (
            datetime.now().isoformat()
        ),
    }

    salvar_controle(controle)


# =====================================================
# EXTRAÇÃO DOS DADOS
# =====================================================

def executar_consulta(
    conexao,
    nome_tabela,
    ultimo_id,
):
    """
    Executa a consulta e retorna um DataFrame.
    """

    cursor = conexao.cursor(
        dictionary=True
    )

    try:
        if ultimo_id == 0:
            # Primeira coleta:
            # traz somente registros de hoje em diante
            query = f"""
                SELECT
                    id,
                    rpa,
                    processo,
                    status,
                    descricao,
                    data_log
                FROM {nome_tabela}
                WHERE data_log >= %s
                ORDER BY id ASC
                LIMIT %s
            """

            parametros = (
                data_inicio_projeto,
                limite_registros,
            )

        else:
            # Próximas coletas:
            # traz somente IDs ainda não coletados
            query = f"""
                SELECT
                    id,
                    rpa,
                    processo,
                    status,
                    descricao,
                    data_log
                FROM {nome_tabela}
                WHERE id > %s
                ORDER BY id ASC
                LIMIT %s
            """

            parametros = (
                ultimo_id,
                limite_registros,
            )

        cursor.execute(
            query,
            parametros,
        )

        registros = cursor.fetchall()

        if not registros:
            return pd.DataFrame()

        return pd.DataFrame(registros)

    finally:
        cursor.close()


def extrair_tabela(nome_tabela):
    """
    Extrai os registros novos de uma tabela.
    """

    if nome_tabela not in tabelas:
        raise ValueError(
            f"Tabela não autorizada: {nome_tabela}"
        )

    ultimo_id = buscar_ultimo_id(
        nome_tabela
    )

    print(
        f"\n[EXTRAÇÃO] Tabela: {nome_tabela}"
    )

    print(
        f"[EXTRAÇÃO] Último ID coletado: "
        f"{ultimo_id}"
    )

    conexao = conectar_banco()

    if conexao is None:
        print(
            "[EXTRAÇÃO] Não foi possível "
            "conectar ao banco."
        )

        return pd.DataFrame()

    try:
        dataframe = executar_consulta(
            conexao=conexao,
            nome_tabela=nome_tabela,
            ultimo_id=ultimo_id,
        )

        if dataframe.empty:
            print(
                "[EXTRAÇÃO] Nenhum registro novo."
            )

            return dataframe

        # Identifica a origem
        dataframe.insert(
            0,
            "tabela_origem",
            nome_tabela,
        )

        # Chave única
        dataframe.insert(
            0,
            "chave_registro",
            (
                nome_tabela
                + "_"
                + dataframe["id"].astype(str)
            ),
        )

        # Momento da coleta
        dataframe["data_extracao"] = (
            datetime.now()
        )

        dataframe["data_log"] = (
            pd.to_datetime(
                dataframe["data_log"],
                errors="coerce",
            )
        )

        dataframe = dataframe[
            [
                "chave_registro",
                "tabela_origem",
                "id",
                "rpa",
                "processo",
                "status",
                "descricao",
                "data_log",
                "data_extracao",
            ]
        ]

        print(
            f"[EXTRAÇÃO] "
            f"{len(dataframe)} registro(s) novo(s)."
        )

        return dataframe

    except Exception as erro:
        print(
            f"[ERRO EXTRAÇÃO] "
            f"{nome_tabela}: {erro}"
        )

        return pd.DataFrame()

    finally:
        if conexao.is_connected():
            conexao.close()


def extrair_todos_os_processos():
    """
    Extrai separadamente todas as tabelas
    configuradas.
    """

    resultado = {}

    for nome_tabela in tabelas:
        dataframe = extrair_tabela(
            nome_tabela
        )

        resultado[nome_tabela] = dataframe

    return resultado


# =====================================================
# SALVAMENTO POR SEMANA
# =====================================================

def salvar_tabela_semanal(
    nome_tabela,
    dataframe,
):
    """
    Salva os dados da tabela no CSV da semana.
    """

    if dataframe.empty:
        return 0

    pasta_semana = obter_pasta_semana()

    caminho_csv = (
        pasta_semana
        / f"{nome_tabela}.csv"
    )

    # Verifica se o arquivo já existe
    arquivo_existe = caminho_csv.exists()

    dataframe.to_csv(
        caminho_csv,
        mode="a",
        header=not arquivo_existe,
        index=False,
        encoding="utf-8-sig",
    )

    ultimo_id = int(
        dataframe["id"].max()
    )

    atualizar_ultimo_id(
        nome_tabela=nome_tabela,
        ultimo_id=ultimo_id,
    )

    print(
        f"[SALVAMENTO] "
        f"{len(dataframe)} registro(s) salvo(s)."
    )

    print(
        f"[SALVAMENTO] Arquivo: "
        f"{caminho_csv}"
    )

    return len(dataframe)


def salvar_base_local(
    bases_extraidas,
):
    """
    Salva os DataFrames em arquivos semanais.
    """

    total_inserido = 0

    for (
        nome_tabela,
        dataframe,
    ) in bases_extraidas.items():

        quantidade = salvar_tabela_semanal(
            nome_tabela=nome_tabela,
            dataframe=dataframe,
        )

        total_inserido += quantidade

    print(
        f"\n[SALVAMENTO] Total desta coleta: "
        f"{total_inserido} registro(s)."
    )

    return total_inserido


# =====================================================
# VALIDAÇÃO
# =====================================================

def validar_base_local():
    """
    Mostra um resumo dos arquivos da semana.
    """

    pasta_semana = obter_pasta_semana()

    print("\n===== RESUMO DA SEMANA =====")
    print(f"Pasta: {pasta_semana.name}")

    for nome_tabela in tabelas:
        caminho_csv = (
            pasta_semana
            / f"{nome_tabela}.csv"
        )

