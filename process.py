import time
from datetime import datetime, timedelta

from banco_de_dados.conexao import testar_conexao
from banco_de_dados.extracao import extrair_todas_as_tabelas
from config.config import intervalo_coleta_minutos
from logs.logger import registrar_log


# primeiro commit e e e 
class process_handle:

    def executar(self):
        """
        Executa a coleta imediatamente e repete
        no intervalo configurado.
        """

        print("\n========================================")
        print("OBSERVABILITY AI - COLETA RIFAINA")
        print("========================================")

        try:
            while True:
                self.executar_coleta()

                proxima_execucao = (
                    datetime.now()
                    + timedelta(
                        minutes=intervalo_coleta_minutos
                    )
                )

                print(
                    f"\n[PROCESSO] Próxima coleta: "
                    f"{proxima_execucao:%d/%m/%Y %H:%M:%S}"
                )

                time.sleep(
                    intervalo_coleta_minutos * 60
                )

        except KeyboardInterrupt:
            print(
                "\n[PROCESSO] Coleta encerrada "
                "manualmente."
            )

    def executar_coleta(self):
        """
        Executa um ciclo completo de coleta.
        """

        inicio = datetime.now()
        status_execucao = "Sucesso"
        descricao = "Execução iniciada."

        try:
            if not testar_conexao():
                status_execucao = "Erro"
                descricao = (
                    "Não foi possível conectar "
                    "ao banco de dados."
                )
                return

            resumo = extrair_todas_as_tabelas()

            if resumo["total_erros"] > 0:
                status_execucao = "Erro"

            detalhes = []

            for item in resumo["resultados"]:
                detalhes.append(
                    f"{item['tabela']}: "
                    f"{item['resultado']} "
                    f"({item['quantidade']} registro(s))"
                )

            descricao = (
                f"Tabelas processadas: "
                f"{resumo['total_tabelas']}. "
                f"Registros processados: "
                f"{resumo['total_registros']}. "
                + " | ".join(detalhes)
            )

            print(f"[PROCESSO] {descricao}")

        except Exception as erro:
            status_execucao = "Erro"
            descricao = (
                f"Erro não tratado: "
                f"{type(erro).__name__}: {erro}"
            )

            print(f"[PROCESSO] {descricao}")

        finally:
            duracao = (
                datetime.now() - inicio
            ).total_seconds()

            registrar_log(
                nome="Coleta histórico RIFAINA",
                descricao=(
                    f"{descricao} "
                    f"Duração: {duracao:.2f} segundo(s)."
                ),
                status=status_execucao,
            )