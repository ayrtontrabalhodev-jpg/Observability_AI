from src.services.captacao_expectativa import CaptacaoExpectativaService


class CaptacaoExpectativaController:
    def __init__(self, de_pasta=None):
        self.service = CaptacaoExpectativaService(de_pasta=de_pasta)

    def captar_expectativa(self, referencia: str | None = None) -> list[str]:
        """
        Traz a expectativa do período e devolve o resumo do que aconteceu.

        O retorno existe para a parada entre etapas, como nos outros dois
        controllers do RPA 2.
        """
        resultado = self.service.executar(referencia=referencia)
        return resultado.resumo()
