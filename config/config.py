import os


db_user = os.environ.get("YELLOW_USER_DB")
db_pass = os.environ.get("YELLOW_PASS_DB")


# Data oficial de início da coleta
data_inicio_projeto = "2026-10-06"


# Tempo entre as coletas
intervalo_coleta_minutos = 5


# Tabelas que serão monitoradas
tabelas = [
    "tbl_rpa_log_rifaina",
    "tbl_rpa_log_roaming_gestao_tarifas",
]