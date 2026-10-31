import time
from datetime import datetime, timedelta

from Banco_de_Dados.conexao import testar_conexao
from Banco_de_Dados.extracao import (
    extrair_todos_os_processos,
    salvar_base_local,
    validar_base_local,
)
from config.config import (
    intervalo_coleta_minutos,
)


class process_handle:

    def executar(self):
        """
        Executa continuamente o projeto.
        """

        print("\n================================")
        print("OBSERVABILITY AI")
        print("================================")

        try:
            while True:
                self.parte_1_coleta_dados()

                proxima_coleta = (
                    datetime.now()
                    + timedelta(
                        minutes=(
                            intervalo_coleta_minutos
                        )
                    )
                )

                print(
                    "\n[PROCESSO] Próxima coleta: "
                    f"{proxima_coleta:%d/%m/%Y %H:%M:%S}"
                )

                time.sleep(
                    intervalo_coleta_minutos * 60
                )

        except KeyboardInterrupt:
            print(
                "\n[PROCESSO] Coleta encerrada "
                "pelo usuário."
            )

    def parte_1_coleta_dados(self):
        """
        Testa a conexão, extrai os dados,
        salva e valida os arquivos.
        """

        print("\n================================")
        print(
            f"INÍCIO DA COLETA: "
            f"{datetime.now():%d/%m/%Y %H:%M:%S}"
        )
        print("================================")

        # Parte 1: conexão
        if not testar_conexao():
            print(
                "[PROCESSO] Coleta cancelada "
                "por falha na conexão."
            )

            return

        # Parte 2: extração
        bases_extraidas = (
            extrair_todos_os_processos()
        )

        # Parte 3: armazenamento semanal
        salvar_base_local(
            bases_extraidas
        )

        # Parte 4: validação
        validar_base_local()

        print(
            f"\n[FIM DA COLETA] "
            f"{datetime.now():%d/%m/%Y %H:%M:%S}"
        )