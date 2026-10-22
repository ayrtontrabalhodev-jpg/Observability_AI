from src.services.classificacao_falhas import classificar_falhas_rifaina
from src.services.monitoramento_alertas import monitorar_e_enviar_alertas
from src.services.preparacao_treinamento import preparar_base_treinamento
from src.services.tratamento_dados import tratar_dados_rifaina
from src.services.treinamento_modelo import treinar_modelo_rifaina


class process_handle:

    def executar(self):
        """
        Executa o fluxo completo do Observability AI:

        1. Trata os logs;
        2. Classifica as falhas;
        3. Prepara a base de treinamento;
        4. Treina e avalia o modelo;
        5. Monitora os erros e envia alertas.
        """

        print("\n========================================")
        print("OBSERVABILITY AI - APP PRINCIPAL")
        print("========================================")

        try:
            # =====================================
            # PARTE 1: TRATAMENTO
            # =====================================

            base_tratada = self.processo_tratar_dados()

            if base_tratada is None or base_tratada.empty:
                print("[PROCESSO] Nenhum dado disponível.")
                return

            # =====================================
            # PARTE 2: CLASSIFICAÇÃO
            # =====================================

            base_classificada = self.processo_classificar_falhas()

            if base_classificada is None or base_classificada.empty:
                print("[PROCESSO] Nenhuma classificação disponível.")
                return

            # =====================================
            # PARTE 3: BASE DE TREINAMENTO
            # =====================================

            base_treinamento = self.processo_preparar_treinamento()

            if base_treinamento is None or base_treinamento.empty:
                print("[PROCESSO] Nenhum registro apto para treinamento.")
                return

            # =====================================
            # PARTE 4: TREINAMENTO DO MODELO
            # =====================================

            resultado_modelo = self.processo_treinar_modelo()

            if resultado_modelo is None:
                print("[PROCESSO] O modelo não foi treinado.")
                return

            metricas = resultado_modelo["metricas"]

            # =====================================
            # PARTE 5: ALERTAS
            # =====================================

            resumo_alertas = self.processo_monitorar_alertas()

            print("\n========================================")
            print("PROCESSAMENTO CONCLUÍDO")
            print("========================================")

            print(
                f"Registros de treinamento: "
                f"{len(base_treinamento)}"
            )

            print(
                f"Acurácia de teste: "
                f"{metricas['acuracia']:.2%}"
            )

            print(
                f"F1 macro: "
                f"{metricas['f1_macro']:.2%}"
            )

            print(
                f"Erros encontrados: "
                f"{resumo_alertas['erros_encontrados']}"
            )

            print(
                f"Alertas enviados: "
                f"{resumo_alertas['alertas_enviados']}"
            )

            print(
                f"Erros no envio dos alertas: "
                f"{resumo_alertas['alertas_com_erro']}"
            )

            print("========================================")

        except KeyboardInterrupt:
            print("\n[PROCESSO] Execução interrompida manualmente.")

        except Exception as erro:
            print(
                "\n[PROCESSO] Erro durante o processamento: "
                f"{type(erro).__name__}: {erro}"
            )

    def processo_tratar_dados(self):
        """
        Consolida e trata os logs do RIFAINA.
        """

        print("\n===== PARTE 1: TRATAMENTO DOS DADOS =====")
        return tratar_dados_rifaina()

    def processo_classificar_falhas(self):
        """
        Classifica os padrões encontrados.
        """

        print("\n===== PARTE 2: CLASSIFICAÇÃO DAS FALHAS =====")
        return classificar_falhas_rifaina()

    def processo_preparar_treinamento(self):
        """
        Prepara os registros aptos para treinamento.
        """

        print("\n===== PARTE 3: BASE DE TREINAMENTO =====")
        return preparar_base_treinamento()

    def processo_treinar_modelo(self):
        """
        Treina e avalia o modelo.
        """

        print("\n===== PARTE 4: TREINAMENTO DO MODELO =====")
        return treinar_modelo_rifaina()

    def processo_monitorar_alertas(self):
        """
        Localiza erros ainda não alertados e
        envia os e-mails automaticamente.
        """

        print("\n===== PARTE 5: MONITORAMENTO DE ALERTAS =====")
        return monitorar_e_enviar_alertas()