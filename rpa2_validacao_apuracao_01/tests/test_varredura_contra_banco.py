"""A varredura do RPA 2 cruza o histórico JSON com o banco (2026-09-24).

🔴 O que a Vivo achou (e-mail da Luciana, 23/09/2026): a tabela de log foi
limpa para refazer a massa de 202607, o JSON de histórico continuou dizendo "já
processado", e o RPA 2 regravou só 8 dos 73 Detrafs validados.

Agora um arquivo que o JSON conhece mas o banco não tem volta a ser processado.
Se o banco não responder, o filtro cai no comportamento antigo (só o JSON) e
avisa — a validação vai bater no banco logo depois e falhar com a mensagem certa.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from comum.arquivos.historico import ValidadorHistoricoRPA
from comum.config import configuration
from comum.dados import tabelas
from src.services.validacao_detrafs import ValidacaoDetrafsService

from conftest import LINHA_VALIDA

_ANO_MES = "202507"
_ANO = "2025"


def _criar_detraf(raiz: Path, operadora: str, nome: str) -> Path:
    pasta = raiz / operadora / _ANO / _ANO_MES / configuration.SUBPASTA_DETRAFS_RECEBIDOS
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_text(";".join(LINHA_VALIDA) + "\n", encoding="utf-8")
    return caminho


def _gravar_no_banco(nome: str, periodo: str = _ANO_MES) -> None:
    from comum.dados.repositorio_tabelas import bd_tabelas

    bd_tabelas.cache.inserir(
        tabelas.LOG_DESPESA_ARQUIVOS,
        pd.DataFrame([{
            "tipo_registro": "DETRAF",
            "nome_arquivo": nome,
            "periodo": periodo,
            "status": "Aceito",
        }]),
    )


@pytest.fixture()
def raiz(tmp_path, monkeypatch):
    import comum.arquivos.historico as modulo_historico
    import src.services.validacao_detrafs as vd

    raiz = tmp_path / "Operadoras"
    raiz.mkdir()
    monkeypatch.setattr(vd, "CAMINHO_DETRAF_RECEBIDO", raiz)

    # Histórico JSON num diretório só deste teste — o do ambiente é compartilhado
    # pela suíte inteira e um registro daqui vazaria para os outros.
    monkeypatch.setattr(modulo_historico, "DIRETORIO_HISTORICO_ARQUIVOS", str(tmp_path / "historico"))
    return raiz


class TestJsonContraBanco:
    def test_no_json_e_no_banco_e_pulado(self, raiz):
        """A proteção anti-reprocessamento continua valendo."""
        detraf = _criar_detraf(raiz, "CLARO", "VARR_BANCO_ambos.csv")
        ValidadorHistoricoRPA().registrar_arquivos([detraf], status_valido=True)
        _gravar_no_banco(detraf.name)

        assert ValidacaoDetrafsService()._preparar_arquivos_detrafs() == []

    def test_no_json_mas_fora_do_banco_e_processado_de_novo(self, raiz):
        """O caso da Vivo: tabela limpa, JSON intacto."""
        detraf = _criar_detraf(raiz, "CLARO", "VARR_BANCO_so_json.csv")
        ValidadorHistoricoRPA().registrar_arquivos([detraf], status_valido=True)

        assert ValidacaoDetrafsService()._preparar_arquivos_detrafs() == [detraf]

    def test_linha_de_outro_mes_nao_conta(self, raiz):
        """A consulta é por período: o mesmo nome em 202506 não segura 202507."""
        detraf = _criar_detraf(raiz, "CLARO", "VARR_BANCO_outro_mes.csv")
        ValidadorHistoricoRPA().registrar_arquivos([detraf], status_valido=True)
        _gravar_no_banco(detraf.name, periodo="202506")

        assert ValidacaoDetrafsService()._preparar_arquivos_detrafs() == [detraf]

    def test_banco_indisponivel_cai_no_json_e_avisa(self, raiz, monkeypatch, caplog):
        detraf = _criar_detraf(raiz, "CLARO", "VARR_BANCO_indisponivel.csv")
        ValidadorHistoricoRPA().registrar_arquivos([detraf], status_valido=True)

        servico = ValidacaoDetrafsService()

        def _estourar(*_args, **_kwargs):
            raise RuntimeError("banco fora")

        monkeypatch.setattr(
            servico.repositorio_tabelas, "nomes_arquivos_no_log_despesa", _estourar
        )

        assert servico._preparar_arquivos_detrafs() == []
        assert "só o histórico JSON" in caplog.text

    def test_consulta_ao_banco_e_uma_por_execucao(self, raiz, monkeypatch):
        """Detraf e expectativa passam pelo mesmo filtro; o banco é lido uma vez."""
        _criar_detraf(raiz, "CLARO", "VARR_BANCO_uma_vez.csv")
        servico = ValidacaoDetrafsService()
        chamadas = []

        def _contar(periodo, tipo_registro=None):
            chamadas.append(periodo)
            return set()

        monkeypatch.setattr(servico.repositorio_tabelas, "nomes_arquivos_no_log_despesa", _contar)

        servico._preparar_arquivos_detrafs()
        servico._preparar_arquivos_detrafs()

        assert chamadas == [_ANO_MES]
