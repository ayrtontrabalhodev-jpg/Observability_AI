import calendar
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from banco_de_dados.conexao import conectar_banco
from config.config import (
    meses_historico_inicial,
    pasta_historico,
    tabelas_logs,
)


# ==================================================
# CONFIGURAÇÕES E CAMINHOS
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent

load_dotenv(diretorio_raiz / ".env")

limite_registros = int(
    os.getenv("LIMITE_REGISTROS", "1000")
)

diretorio_logs = diretorio_raiz / "logs"
diretorio_historico = diretorio_logs / pasta_historico

arquivo_controle = (
    diretorio_historico
    / "controle_coleta.json"
)

diretorio_historico.mkdir(
    parents=True,
    exist_ok=True,
)


# ==================================================
# VALIDAÇÃO DA CONFIGURAÇÃO
# ==================================================

def validar_tabelas_configuradas():
    """
    Valida a lista de tabelas configuradas.
    """

    if not isinstance(tabelas_logs, list):
        raise TypeError(
            "tabelas_logs deve ser uma lista."
        )

    if not tabelas_logs:
        raise ValueError(
            "Nenhuma tabela foi configurada."
        )

    for nome_tabela in tabelas_logs:
        if not isinstance(nome_tabela, str):
            raise TypeError(
                "Todos os nomes de tabelas devem ser textos."
            )

        if not nome_tabela.strip():
            raise ValueError(
                "Existe um nome de tabela vazio."
            )


# ==================================================
# CÁLCULO DOS ÚLTIMOS DOIS MESES
# ==================================================

def subtrair_meses(data_referencia, quantidade_meses):
    """
    Subtrai meses preservando o dia sempre
    que ele existir no mês de destino.

    Exemplo:
        13/10/2026 - 2 meses = 13/08/2026
    """

    ano = data_referencia.year
    mes = data_referencia.month - quantidade_meses

    while mes <= 0:
        mes += 12
        ano -= 1

    ultimo_dia = calendar.monthrange(
        ano,
        mes,
    )[1]

    dia = min(
        data_referencia.day,
        ultimo_dia,
    )

    return data_referencia.replace(
        year=ano,
        month=mes,
        day=dia,
    )


def obter_data_inicial_historico():
    """
    Retorna a data inicial da primeira carga.
    """

    agora = datetime.now()

    return subtrair_meses(
        data_referencia=agora,
        quantidade_meses=meses_historico_inicial,
    )


# ==================================================
# CONTROLE INCREMENTAL
# ==================================================

def carregar_controle():
    """
    Carrega o controle individual das tabelas.
    """

    if not arquivo_controle.exists():
        return {}

    try:
        with open(
            arquivo_controle,
            mode="r",
            encoding="utf-8",
        ) as arquivo:
            return json.load(arquivo)

    except (json.JSONDecodeError, OSError) as erro:
        print(
            f"[CONTROLE] Erro ao ler o controle: {erro}"
        )

        return {}


def gravar_controle(controle):
    """
    Grava o controle por meio de arquivo temporário.
    """

    diretorio_historico.mkdir(
        parents=True,
        exist_ok=True,
    )

    arquivo_temporario = (
        arquivo_controle.with_suffix(".tmp")
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
            arquivo_controle
        )

    except OSError as erro:
        if arquivo_temporario.exists():
            arquivo_temporario.unlink()

        raise OSError(
            f"Erro ao salvar o controle: {erro}"
        ) from erro


def buscar_ultimo_id(nome_tabela):
    """
    Retorna o último ID coletado da tabela.
    """

    controle = carregar_controle()
    dados_tabela = controle.get(nome_tabela, {})

    return int(
        dados_tabela.get("ultimo_id", 0)
    )


def tabela_ja_inicializada(nome_tabela):
    """
    Verifica se a carga histórica da tabela
    já foi finalizada.
    """

    controle = carregar_controle()
    dados_tabela = controle.get(nome_tabela, {})

    return bool(
        dados_tabela.get(
            "carga_inicial_concluida",
            False,
        )
    )


def atualizar_controle(
    nome_tabela,
    ultimo_id,
    quantidade,
    carga_inicial_concluida,
    resultado,
):
    """
    Atualiza o controle de uma tabela.
    """

    controle = carregar_controle()
    dados_anteriores = controle.get(
        nome_tabela,
        {},
    )

    agora = datetime.now().isoformat()

    controle[nome_tabela] = {
        "ultimo_id": int(ultimo_id),
        "ultima_consulta": agora,
        "ultima_coleta_com_dados": (
            agora
            if quantidade > 0
            else dados_anteriores.get(
                "ultima_coleta_com_dados"
            )
        ),
        "quantidade_ultima_coleta": int(
            quantidade
        ),
        "carga_inicial_concluida": bool(
            carga_inicial_concluida
        ),
        "resultado_ultima_coleta": resultado,
    }

    gravar_controle(controle)


# ==================================================
# ESTRUTURA SEMANAL
# ==================================================

def obter_pasta_semana(data_referencia):
    """
    Retorna a pasta da semana correspondente
    à data do próprio log.

    A semana começa na segunda-feira e termina
    no domingo.
    """

    if isinstance(
        data_referencia,
        pd.Timestamp,
    ):
        data_referencia = (
            data_referencia.to_pydatetime()
        )

    inicio_semana = (
        data_referencia
        - timedelta(
            days=data_referencia.weekday()
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    fim_semana = (
        inicio_semana
        + timedelta(days=6)
    )

    calendario_iso = (
        data_referencia.isocalendar()
    )

    nome_pasta = (
        f"semana_{calendario_iso.year}_"
        f"{calendario_iso.week:02d}_"
        f"{inicio_semana:%d-%m}_a_"
        f"{fim_semana:%d-%m}"
    )

    pasta_semana = (
        diretorio_historico
        / nome_pasta
    )

    pasta_semana.mkdir(
        parents=True,
        exist_ok=True,
    )

    return pasta_semana


# ==================================================
# PREPARAÇÃO DOS REGISTROS
# ==================================================

def preparar_dataframe(
    nome_tabela,
    registros,
):
    """
    Converte os registros retornados pelo banco
    em DataFrame padronizado.
    """

    if not registros:
        return pd.DataFrame()

    dataframe = pd.DataFrame(registros)

    dataframe["data_log"] = pd.to_datetime(
        dataframe["data_log"],
        errors="coerce",
    )

    dataframe = dataframe.dropna(
        subset=["data_log"]
    )

    if dataframe.empty:
        return dataframe

    dataframe.insert(
        0,
        "tabela_origem",
        nome_tabela,
    )

    dataframe.insert(
        0,
        "chave_registro",
        (
            nome_tabela
            + "_"
            + dataframe["id"].astype(str)
        ),
    )

    dataframe["data_extracao"] = (
        datetime.now()
    )

    dataframe = (
        dataframe
        .drop_duplicates(
            subset=["chave_registro"],
            keep="first",
        )
        .sort_values(
            by=["data_log", "id"],
            ascending=True,
        )
        .reset_index(drop=True)
    )

    return dataframe[
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


# ==================================================
# SALVAMENTO POR SEMANA
# ==================================================

def salvar_grupo_semanal(
    nome_tabela,
    dataframe,
):
    """
    Salva os registros no CSV da semana do evento.
    """

    if dataframe.empty:
        return 0

    data_referencia = dataframe[
        "data_log"
    ].iloc[0]

    pasta_semana = obter_pasta_semana(
        data_referencia
    )

    caminho_csv = (
        pasta_semana
        / f"{nome_tabela}.csv"
    )

    if caminho_csv.exists():
        base_anterior = pd.read_csv(
            caminho_csv,
            encoding="utf-8-sig",
            low_memory=False,
        )

        base_completa = pd.concat(
            [
                base_anterior,
                dataframe,
            ],
            ignore_index=True,
        )

    else:
        base_completa = dataframe.copy()

    base_completa["data_log"] = pd.to_datetime(
        base_completa["data_log"],
        errors="coerce",
    )

    quantidade_antes = (
        len(base_completa)
        - len(dataframe)
    )

    base_completa = (
        base_completa
        .drop_duplicates(
            subset=["chave_registro"],
            keep="first",
        )
        .sort_values(
            by=["data_log", "id"],
            ascending=True,
        )
        .reset_index(drop=True)
    )

    quantidade_inserida = max(
        0,
        len(base_completa)
        - quantidade_antes,
    )

    caminho_temporario = (
        caminho_csv.with_suffix(".tmp")
    )

    base_completa.to_csv(
        caminho_temporario,
        index=False,
        encoding="utf-8-sig",
    )

    caminho_temporario.replace(
        caminho_csv
    )

    print(
        f"[CSV] {nome_tabela} | "
        f"{pasta_semana.name} | "
        f"{quantidade_inserida} novo(s) | "
        f"{len(base_completa)} total."
    )

    return quantidade_inserida


def salvar_dataframe_por_semana(
    nome_tabela,
    dataframe,
):
    """
    Divide um DataFrame pela semana do data_log.
    """

    if dataframe is None or dataframe.empty:
        return 0

    base = dataframe.copy()

    base["inicio_semana"] = (
        base["data_log"]
        - pd.to_timedelta(
            base["data_log"].dt.dayofweek,
            unit="D",
        )
    ).dt.normalize()

    total_inserido = 0

    for _, grupo in base.groupby(
        "inicio_semana"
    ):
        grupo = grupo.drop(
            columns=["inicio_semana"]
        )

        total_inserido += (
            salvar_grupo_semanal(
                nome_tabela=nome_tabela,
                dataframe=grupo,
            )
        )

    return total_inserido


# ==================================================
# CARGA INICIAL DOS ÚLTIMOS DOIS MESES
# ==================================================

def executar_carga_inicial_tabela(
    nome_tabela,
):
    """
    Executa uma única carga histórica dos últimos
    dois meses para a tabela.

    Os registros são processados em lotes.
    """

    data_inicial = (
        obter_data_inicial_historico()
    )

    data_final = datetime.now()

    ultimo_id_lote = 0
    total_processado = 0
    maior_id = 0

    print(
        f"\n[CARGA INICIAL] {nome_tabela}"
    )

    print(
        "[CARGA INICIAL] Período: "
        f"{data_inicial:%d/%m/%Y %H:%M:%S} até "
        f"{data_final:%d/%m/%Y %H:%M:%S}"
    )

    while True:
        conexao = conectar_banco()

        if conexao is None:
            raise ConnectionError(
                f"Falha na conexão para {nome_tabela}."
            )

        cursor = None

        try:
            cursor = conexao.cursor(
                dictionary=True
            )

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
                  AND data_log <= %s
                  AND id > %s
                ORDER BY id ASC
                LIMIT %s
            """

            cursor.execute(
                query,
                (
                    data_inicial,
                    data_final,
                    ultimo_id_lote,
                    limite_registros,
                ),
            )

            registros = cursor.fetchall()

        finally:
            if cursor is not None:
                cursor.close()

            if (
                conexao is not None
                and conexao.is_connected()
            ):
                conexao.close()

        if not registros:
            break

        dataframe = preparar_dataframe(
            nome_tabela=nome_tabela,
            registros=registros,
        )

        if not dataframe.empty:
            salvar_dataframe_por_semana(
                nome_tabela=nome_tabela,
                dataframe=dataframe,
            )

            total_processado += len(dataframe)
            maior_id = max(
                maior_id,
                int(dataframe["id"].max()),
            )

        ultimo_id_lote = max(
            int(registro["id"])
            for registro in registros
        )

        print(
            f"[CARGA INICIAL] {nome_tabela}: "
            f"{total_processado} registro(s) processado(s)."
        )

        if len(registros) < limite_registros:
            break

    atualizar_controle(
        nome_tabela=nome_tabela,
        ultimo_id=maior_id,
        quantidade=total_processado,
        carga_inicial_concluida=True,
        resultado="Carga inicial concluída",
    )

    print(
        f"[CARGA INICIAL] {nome_tabela}: "
        f"{total_processado} registro(s) no total."
    )

    return {
        "tabela": nome_tabela,
        "resultado": "Carga inicial concluída",
        "quantidade": total_processado,
        "ultimo_id": maior_id,
    }


# ==================================================
# COLETA INCREMENTAL
# ==================================================

def executar_coleta_incremental_tabela(
    nome_tabela,
):
    """
    Busca somente IDs maiores que o último ID
    registrado para a tabela.

    Continua lendo lotes até esvaziar a fila.
    """

    ultimo_id = buscar_ultimo_id(
        nome_tabela
    )

    total_processado = 0
    maior_id = ultimo_id

    print(
        f"\n[INCREMENTAL] {nome_tabela}"
    )

    print(
        f"[INCREMENTAL] Último ID: {ultimo_id}"
    )

    while True:
        conexao = conectar_banco()

        if conexao is None:
            raise ConnectionError(
                f"Falha na conexão para {nome_tabela}."
            )

        cursor = None

        try:
            cursor = conexao.cursor(
                dictionary=True
            )

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

            cursor.execute(
                query,
                (
                    maior_id,
                    limite_registros,
                ),
            )

            registros = cursor.fetchall()

        finally:
            if cursor is not None:
                cursor.close()

            if (
                conexao is not None
                and conexao.is_connected()
            ):
                conexao.close()

        if not registros:
            break

        dataframe = preparar_dataframe(
            nome_tabela=nome_tabela,
            registros=registros,
        )

        if not dataframe.empty:
            salvar_dataframe_por_semana(
                nome_tabela=nome_tabela,
                dataframe=dataframe,
            )

            total_processado += len(dataframe)
            maior_id = max(
                maior_id,
                int(dataframe["id"].max()),
            )

        else:
            maior_id = max(
                int(registro["id"])
                for registro in registros
            )

        if len(registros) < limite_registros:
            break

    resultado = (
        "Registros novos coletados"
        if total_processado > 0
        else "Sem registros novos"
    )

    atualizar_controle(
        nome_tabela=nome_tabela,
        ultimo_id=maior_id,
        quantidade=total_processado,
        carga_inicial_concluida=True,
        resultado=resultado,
    )

    print(
        f"[INCREMENTAL] {nome_tabela}: "
        f"{total_processado} registro(s) novo(s)."
    )

    return {
        "tabela": nome_tabela,
        "resultado": resultado,
        "quantidade": total_processado,
        "ultimo_id": maior_id,
    }


# ==================================================
# EXECUÇÃO DE UMA TABELA
# ==================================================

def processar_tabela(nome_tabela):
    """
    Decide automaticamente se deve executar:

    - carga histórica inicial;
    - coleta incremental.
    """

    if tabela_ja_inicializada(
        nome_tabela
    ):
        return executar_coleta_incremental_tabela(
            nome_tabela
        )

    return executar_carga_inicial_tabela(
        nome_tabela
    )


# ==================================================
# EXECUÇÃO DE TODAS AS TABELAS
# ==================================================

def extrair_todas_as_tabelas():
    """
    Processa todas as tabelas configuradas.

    A primeira execução de cada tabela busca os
    últimos dois meses.

    As execuções seguintes buscam apenas IDs novos.
    """

    validar_tabelas_configuradas()

    resultados = []

    print("\n========================================")
    print("COLETA DO HISTÓRICO DO MVP")
    print("========================================")

    print(
        f"[COLETA] Pasta: {diretorio_historico}"
    )

    print(
        f"[COLETA] Tabelas configuradas: "
        f"{len(tabelas_logs)}"
    )

    for nome_tabela in tabelas_logs:
        try:
            resultado = processar_tabela(
                nome_tabela
            )

        except Exception as erro:
            mensagem = (
                f"{type(erro).__name__}: {erro}"
            )

            print(
                f"[COLETA] Erro em {nome_tabela}: "
                f"{mensagem}"
            )

            ultimo_id = buscar_ultimo_id(
                nome_tabela
            )

            atualizar_controle(
                nome_tabela=nome_tabela,
                ultimo_id=ultimo_id,
                quantidade=0,
                carga_inicial_concluida=(
                    tabela_ja_inicializada(
                        nome_tabela
                    )
                ),
                resultado=mensagem,
            )

            resultado = {
                "tabela": nome_tabela,
                "resultado": "Erro",
                "quantidade": 0,
                "ultimo_id": ultimo_id,
                "erro": mensagem,
            }

        resultados.append(resultado)

    total_registros = sum(
        item.get("quantidade", 0)
        for item in resultados
    )

    total_erros = sum(
        1
        for item in resultados
        if item.get("resultado") == "Erro"
    )

    return {
        "total_registros": total_registros,
        "total_tabelas": len(resultados),
        "total_erros": total_erros,
        "resultados": resultados,
    }