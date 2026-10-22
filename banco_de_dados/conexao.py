import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import Error

from config.config import db_pass, db_user


# Localiza a raiz do projeto
diretorio_raiz = Path(__file__).resolve().parent.parent

# Carrega o arquivo .env
load_dotenv(diretorio_raiz / ".env")


# Informações não confidenciais do banco
db_host = os.environ.get("DB_HOST")
db_port = int(os.environ.get("DB_PORT", "3306"))
db_name = os.environ.get("DB_NAME")


def conectar_banco():
    """
    Cria e retorna uma conexão com o banco de dados.
    """

    try:
        # Validação das variáveis de ambiente
        if not db_user:
            raise ValueError(
                "A variável YELLOW_USER_DB não foi encontrada."
            )

        if not db_pass:
            raise ValueError(
                "A variável YELLOW_PASS_DB não foi encontrada."
            )

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

        return conexao

    except ValueError as erro:
        print(f"[CONFIGURAÇÃO] {erro}")
        return None

    except Error as erro:
        print(f"[BANCO] Erro ao conectar: {erro}")
        return None


def testar_conexao():
    """
    Testa o acesso ao banco de dados.
    """

    conexao = conectar_banco()

    if conexao is None:
        return False

    cursor = None

    try:
        cursor = conexao.cursor()

        cursor.execute(
            """
            SELECT
                DATABASE(),
                NOW()
            """
        )

        banco, data_servidor = cursor.fetchone()

        print("[BANCO] Conexão realizada com sucesso.")
        print(f"[BANCO] Banco conectado: {banco}")
        print(f"[BANCO] Data do servidor: {data_servidor}")

        return True

    except Error as erro:
        print(f"[BANCO] Erro durante o teste: {erro}")
        return False

    finally:
        if cursor is not None:
            cursor.close()

        if conexao.is_connected():
            conexao.close()