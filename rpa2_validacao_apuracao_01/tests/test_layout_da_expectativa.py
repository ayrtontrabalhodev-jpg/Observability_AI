"""A expectativa Vivo tem layout próprio — e a extração precisa saber disso.

🔴 Pontos 5 do e-mail da Luciana de 23/09/2026:

    "Os arquivos de Expectativa da Vivo no banco não estão com as informações
     extraídas, não foram renomeados como orientado"

A consulta ao banco em 24/09 quantificou: **562 de 562** registros de
expectativa com `remuneracoes` nulo, e **0 de 564** com o sufixo `_EXP`/`_ERRO`
no nome.

Duas causas distintas:

1. O filtro de `Rel` lia a coluna errada e zerava o arquivo; tudo voltava como
   `dados_padrao`. A primeira tentativa (24/09) foi escolher o layout pelo
   nome do lote — e errou para o outro lado, porque existem **dois** formatos
   sob o nome "expectativa". Ver `TestOLayoutSaiDoConteudo`, no fim do arquivo.

2. A validação renomeia os arquivos **depois** de registrá-los, então o nome
   gravado era o anterior ao rename.
"""

import pandas as pd
import pytest

from comum.config import constantes as const
from src.services.resultado_validacao import (
    _LAYOUT_DETRAF,
    _LAYOUT_EXPECTATIVA,
    _layout_do_conteudo,
    _nome_com_sufixo,
)

from pathlib import Path


class TestOsDoisLayoutsSaoDiferentes:
    """
    Se estes índices coincidissem, o defeito não existiria — e o teste que
    garante a distinção é o que impede alguém de "simplificar" os dois num só.
    """

    def test_a_expectativa_tem_deslocamento(self):
        assert _LAYOUT_EXPECTATIVA.credora != _LAYOUT_DETRAF.credora
        assert _LAYOUT_EXPECTATIVA.rel != _LAYOUT_DETRAF.rel
        assert _LAYOUT_EXPECTATIVA.descritor != _LAYOUT_DETRAF.descritor

    def test_a_coluna_rel_do_detraf_e_o_poi_da_expectativa(self):
        """
        🔴 A origem do defeito: filtrar `Rel` no índice 5 de um arquivo de
        expectativa lê o `POI`, que nunca vale "00" — e o arquivo inteiro sai.
        """
        assert _LAYOUT_DETRAF.rel == const.COL_REL == 5
        assert _LAYOUT_EXPECTATIVA.rel == const.EXPECTATIVA_COL_REL == 6
        assert const.EXPECTATIVA_COL_POI == 5

    def test_a_expectativa_nao_tem_r_bruto(self):
        """
        Não é omissão: o arquivo termina em `VALOR_LIQUIDO` (pendência N3).
        Preencher `valor_bruto_desp` com o líquido seria gravar uma coisa no
        lugar de outra, e é justamente sobre R$_Bruto que a apuração compara.
        """
        assert _LAYOUT_EXPECTATIVA.r_bruto is None
        assert _LAYOUT_DETRAF.r_bruto == const.COL_R_BRUTO


class TestONomeGravadoEODoDisco:
    """🔴 Ponto 5: 0 de 564 registros tinham o sufixo."""

    @pytest.mark.parametrize(
        "lote, sufixo",
        [
            ("EXPECTATIVA_SUCESSO", "_EXP"),
            ("EXPECTATIVA_ERRO", "_ERRO"),
        ],
    )
    def test_cada_lote_de_expectativa_tem_o_seu_sufixo(self, lote, sufixo):
        caminho = Path("DETRAF_FINAL_VIVO_202607_N_ALGAR_STF_VIVO_D.txt")

        assert _nome_com_sufixo(caminho, lote) == (
            f"DETRAF_FINAL_VIVO_202607_N_ALGAR_STF_VIVO_D{sufixo}.txt"
        )

    @pytest.mark.parametrize("lote", ["DETRAF_SUCESSO", "DETRAF_ERRO"])
    def test_o_arquivo_recebido_por_email_nao_e_renomeado(self, lote):
        """
        🔴 E-mail da Luciana de 29/09/2026:

            "O RPA não pode promover nenhuma alteração nos arquivos recebidos
             nos e-mails. Exemplo:
             expectativa-telefonica-brasil-smp-c-vc1-202607_ERRO.xlsx — o nome
             do arquivo na tabela está com _ERRO no final, diferente do arquivo
             original na pasta 33."

        O pedido do sufixo (ponto 5 de 23/09) estava na seção da expectativa, e
        nós o aplicamos aos dois tipos. O Detraf da operadora é insumo de
        terceiro: o nome é o que ela escreveu, no disco e no banco.
        """
        nome = "expectativa-telefonica-brasil-smp-c-vc1-202607.xlsx"
        assert _nome_com_sufixo(Path(nome), lote) == nome

    def test_a_extensao_e_preservada(self):
        assert _nome_com_sufixo(Path("a.csv"), "EXPECTATIVA_SUCESSO") == "a_EXP.csv"
        assert _nome_com_sufixo(Path("a.xlsx"), "EXPECTATIVA_SUCESSO") == "a_EXP.xlsx"

    def test_nao_duplica_o_sufixo(self):
        """
        Arquivo reprocessado já chega renomeado. Sem esta guarda, viraria
        `..._EXP_EXP.csv` a cada rodada.
        """
        assert _nome_com_sufixo(Path("x_EXP.csv"), "EXPECTATIVA_SUCESSO") == "x_EXP.csv"
        assert _nome_com_sufixo(Path("x_ERRO.csv"), "EXPECTATIVA_ERRO") == "x_ERRO.csv"

    def test_lote_desconhecido_mantem_o_nome(self):
        """Sem saber o destino, não inventa sufixo."""
        assert _nome_com_sufixo(Path("x.csv"), "OUTRO") == "x.csv"


def _quadro(colunas: int, indice_do_rel: int) -> pd.DataFrame:
    """Um quadro com linhas de tráfego (`Rel` == "00") na coluna pedida."""
    dados = [[f"c{indice}" for indice in range(colunas)] for _ in range(3)]
    quadro = pd.DataFrame(dados)
    quadro.iloc[:, indice_do_rel] = "00"
    return quadro


class TestOLayoutSaiDoConteudo:
    """
    🔴 Correção de 25/09/2026, e é uma correção do meu próprio erro de 24/09.

    Eu decidi o layout pelo **nome do lote**: lote `EXPECTATIVA_*` lia os
    índices deslocados. Os arquivos de expectativa que a Vivo gera
    (`DETRAF_FINAL_VIVO_..._D.csv`) são **Detraf comum** — 21 colunas, `Rel`
    na 5, `R$_Bruto` na 14. Medido nos quatro arquivos do repositório:
    `Rel` na coluna 5 acha 8.275 / 249 / 52 / 355 linhas de tráfego; na
    coluna 6, **zero** em todos.

    Resultado: o filtro esvaziava o arquivo inteiro, a extração caía nos
    `dados_padrao` e os 562 registros continuavam com `remuneracoes` nulo —
    exatamente o sintoma do ponto 5 que a mudança deveria ter resolvido.

    A coluna `Rel` é o desempate honesto: só ela vale "00"/"0" no tráfego.
    """

    def test_o_arquivo_da_vivo_e_lido_como_detraf_mesmo_no_lote_expectativa(self):
        assert (
            _layout_do_conteudo(_quadro(21, 5), _LAYOUT_EXPECTATIVA, "x.csv")
            is _LAYOUT_DETRAF
        )

    def test_o_arquivo_do_ict_continua_sendo_lido_deslocado(self):
        assert (
            _layout_do_conteudo(_quadro(16, 6), _LAYOUT_EXPECTATIVA, "x.csv")
            is _LAYOUT_EXPECTATIVA
        )

    def test_o_detraf_da_operadora_nao_muda(self):
        assert (
            _layout_do_conteudo(_quadro(21, 5), _LAYOUT_DETRAF, "x.csv")
            is _LAYOUT_DETRAF
        )

    def test_sem_linha_de_trafego_mantem_o_preferido(self):
        """
        Arquivo só de totais não tem como desempatar — e inventar um layout
        aqui seria pior que manter o palpite: o retorno é `dados_padrao` de
        qualquer jeito.
        """
        quadro = pd.DataFrame([["a"] * 21])
        assert (
            _layout_do_conteudo(quadro, _LAYOUT_DETRAF, "x.csv") is _LAYOUT_DETRAF
        )

    def test_quadro_estreito_nao_estoura(self):
        """`Rel` da expectativa é a coluna 6; um quadro de 6 colunas não a tem."""
        assert (
            _layout_do_conteudo(_quadro(6, 5), _LAYOUT_EXPECTATIVA, "x.csv")
            is _LAYOUT_DETRAF
        )
