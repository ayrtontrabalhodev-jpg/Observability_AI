import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import Error

from config.config import db_pass, db_user


# Localiza a pasta principal do projeto
diretorio_raiz = Path(__file__).resolve().parent.parent

# Localiza o arquivo .env
caminho_env = diretorio_raiz / ".env"

# Carrega as variáveis do arquivo .env
load_dotenv(caminho_env)


# Variáveis não confidenciais carregadas do .env
db_host = os.environ.get("DB_HOST")
db_port = int(os.environ.get("DB_PORT", "3306"))
db_name = os.environ.get("DB_NAME")


def conectar_banco():
    """
    Cria e retorna a conexão com o banco de dados.
    """

    try:
        # Valida se as credenciais estão disponíveis
        if not db_user:
            raise ValueError(
                "A variável YELLOW_USER_DB não foi encontrada."
            )

        if not db_pass:
            raise ValueError(
                "A variável YELLOW_PASS_DB não foi encontrada."
            )

        # Valida as informações do arquivo .env
        if not db_host:
            raise ValueError(
                "A variável DB_HOST não foi encontrada no .env."
            )

        if not db_name:
            raise ValueError(
                "A variável DB_NAME não foi encontrada no .env."
            )

        conexao = mysql.connector.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            database=db_name,
            connection_timeout=15,
        )

        if conexao.is_connected():
            return conexao

        return None

    except (Error, ValueError) as erro:
        print(f"[ERRO BANCO] {erro}")
        return None


def testar_conexao():
    """
    Testa a conexão com o banco de dados.

    Retorna True em caso de sucesso e False em caso de erro.
    """

    conexao = conectar_banco()

    if conexao is None:
        print("[BANCO] Não foi possível estabelecer a conexão.")
        return False

    cursor = None

    try:
        cursor = conexao.cursor()

        cursor.execute(
            """
            SELECT
                DATABASE() AS banco,
                NOW() AS data_servidor
            """
        )

        resultado = cursor.fetchone()

        print("[BANCO] Conexão realizada com sucesso.")
        print(f"[BANCO] Banco conectado: {resultado[0]}")
        print(f"[BANCO] Data do servidor: {resultado[1]}")

        return True

    except Error as erro:
        print(f"[ERRO BANCO] Falha no teste: {erro}")
        return False

    finally:
        if cursor is not None:
            cursor.close()

        if conexao.is_connected():
            conexao.close()
            print("[BANCO] Conexão encerrada.")