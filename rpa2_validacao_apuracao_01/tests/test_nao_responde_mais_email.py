"""O RPA 2 deixou de responder à operadora (2026-08-06).

Quem responde é o RPA 1, que valida o arquivo na captura e recusa antes de
salvar. O RPA 2 continua validando — virou rede de segurança —, mas não fala
mais com o Outlook.

Por que isto merece teste próprio, e não só a remoção do código: se alguém
reintroduzir a notificação aqui, **a operadora recebe dois e-mails** sobre o
mesmo arquivo, e o segundo chega dias depois do primeiro. É o tipo de regressão
que ninguém percebe olhando o log de um robô só.
"""

import ast
from pathlib import Path

import pytest

_RAIZ_RPA = Path(__file__).resolve().parents[1]


def _fontes_de_producao():
    for caminho in (_RAIZ_RPA / "src").rglob("*.py"):
        yield caminho


class TestNenhumaConversaComOOutlook:
    def test_nenhum_modulo_menciona_outlook(self):
        for caminho in _fontes_de_producao():
            texto = caminho.read_text(encoding="utf-8", errors="ignore").lower()
            assert "outlook" not in texto, f"{caminho.name} voltou a falar com o Outlook"
            assert "win32com" not in texto, caminho.name

    def test_o_modulo_de_notificacao_nao_existe_mais(self):
        assert not (_RAIZ_RPA / "src" / "services" / "notificacao_email.py").exists()

    def test_a_validacao_nao_tem_metodo_de_notificacao(self):
        arvore = ast.parse(
            (_RAIZ_RPA / "src" / "services" / "validacao_detrafs.py").read_text(
                encoding="utf-8"
            )
        )
        metodos = {
            no.name for no in ast.walk(arvore) if isinstance(no, ast.FunctionDef)
        }

        assert "_notificar_arquivos_invalidos" not in metodos


class TestARedeDeSegurancaContinua:
    """
    Continuar marcando `_ERRO` não é detalhe: é a única saída visível da rede de
    segurança. Sem ela, a rede fica silenciosa — e uma rede de segurança
    silenciosa não é rede de segurança.
    """

    def test_continua_renomeando_o_invalido_para_erro(self, tmp_path):
        from src.services.validacao_detrafs import ValidacaoDetrafsService

        invalido = tmp_path / "RUIM.csv"
        invalido.write_text("x", encoding="utf-8")

        # Deixou de ser `staticmethod` em 29/09/2026: agora consulta a área de
        # trabalho para renomear também o arquivo de ORIGEM (ponto 2.2 da
        # Luciana). Aqui não há origem separada — a área devolve o próprio
        # caminho, e só a cópia é renomeada, que é o que este teste vigia.
        class _AreaSemOrigem:
            def origem_de(self, caminho):
                return caminho

        servico = ValidacaoDetrafsService.__new__(ValidacaoDetrafsService)
        servico.area = _AreaSemOrigem()

        servico.renomear_arquivos_processados(
            arquivos_validos=set(), arquivos_invalidos={invalido}
        )

        assert (tmp_path / "RUIM_ERRO.csv").is_file()

    def test_a_reprovacao_e_registrada_como_anomalia(self):
        """
        Nível `error`, não `warning`. Nada reprovado deveria chegar até aqui: o
        RPA 1 valida antes de salvar. Um `_ERRO` no RPA 2 significa que o portão
        falhou, ou que alguém pôs o arquivo na pasta à mão — e nos dois casos
        alguém precisa olhar.
        """
        fonte = (_RAIZ_RPA / "src" / "services" / "validacao_detrafs.py").read_text(
            encoding="utf-8"
        )
        # Pelas 300 posições anteriores à mensagem, e não pelo recuo exato: casar
        # a indentação faria este teste quebrar em toda reformatação, sem nada
        # ter mudado de fato.
        antes = fonte[: fonte.index("APÓS ter passado pelo portão")]

        assert "falhou em uma ou mais validações" in antes[-300:]
        assert "logger.error(" in antes[-300:], (
            "a reprovação no RPA 2 voltou a ser warning — ela é anomalia"
        )
