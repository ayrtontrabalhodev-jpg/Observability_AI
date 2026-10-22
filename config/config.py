import os


db_user = os.environ.get("YELLOW_USER_DB")
db_pass = os.environ.get("YELLOW_PASS_DB")


# Tabelas utilizadas no MVP.
# Novas tabelas padronizadas poderão ser adicionadas aqui.
tabelas_logs = [
    "tbl_rpa_log_rifaina",
]


# Nome da pasta do histórico do MVP
pasta_historico = "historico_rifaina"


# Intervalo da coleta automática
intervalo_coleta_minutos = 30


# Quantidade de meses carregados na primeira execução
meses_historico_inicial = 2