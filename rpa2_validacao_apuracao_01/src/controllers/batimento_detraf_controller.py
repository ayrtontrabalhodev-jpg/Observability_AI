from src.services.batimento_detraf import BatimentoDetrafService


class BatimentoDetrafController:
    def __init__(self):
        self.service = BatimentoDetrafService()

    def batimento_detraf(self) -> list[str]:
        """Executa o batimento e devolve o resumo, para a parada entre etapas."""
        self.service.executar()
        return self.service.resumo
