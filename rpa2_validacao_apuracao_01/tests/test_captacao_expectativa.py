"""A captação da expectativa pelo SFTP — a parte que roda sem rede.

O transporte (`comum/integracoes/sftp.py`) não é testado aqui: ele é `paramiko`
com outro nome. O que se testa é a **regra** — qual arquivo entra, para qual
pasta vai, e que o robô não conecta quando o kill-switch está desligado.

O molde do `_SFTPProibido` veio de `rpa3/tests/test_upload_agi.py`: um dublê que
falha ao ser tocado prova o kill-switch melhor que um `assert` sobre um mock,
porque o objeto real nem chega a ser construído.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comum.config import configuration
from src.services import captacao_expectativa as ce
from src.services.captacao_expectativa import (
    CaptacaoExpectativaService,
    eh_detalhado_do_periodo,
)

PERIODO = "202603"


class _SFTPProibido:
    """Qualquer toque é falha — é o que prova que o robô não conectou."""

    def __getattr__(self, nome):
        def _explodir(*args, **kwargs):
            raise AssertionError(
                f"O SFTP foi acionado ('{nome}') com PERMITIR_DOWNLOAD_SFTP "
                f"desligado."
            )

        return _explodir


class _SFTPFalso:
    """Um SFTP de mentira: devolve nomes e 'baixa' escrevendo um arquivinho."""

    def __init__(self, por_pasta: dict[str, list[str]], falhar_em: set[str] | None = None):
        self.por_pasta = por_pasta
        self.falhar_em = falhar_em or set()
        self.conectou = False
        self.fechou = False
        self.baixados: list[str] = []

    def conectar(self):
        self.conectou = True

    def fechar(self):
        self.fechou = True

    def listar(self, caminho_remoto):
        if caminho_remoto in self.falhar_em:
            return []  # é o que o SFTPService faz: loga e devolve vazio
        return self.por_pasta.get(caminho_remoto, [])

    def baixar(self, caminho_remoto, destino):
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("conteudo\n", encoding="utf-8")
        self.baixados.append(caminho_remoto)
        return destino


@pytest.fixture
def destino(tmp_path, monkeypatch) -> Path:
    """
    Aponta `CAMINHO_EXPECTATIVA_DETRAF` para um diretório temporário.

    `PASTAS_EXPECTATIVAS` também é fixada aqui: sob pytest o `.env` não é lido
    por design, e ela vem vazia — mas o roteamento por nome depende dela.
    """
    raiz = tmp_path / "Expectativa"
    raiz.mkdir()
    monkeypatch.setattr(configuration, "CAMINHO_EXPECTATIVA_DETRAF", raiz)
    monkeypatch.setattr(
        configuration, "PASTAS_EXPECTATIVAS", ["Vivo", "TLF", "MVNO", "Detraf TRP"]
    )
    return raiz


class TestFiltroDeArquivo:
    """As três condições do filtro, que vieram do script de origem."""

    @pytest.mark.parametrize(
        "nome",
        [
            "DETRAF_FINAL_VIVO_202603_N_ALGAR_SMP_VIVO_D.csv",
            "QUALQUER_202603_D.txt",
            "minusculo_202603_d.csv",  # a comparação é em caixa alta
        ],
    )
    def test_aceita_o_detalhado_do_periodo(self, nome):
        assert eh_detalhado_do_periodo(nome, PERIODO) is True

    def test_recusa_outro_periodo(self):
        assert eh_detalhado_do_periodo("DETRAF_202602_VIVO_D.csv", PERIODO) is False

    def test_recusa_o_resumido(self):
        """`_L_` é o resumido; o robô quer o Detalhado."""
        assert eh_detalhado_do_periodo("DETRAF_202603_L_VIVO_D.csv", PERIODO) is False

    def test_recusa_quando_o_D_nao_esta_no_fim(self):
        """
        🔴 A regra é **sufixo**, não substring — mais estrita que o
        `EXPECTATIVA_SUBSTRING` do `.env`. Unificar as duas afrouxaria esta.
        """
        assert eh_detalhado_do_periodo("DETRAF_D_202603_VIVO.csv", PERIODO) is False

    def test_recusa_sem_o_D(self):
        assert eh_detalhado_do_periodo("DETRAF_202603_VIVO.csv", PERIODO) is False


class TestKillSwitch:
    def test_desligado_nao_conecta(self, destino, monkeypatch):
        """O que está atrás do interruptor é a rede e a credencial."""
        monkeypatch.setattr(configuration, "PERMITIR_DOWNLOAD_SFTP", False)
        monkeypatch.setattr(ce, "SFTPService", lambda **kwargs: _SFTPProibido())

        resultado = CaptacaoExpectativaService().executar(referencia=PERIODO)

        assert resultado.baixados == []
        assert "desligado" in resultado.origem

    def test_desligado_avisa_no_log(self, destino, monkeypatch, caplog):
        monkeypatch.setattr(configuration, "PERMITIR_DOWNLOAD_SFTP", False)

        CaptacaoExpectativaService().executar(referencia=PERIODO)

        assert "PERMITIR_DOWNLOAD_SFTP" in caplog.text

    def test_de_pasta_funciona_com_o_switch_desligado(self, destino, monkeypatch, tmp_path):
        """
        O `--de-pasta` é o modo de teste: não deve depender do kill-switch, que
        protege a **rede** — e aqui não há rede nenhuma.
        """
        monkeypatch.setattr(configuration, "PERMITIR_DOWNLOAD_SFTP", False)
        origem = tmp_path / "origem"
        origem.mkdir()
        (origem / f"DETRAF_{PERIODO}_VIVO_D.csv").write_text("x\n", encoding="utf-8")

        resultado = CaptacaoExpectativaService(de_pasta=origem).executar(
            referencia=PERIODO
        )

        assert resultado.baixados == [f"Vivo/DETRAF_{PERIODO}_VIVO_D.csv"]


class TestRoteamentoDePasta:
    def test_cada_origem_cai_na_subpasta_certa(self, destino):
        sftp = _SFTPFalso({
            "/interfaces/GERACAO_DETRAF_VIVO": [f"A_{PERIODO}_D.csv"],
            "/interfaces/GERACAO_DETRAF_TELEFONICA": [f"B_{PERIODO}_D.csv"],
            "/interfaces/MVNO/NEXTEL/DESMP": [f"C_{PERIODO}_D.csv"],
            "/interfaces/GERACAO_DETRAF_TRP": [f"D_{PERIODO}_D.csv"],
        })

        CaptacaoExpectativaService(sftp=sftp).executar(referencia=PERIODO)

        assert (destino / "Vivo" / f"A_{PERIODO}_D.csv").exists()
        assert (destino / "TLF" / f"B_{PERIODO}_D.csv").exists()
        assert (destino / "MVNO" / f"C_{PERIODO}_D.csv").exists()
        assert (destino / "Detraf TRP" / f"D_{PERIODO}_D.csv").exists()

    def test_as_duas_origens_da_vivo_caem_na_mesma_pasta(self, destino):
        """`SMS_ITF` e `VIVO` são cinco origens para quatro destinos."""
        sftp = _SFTPFalso({
            "/interfaces/GERACAO_DETRAF_SMS_ITF": [f"SMS_{PERIODO}_D.csv"],
            "/interfaces/GERACAO_DETRAF_VIVO": [f"VIVO_{PERIODO}_D.csv"],
        })

        CaptacaoExpectativaService(sftp=sftp).executar(referencia=PERIODO)

        assert sorted(item.name for item in (destino / "Vivo").iterdir()) == [
            f"SMS_{PERIODO}_D.csv",
            f"VIVO_{PERIODO}_D.csv",
        ]

    def test_o_mapa_tem_os_quatro_destinos_previstos(self):
        """
        🔴 Baixar para uma pasta que o RPA 2 não lê é trabalho jogado fora.

        A conferência contra o `PASTAS_EXPECTATIVAS` de verdade mora no
        `verificar_ambiente.py`, e não aqui: sob pytest o `.env` não é lido por
        design, e a lista vem vazia. O que se trava aqui é o mapa em si — quem
        acrescentar uma origem nova vai ter que decidir conscientemente o
        destino, e lembrar de configurá-lo.
        """
        assert set(ce.MAPA_PASTAS.values()) == {"Vivo", "TLF", "MVNO", "Detraf TRP"}


class TestResiliencia:
    def test_pasta_remota_indisponivel_nao_derruba_as_outras(self, destino):
        sftp = _SFTPFalso(
            {
                "/interfaces/GERACAO_DETRAF_VIVO": [f"A_{PERIODO}_D.csv"],
                "/interfaces/GERACAO_DETRAF_TELEFONICA": [f"B_{PERIODO}_D.csv"],
            },
            falhar_em={"/interfaces/GERACAO_DETRAF_VIVO"},
        )

        resultado = CaptacaoExpectativaService(sftp=sftp).executar(referencia=PERIODO)

        assert resultado.baixados == ["TLF/B_202603_D.csv"]

    def test_falha_num_arquivo_nao_derruba_os_demais(self, destino, monkeypatch):
        sftp = _SFTPFalso(
            {"/interfaces/GERACAO_DETRAF_VIVO": [f"A_{PERIODO}_D.csv", f"B_{PERIODO}_D.csv"]}
        )
        original = sftp.baixar

        def baixar(caminho_remoto, destino_arquivo):
            if caminho_remoto.endswith(f"A_{PERIODO}_D.csv"):
                raise OSError("disco cheio")
            return original(caminho_remoto, destino_arquivo)

        monkeypatch.setattr(sftp, "baixar", baixar)

        resultado = CaptacaoExpectativaService(sftp=sftp).executar(referencia=PERIODO)

        assert resultado.baixados == ["Vivo/B_202603_D.csv"]
        assert len(resultado.falhas) == 1

    def test_a_sessao_e_fechada_mesmo_sem_nada_para_baixar(self, destino):
        sftp = _SFTPFalso({})

        CaptacaoExpectativaService(sftp=sftp).executar(referencia=PERIODO)

        assert sftp.conectou and sftp.fechou

    def test_nada_encontrado_avisa_sem_falhar(self, destino, caplog):
        """
        Zero arquivos não é erro — pode ser o período errado, e a validação segue
        com o que já estiver na pasta. Mas precisa aparecer no log.
        """
        resultado = CaptacaoExpectativaService(sftp=_SFTPFalso({})).executar(
            referencia=PERIODO
        )

        assert resultado.baixados == []
        assert "Nenhum arquivo" in caplog.text


class TestPeriodo:
    def test_referencia_explicita_manda(self, destino):
        sftp = _SFTPFalso({
            "/interfaces/GERACAO_DETRAF_VIVO": ["A_202601_D.csv", "A_202603_D.csv"]
        })

        resultado = CaptacaoExpectativaService(sftp=sftp).executar(referencia="202601")

        assert resultado.periodo == "202601"
        assert resultado.baixados == ["Vivo/A_202601_D.csv"]

    def test_sem_referencia_usa_a_competencia_do_ambiente(self, destino):
        """
        O conftest fixa `DEBUG_ANO_MES_ATUAL=202508`, então a competência é
        202507 — o mês anterior. É a mesma conta que a validação usa.
        """
        sftp = _SFTPFalso({
            "/interfaces/GERACAO_DETRAF_VIVO": ["A_202507_D.csv", "A_202601_D.csv"]
        })

        resultado = CaptacaoExpectativaService(sftp=sftp).executar()

        assert resultado.periodo == "202507"
        assert resultado.baixados == ["Vivo/A_202507_D.csv"]


class TestOrigemEmDisco:
    def test_pasta_plana_roteia_pelo_nome(self, destino, tmp_path):
        """
        `Insumos/Expectativa/` tem tudo junto, sem espelhar a árvore remota.

        🔴 Cada arquivo entra **uma** vez, na pasta que o nome dele indica. Antes
        de 2026-08-10 a origem plana casava com as cinco pastas remotas, e o
        mesmo arquivo era copiado quatro vezes — três delas para a pasta errada.
        """
        origem = tmp_path / "origem"
        origem.mkdir()
        (origem / f"A_{PERIODO}_SMP_VIVO_D.csv").write_text("a\n", encoding="utf-8")
        (origem / f"B_{PERIODO}_STF_TLF_D.csv").write_text("b\n", encoding="utf-8")
        (origem / f"Y_{PERIODO}_L_VIVO_D.csv").write_text("y\n", encoding="utf-8")

        resultado = CaptacaoExpectativaService(de_pasta=origem).executar(
            referencia=PERIODO
        )

        assert sorted(resultado.baixados) == [
            f"TLF/B_{PERIODO}_STF_TLF_D.csv",
            f"Vivo/A_{PERIODO}_SMP_VIVO_D.csv",
        ]
        # O resumido continua fora, mesmo lendo do disco.
        assert not (destino / "Vivo" / f"Y_{PERIODO}_L_VIVO_D.csv").exists()

    def test_arquivo_sem_pasta_no_nome_falha_dizendo(self, destino, tmp_path):
        """
        Copiar para um palpite seria pior: o arquivo entraria na comparação de
        outra origem. Fica de fora, nomeado no log e no resumo.
        """
        origem = tmp_path / "origem"
        origem.mkdir()
        (origem / f"SEM_PASTA_{PERIODO}_D.csv").write_text("x\n", encoding="utf-8")

        resultado = CaptacaoExpectativaService(de_pasta=origem).executar(
            referencia=PERIODO
        )

        assert resultado.baixados == []
        assert "destino indefinido" in resultado.falhas[0]

    def test_le_da_subpasta_quando_a_arvore_esta_espelhada(self, destino, tmp_path):
        origem = tmp_path / "origem"
        (origem / "GERACAO_DETRAF_VIVO").mkdir(parents=True)
        (origem / "GERACAO_DETRAF_VIVO" / f"V_{PERIODO}_D.csv").write_text(
            "v\n", encoding="utf-8"
        )

        resultado = CaptacaoExpectativaService(de_pasta=origem).executar(
            referencia=PERIODO
        )

        assert "Vivo/V_202603_D.csv" in resultado.baixados

    def test_pasta_inexistente_falha_com_o_motivo(self, destino, tmp_path, caplog):
        resultado = CaptacaoExpectativaService(
            de_pasta=tmp_path / "nao_existe"
        ).executar(referencia=PERIODO)

        assert resultado.baixados == []
        assert "não existe" in caplog.text


class TestResumo:
    def test_o_resumo_diz_a_origem_e_o_periodo(self, destino):
        sftp = _SFTPFalso({"/interfaces/GERACAO_DETRAF_VIVO": [f"A_{PERIODO}_D.csv"]})

        resultado = CaptacaoExpectativaService(sftp=sftp).executar(referencia=PERIODO)
        resumo = "\n".join(resultado.resumo())

        assert PERIODO in resumo
        assert "Vivo/A_202603_D.csv" in resumo
