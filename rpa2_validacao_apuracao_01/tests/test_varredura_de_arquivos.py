"""Descoberta dos arquivos do mês, na árvore de pastas das operadoras.

É a primeira coisa que o RPA 2 faz, e a mais silenciosa quando dá errado: se a
raiz apontar para o lugar errado, ele registra "nenhum arquivo encontrado" e
termina com sucesso. Foi exatamente o que o `Path("")` → `Path(".")` causava,
corrigido em 2026-08-04.

A estrutura é ``{operadora}/{ano}/{aaaamm}/Detrafs Recebidos``, e os dois lados
(RPA 1 grava, RPA 2 lê) usam a mesma constante para não divergirem.
"""

from pathlib import Path

import pytest

from comum.config import configuration
from src.services.batimento_detraf import BatimentoDetrafService
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


class TestRaizNaoConfigurada:
    """
    `Path("")` vira `Path(".")`, e o diretório atual **existe e é um diretório** —
    então a guarda `exists()`/`is_dir()` passava e o robô varria o CWD.
    """

    def test_expectativa_none_acusa_a_variavel(self, monkeypatch):
        import src.services.validacao_detrafs as vd

        monkeypatch.setattr(vd, "CAMINHO_EXPECTATIVA_DETRAF", None)

        with pytest.raises(FileNotFoundError, match="CAMINHO_EXPECTATIVA_DETRAF"):
            ValidacaoDetrafsService()._preparar_arquivos_expectativa()

    def test_expectativa_none_tambem_no_batimento(self, monkeypatch):
        """A mesma guarda existe nos dois módulos — as duas precisam valer."""
        import src.services.batimento_detraf as bd

        monkeypatch.setattr(bd, "CAMINHO_EXPECTATIVA_DETRAF", None)

        with pytest.raises(FileNotFoundError, match="CAMINHO_EXPECTATIVA_DETRAF"):
            BatimentoDetrafService()._preparar_arquivos_expectativa()

    def test_raiz_apontando_para_lugar_inexistente_e_erro(self, monkeypatch, tmp_path):
        import src.services.validacao_detrafs as vd

        monkeypatch.setattr(
            vd, "CAMINHO_EXPECTATIVA_DETRAF", tmp_path / "nao_existe"
        )

        with pytest.raises(FileNotFoundError):
            ValidacaoDetrafsService()._preparar_arquivos_expectativa()


class TestVarreduraDosDetrafs:
    @pytest.fixture()
    def raiz(self, tmp_path, monkeypatch):
        import src.services.validacao_detrafs as vd

        raiz = tmp_path / "Operadoras"
        raiz.mkdir()
        monkeypatch.setattr(vd, "CAMINHO_DETRAF_RECEBIDO", raiz)
        return raiz

    def test_encontra_o_arquivo_na_subpasta_correta(self, raiz):
        esperado = _criar_detraf(raiz, "CLARO", "DETRAF_CLARO_202507.csv")

        encontrados = ValidacaoDetrafsService()._preparar_arquivos_detrafs()

        assert encontrados == [esperado]

    def test_arquivo_fora_da_subpasta_nao_conta(self, raiz):
        """
        A subpasta `Detrafs Recebidos` é exigida pela V2 (HU-03) e é onde o RPA 1
        grava. Um arquivo solto na pasta do mês não é entrada válida.
        """
        solta = raiz / "CLARO" / _ANO / _ANO_MES
        solta.mkdir(parents=True)
        (solta / "DETRAF.csv").write_text("x", encoding="utf-8")

        assert ValidacaoDetrafsService()._preparar_arquivos_detrafs() == []

    def test_operadora_sem_o_mes_e_registrada_como_sem_detraf(self, raiz):
        (raiz / "ALGAR" / "2025" / "202506").mkdir(parents=True)

        servico = ValidacaoDetrafsService()
        servico._preparar_arquivos_detrafs()

        assert "ALGAR" in servico.operadoras_sem_detraf

    def test_extensao_nao_permitida_e_ignorada(self, raiz):
        pasta = (
            raiz / "CLARO" / _ANO / _ANO_MES / configuration.SUBPASTA_DETRAFS_RECEBIDOS
        )
        pasta.mkdir(parents=True)
        (pasta / "carta.pdf").write_text("x", encoding="utf-8")

        assert ValidacaoDetrafsService()._preparar_arquivos_detrafs() == []

    def test_raiz_vazia_devolve_lista_vazia_sem_erro(self, raiz):
        """Um mês sem nenhuma operadora é estado possível."""
        assert ValidacaoDetrafsService()._preparar_arquivos_detrafs() == []

    def test_varre_todas_as_operadoras(self, raiz):
        _criar_detraf(raiz, "CLARO", "DETRAF_CLARO.csv")
        _criar_detraf(raiz, "ALGAR", "DETRAF_ALGAR.csv")

        encontrados = ValidacaoDetrafsService()._preparar_arquivos_detrafs()

        # parents: [0] Detrafs Recebidos, [1] 202507, [2] 2025, [3] operadora
        assert {caminho.parents[3].name for caminho in encontrados} == {
            "CLARO",
            "ALGAR",
        }


class TestMapeamentoPorOperadora:
    """
    O agrupamento é pelo **conteúdo**: a EOT credora da 1ª coluna, buscada no
    Anexo 5 — como a V2 define (*"O nome correto da operadora é pela EOT da
    credora presente no anexo 5"*), e não pelo nome da pasta nem pelo remetente.
    """

    @pytest.fixture()
    def batimento(self) -> BatimentoDetrafService:
        return BatimentoDetrafService()

    def test_agrupa_pelo_eot_credora(self, batimento, tmp_path):
        caminho = tmp_path / "qualquer_nome.csv"
        caminho.write_text(";".join(LINHA_VALIDA) + "\n", encoding="utf-8")

        mapa = batimento._mapear_arquivos_por_operadora([caminho])

        assert "CLARO" in mapa

    def test_arquivo_de_zero_byte_vai_para_nao_identificada(
        self, batimento, tmp_path, caplog
    ):
        """
        ⚠️ O docstring do método diz *"Arquivos vazios são ignorados"*, mas isso
        só vale para o arquivo que **abre** e resulta num DataFrame vazio (só
        cabeçalho, por exemplo). Um arquivo de 0 byte não abre: `carregar_dados`
        levanta "No columns to parse from file", o `except` captura e o arquivo
        cai em `OPERADORA_NAO_IDENTIFICADA`.

        O teste fixa o comportamento **real**, que por sinal é o melhor dos dois:
        ignorar em silêncio faria o arquivo sumir sem ninguém saber.
        """
        caminho = tmp_path / "vazio.csv"
        caminho.write_text("", encoding="utf-8")

        with caplog.at_level("ERROR"):
            mapa = batimento._mapear_arquivos_por_operadora([caminho])

        assert list(mapa) == ["OPERADORA_NAO_IDENTIFICADA"]
        assert "vazio.csv" in caplog.text

    def test_eot_desconhecida_vai_para_nao_identificada(self, batimento, tmp_path):
        """
        Não some nem é descartado: fica num grupo próprio, para alguém olhar. É
        a única exceção que a V2 trata na identificação da operadora.
        """
        linha = list(LINHA_VALIDA)
        linha[0] = "999"
        caminho = tmp_path / "desconhecida.csv"
        caminho.write_text(";".join(linha) + "\n", encoding="utf-8")

        mapa = batimento._mapear_arquivos_por_operadora([caminho])

        assert "OPERADORA_NAO_IDENTIFICADA" in mapa


class TestPastaDeExpectativaSemArquivo:
    """
    Q21, decidida em 2026-08-05 — a pasta vazia deixa de passar batido.

    Sem expectativa Vivo não há com o que comparar: a variação sai como 100% e a
    operadora inteira é contestada indevidamente. Até esta decisão o
    `if pasta.exists()` não tinha `else` — a pasta ausente era ignorada em
    silêncio.

    **Não aborta**: uma pasta vazia pode ser legítima (operadora sem tráfego no
    mês), e abortar faria uma pasta bloquear a apuração inteira.
    """

    @pytest.fixture()
    def raiz_expectativa(self, tmp_path, monkeypatch):
        import src.services.validacao_detrafs as vd

        raiz = tmp_path / "Expectativa"
        raiz.mkdir()
        monkeypatch.setattr(vd, "CAMINHO_EXPECTATIVA_DETRAF", raiz)
        monkeypatch.setattr(vd, "PASTAS_EXPECTATIVAS", ["VIVO SP"])
        # O `.env` de teste não define substrings; sem elas nada seria válido e
        # o caso positivo não distinguiria "pasta vazia" de "filtro vazio".
        monkeypatch.setattr(vd, "EXPECTATIVA_SUBSTRING", ["_D_"])
        return raiz

    def test_pasta_inexistente_e_acusada_pelo_nome(self, raiz_expectativa, caplog):
        with caplog.at_level("ERROR"):
            arquivos = ValidacaoDetrafsService()._preparar_arquivos_expectativa()

        assert arquivos == [], "não havia nada para encontrar"
        assert "Q21" in caplog.text
        assert "VIVO SP" in caplog.text
        assert "não existe" in caplog.text

    def test_pasta_existente_mas_sem_arquivo_valido_tambem_acusa(
        self, raiz_expectativa, caplog
    ):
        pasta = raiz_expectativa / "VIVO SP"
        pasta.mkdir()
        (pasta / "leia-me.txt").write_text("nada aqui", encoding="utf-8")

        with caplog.at_level("ERROR"):
            arquivos = ValidacaoDetrafsService()._preparar_arquivos_expectativa()

        assert arquivos == []
        assert "Q21" in caplog.text
        assert "VIVO SP" in caplog.text
        assert "nenhum" in caplog.text

    def test_o_batimento_acusa_do_mesmo_jeito(self, tmp_path, monkeypatch, caplog):
        """As duas varreduras têm filtros diferentes, mas o mesmo ponto cego."""
        import src.services.batimento_detraf as bd

        raiz = tmp_path / "Expectativa"
        raiz.mkdir()
        monkeypatch.setattr(bd, "CAMINHO_EXPECTATIVA_DETRAF", raiz)
        monkeypatch.setattr(bd, "PASTAS_EXPECTATIVAS", ["VIVO SP"])

        with caplog.at_level("ERROR"):
            BatimentoDetrafService()._preparar_arquivos_expectativa()

        assert "Q21" in caplog.text and "VIVO SP" in caplog.text

    def test_pasta_com_arquivo_valido_nao_acusa(self, raiz_expectativa, caplog):
        pasta = raiz_expectativa / "VIVO SP"
        pasta.mkdir()
        nome = f"DE_D_TBRA_VIVO_{_ANO_MES}.csv"
        (pasta / nome).write_text(";".join(LINHA_VALIDA) + "\n", encoding="utf-8")

        with caplog.at_level("ERROR"):
            ValidacaoDetrafsService()._preparar_arquivos_expectativa()

        assert "Q21" not in caplog.text


class TestDiagnosticoDaRecusa:
    """
    O motivo da recusa passa a ficar ao lado do arquivo (2026-08-06).

    O diagnóstico do layout já era bom — posição, esperado, encontrado,
    proporção de válidos. O problema era **onde** ele ficava: só no log do dia,
    misturado a tudo o mais. Numa homologação manual, responder "por que este
    arquivo foi recusado?" exigia abrir o `.log` e caçar pelo nome.
    """

    from comum.dominio.layout_detraf import validar_layout as _validar
    from comum.arquivos.recusa import registrar_recusa as _registrar

    def _recusar(self, tmp_path, conteudo: str):
        import pandas as pd

        arquivo = tmp_path / "DETRAF_D_CLARO_202507.csv"
        arquivo.write_text(conteudo, encoding="utf-8")
        df = pd.DataFrame([linha.split(";") for linha in conteudo.strip().splitlines()])
        return arquivo, type(self)._validar(df), df

    def test_grava_o_motivo_ao_lado_do_arquivo(self, tmp_path):
        arquivo, resultado, df = self._recusar(tmp_path, "a;b;c\nd;e;f\n")

        destino = type(self)._registrar(arquivo, resultado, df)

        assert destino is not None and destino.is_file()
        assert destino.parent == arquivo.parent, "fica junto do arquivo, não numa pasta à parte"
        assert arquivo.stem in destino.name

    def test_o_diagnostico_traz_as_linhas_do_arquivo(self, tmp_path):
        """É o que permite reconhecer o layout sem abrir mais nada."""
        arquivo, resultado, df = self._recusar(tmp_path, "a;b;c\nd;e;f\n")

        texto = type(self)._registrar(arquivo, resultado, df).read_text(encoding="utf-8")

        assert "a;b;c" in texto
        assert "3" in texto, "o número de colunas encontradas"

    def test_o_diagnostico_cita_a_n3_para_a_expectativa(self, tmp_path):
        """
        Um arquivo de expectativa recusado quase sempre é a N3 — contradição
        entre a V2 e o arquivo real, não defeito do robô. Quem homologa precisa
        saber disso sem ter que perguntar.
        """
        arquivo, resultado, df = self._recusar(tmp_path, "a;b;c\nd;e;f\n")

        texto = type(self)._registrar(arquivo, resultado, df).read_text(encoding="utf-8")

        assert "N3" in texto

    def test_falha_ao_gravar_nao_derruba_a_validacao(self, tmp_path, monkeypatch):
        """
        Perder o diagnóstico é menos grave do que parar a apuração do mês por
        falta de permissão numa pasta.
        """
        from pathlib import Path

        arquivo, resultado, df = self._recusar(tmp_path, "a;b;c\n")

        def _recusar_escrita(self, *args, **kwargs):
            raise PermissionError("pasta somente leitura")

        monkeypatch.setattr(Path, "write_text", _recusar_escrita)

        assert type(self)._registrar(arquivo, resultado, df) is None
