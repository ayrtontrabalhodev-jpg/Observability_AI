"""Configuração da suíte do RPA 2.

Esta suíte **não existia**: os Projetos 2 e 3, que compõem este robô, vieram sem
nenhum teste, e é aqui que estão as regras mais densas da V2 — as 15 colunas uma
a uma, a tarifa ("não existe tarifa zero"), o `_ERRO`, a regra de 1%. Era a maior
dívida da unificação.

Como nas demais suítes: as variáveis de ambiente são definidas em nível de módulo,
**antes** de qualquer `import src...`, porque `RepositorioCache` é singleton e
resolve o banco no primeiro uso.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

_RAIZ_RPA = Path(__file__).resolve().parents[1]
_RAIZ_UNIFICADO = _RAIZ_RPA.parent

for _caminho in (str(_RAIZ_UNIFICADO), str(_RAIZ_RPA)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

from tests_apoio import LINHA_VALIDA, criar_banco_de_teste, linha, silenciar_diagnose_do_log

silenciar_diagnose_do_log()

# Ponte loguru -> caplog. Sem ela, um teste que afirma "isto foi registrado no
# log" passa em silêncio mesmo quando nada foi registrado.
from tests_apoio import loguru_para_caplog  # noqa: F401 — fixture autouse

# ---------------------------------------------------------------------------
# Ambiente determinístico, antes de qualquer import de `src`
# ---------------------------------------------------------------------------
_DIR_TEMP = Path(tempfile.mkdtemp(prefix="detraf_rpa2_teste_"))
#: Exposto para o teste que precisa mexer no seed em tempo de execução.
CAMINHO_DB = _DIR_TEMP / "TABELAS_DETRAF_TESTE.db"
_CAMINHO_DB = CAMINHO_DB

os.environ.setdefault("ENV", "dev")
# Referência fixa => ANO_MES_REFERENCIA = 202507 (mês anterior a 202508).
os.environ.setdefault("DEBUG_ANO_MES_ATUAL", "202508")
os.environ["CAMINHO_SQLITE"] = str(_CAMINHO_DB)


criar_banco_de_teste(_CAMINHO_DB)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def df_valido() -> pd.DataFrame:
    """DataFrame de uma linha, aprovada em todas as regras."""
    return pd.DataFrame([LINHA_VALIDA])


@pytest.fixture()
def df_com() -> callable:
    """Fábrica: ``df_com(gh="X")`` -> DataFrame de uma linha com aquele desvio."""

    def _construir(**alteracoes) -> pd.DataFrame:
        return pd.DataFrame([linha(**alteracoes)])

    return _construir


@pytest.fixture()
def repo_cache():
    """Instância limpa do cache apontando para o SQLite de teste."""
    from comum.dados.repositorio_cache import RepositorioCache

    RepositorioCache.resetar()
    cache = RepositorioCache()
    yield cache
    RepositorioCache.resetar()
