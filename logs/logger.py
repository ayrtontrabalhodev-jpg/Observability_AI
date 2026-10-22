import csv
import threading
from datetime import datetime
from pathlib import Path

from config.config import pasta_historico


# ==================================================
# CAMINHOS
# ==================================================

# Raiz do projeto:
# Observability_AI/
diretorio_raiz = Path(__file__).resolve().parent.parent

# Pasta configurada para o histórico atual
diretorio_historico = diretorio_raiz / "logs" / pasta_historico

# Arquivo de controle das execuções
ARQUIVO_LOG_EXECUCAO = diretorio_historico / "log_execucao.csv"

# Evita duas gravações simultâneas dentro
# da mesma execução do programa
BLOQUEIO_LOG = threading.Lock()

# Colunas do arquivo
COLUNAS_LOG = [
    "id",
    "nome",
    "descricao",
    "status",
    "data_log",
]

# Garante que a pasta exista
diretorio_historico.mkdir(parents=True, exist_ok=True)


# ==================================================
# CONTROLE DO ID
# ==================================================

def buscar_proximo_id():
    """
    Retorna o próximo ID disponível no
    arquivo log_execucao.csv.

    Se o arquivo não existir ou estiver vazio,
    retorna 1.
    """

    if not ARQUIVO_LOG_EXECUCAO.exists():
        return 1

    if ARQUIVO_LOG_EXECUCAO.stat().st_size == 0:
        return 1

    ultimo_id = 0

    try:
        with open(
            ARQUIVO_LOG_EXECUCAO,
            mode="r",
            encoding="utf-8-sig",
            newline="",
        ) as arquivo:

            leitor = csv.DictReader(
                arquivo,
                delimiter=";",
            )

            for linha in leitor:
                try:
                    id_atual = int(linha.get("id", 0))

                    if id_atual > ultimo_id:
                        ultimo_id = id_atual

                except (TypeError, ValueError):
                    continue

    except OSError as erro:
        print(f"[LOGGER] Erro ao ler o arquivo: {erro}")
        return 1

    return ultimo_id + 1


# ==================================================
# REGISTRO DA EXECUÇÃO
# ==================================================

def registrar_log(nome, descricao, status):
    """
    Registra uma nova linha no log_execucao.csv.

    Toda execução do app_coleta deve registrar
    uma linha, independentemente de:

    - encontrar registros novos;
    - não encontrar registros novos;
    - ocorrer erro;
    - criar ou não criar arquivos semanais.

    Status permitidos:
        Sucesso
        Erro
    """

    status_formatado = str(status).strip().capitalize()

    if status_formatado not in {"Sucesso", "Erro"}:
        raise ValueError(
            "O status do log deve ser 'Sucesso' ou 'Erro'."
        )

    nome_formatado = str(nome).strip()
    descricao_formatada = str(descricao).strip()

    if not nome_formatado:
        raise ValueError(
            "O nome do processo não pode ficar vazio."
        )

    if not descricao_formatada:
        descricao_formatada = "Execução registrada sem descrição."

    diretorio_historico.mkdir(parents=True, exist_ok=True)

    with BLOQUEIO_LOG:
        arquivo_existe = (
            ARQUIVO_LOG_EXECUCAO.exists()
            and ARQUIVO_LOG_EXECUCAO.stat().st_size > 0
        )

        registro = {
            "id": buscar_proximo_id(),
            "nome": nome_formatado,
            "descricao": descricao_formatada,
            "status": status_formatado,
            "data_log": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }

        try:
            with open(
                ARQUIVO_LOG_EXECUCAO,
                mode="a",
                encoding="utf-8-sig",
                newline="",
            ) as arquivo:

                escritor = csv.DictWriter(
                    arquivo,
                    fieldnames=COLUNAS_LOG,
                    delimiter=";",
                    extrasaction="ignore",
                )

                if not arquivo_existe:
                    escritor.writeheader()

                escritor.writerow(registro)

        except OSError as erro:
            raise OSError(
                "Não foi possível registrar a execução "
                f"em {ARQUIVO_LOG_EXECUCAO}: {erro}"
            ) from erro

    print(
        f"[LOGGER] ID {registro['id']} | "
        f"{status_formatado} | {nome_formatado}"
    )

    return registro