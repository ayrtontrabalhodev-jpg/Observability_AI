"""O sufixo vai para o disco de origem, e só nos arquivos da Vivo.

🔴 Pontos 1.2 e 2.1/2.2 do e-mail da Luciana de 29/09/2026 — os dois lados da
mesma moeda:

    1.2  "O RPA não pode promover nenhuma alteração nos arquivos recebidos nos
          e-mails. Exemplo: expectativa-telefonica-brasil-smp-c-vc1-202607_ERRO.xlsx"

    2.2  "Arquivo na pasta 33 sem o _ERRO e no banco de dados com. O nome do
          arquivo deve seguir o nome do banco." (CITTA_TELECOM, TELECALL)

Um pede para NÃO tocar; o outro pede para renomear. A diferença é a origem do
arquivo, e é o próprio e-mail que faz o corte: o grupo 1 é "arquivos recebidos
nos e-mails", o grupo 2 é "arquivos retirados da base da Vivo".

Corrigir um sem o outro faria o banco divergir do disco na direção oposta.
"""

from pathlib import Path

import pytest

from comum.arquivos.gerenciador import renomear_arquivo_com_sufixo


class TestNaoRepeteOSufixo:
    """
    🔴 Enquanto só a cópia de trabalho era renomeada, repetir não acontecia —
    a cópia nasce nova a cada execução. Com o insumo sendo renomeado também, a
    segunda execução acharia `X_EXP.txt` e produziria `X_EXP_EXP.txt`.
    """

    def test_arquivo_ja_com_sufixo_fica_como_esta(self, tmp_path: Path):
        arquivo = tmp_path / "expectativa_EXP.txt"
        arquivo.write_text("x", encoding="utf-8")

        assert renomear_arquivo_com_sufixo(arquivo, "_EXP") == arquivo
        assert arquivo.is_file()
        assert not (tmp_path / "expectativa_EXP_EXP.txt").exists()

    def test_tres_execucoes_seguidas_nao_acumulam(self, tmp_path: Path):
        arquivo = tmp_path / "expectativa.txt"
        arquivo.write_text("x", encoding="utf-8")

        atual = arquivo
        for _ in range(3):
            atual = renomear_arquivo_com_sufixo(atual, "_EXP")

        assert atual.name == "expectativa_EXP.txt"
        assert [p.name for p in tmp_path.iterdir()] == ["expectativa_EXP.txt"]

    def test_sufixo_diferente_ainda_e_acrescentado(self, tmp_path: Path):
        """A guarda é sobre o MESMO sufixo, não sobre qualquer um."""
        arquivo = tmp_path / "expectativa_EXP.txt"
        arquivo.write_text("x", encoding="utf-8")

        assert renomear_arquivo_com_sufixo(arquivo, "_BK").name == (
            "expectativa_EXP_BK.txt"
        )

    def test_arquivo_inexistente_continua_levantando(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            renomear_arquivo_com_sufixo(tmp_path / "nao_existe.txt", "_EXP")


class TestACopiaEAOrigemSaoRenomeadas:
    """O que fecha o 2.2: disco e banco passam a dizer a mesma coisa."""

    def test_as_duas_pontas_recebem_o_sufixo(self, tmp_path: Path):
        from src.services.validacao_detrafs import ValidacaoDetrafsService

        origem = tmp_path / "origem"
        trabalho = tmp_path / "trabalho"
        origem.mkdir()
        trabalho.mkdir()

        arquivo_origem = origem / "EXPECTATIVA_D.txt"
        arquivo_copia = trabalho / "EXPECTATIVA_D.txt"
        arquivo_origem.write_text("x", encoding="utf-8")
        arquivo_copia.write_text("x", encoding="utf-8")

        class _AreaFalsa:
            def origem_de(self, copia):
                return arquivo_origem if copia == arquivo_copia else copia

        servico = ValidacaoDetrafsService.__new__(ValidacaoDetrafsService)
        servico.area = _AreaFalsa()

        servico.renomear_arquivos_processados(
            arquivos_validos={arquivo_copia}, arquivos_invalidos=set()
        )

        assert (trabalho / "EXPECTATIVA_D_EXP.txt").is_file()
        assert (origem / "EXPECTATIVA_D_EXP.txt").is_file()
        assert not arquivo_origem.exists()

    def test_origem_ausente_nao_derruba_a_execucao(self, tmp_path: Path):
        """
        O insumo mora na rede e pode sumir entre a cópia e o fim da etapa.
        Perder o sufixo é ruim; perder a apuração inteira é pior.
        """
        from src.services.validacao_detrafs import ValidacaoDetrafsService

        copia = tmp_path / "EXPECTATIVA_D.txt"
        copia.write_text("x", encoding="utf-8")
        sumida = tmp_path / "rede" / "EXPECTATIVA_D.txt"

        class _AreaFalsa:
            def origem_de(self, _):
                return sumida

        servico = ValidacaoDetrafsService.__new__(ValidacaoDetrafsService)
        servico.area = _AreaFalsa()

        servico.renomear_arquivos_processados(
            arquivos_validos={copia}, arquivos_invalidos=set()
        )

        assert (tmp_path / "EXPECTATIVA_D_EXP.txt").is_file()
