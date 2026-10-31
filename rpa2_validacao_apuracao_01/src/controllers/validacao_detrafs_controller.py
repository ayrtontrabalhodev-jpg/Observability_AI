from src.services.validacao_detrafs import ValidacaoDetrafsService


class ValidacaoDetrafsController:
    def __init__(self):
        self.service = ValidacaoDetrafsService()

    def validar_detrafs(self) -> list[str]:
        """
        Executa a validação e devolve o resumo do que aconteceu.

        O retorno existe para a parada entre etapas: sem ele, o
        `process_handle` teria que recontar o que o serviço já contou.
        """
        self.service.executar()
        return self.service.resumo
