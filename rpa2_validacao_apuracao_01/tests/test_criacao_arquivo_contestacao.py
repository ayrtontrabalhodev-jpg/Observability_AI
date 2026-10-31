"""HU-09 e HU-10 — comparativo apresentado × esperado, e a gravação no banco.

É o módulo mais consequente do RPA 2: ele produz `tbl_rpa_log_detraf_despesa_contestacao`,
a tabela que o **RPA 3 lê** para saber o cenário de cada linha. 554 linhas que
estavam sem um único teste.

## As duas convenções em jogo

A V2 é explícita sobre quem é quem no arquivo:

    "1ª coluna ou 'Credora' deve estar preenchida com uma EOT relacionada
     **à operadora**. A base de busca deve ser o Anexo 5."
    "2ª coluna ou 'Devedora' deve estar preenchida com uma das EOTs **da Vivo**."

E `validacao_colunas._mascara_col_2_eot_vivo` concorda: valida a coluna de
**índice 1** (Devedora) contra os nomes fantasia da Vivo.

Isso é o que estes testes fixam. O docstring de
`_preparar_dados_persistencia_contestacao` afirma a convenção **invertida**
("Credora = EOT Vivo, Devedora = EOT da operadora") — e é dele que vinha o defeito
de `tipo_servico_vivo`, corrigido em 2026-08-04.
"""

import pandas as pd
import pytest

from src.services.criacao_arquivo_contestacao import CriacaoArquivoContestacao

from conftest import LINHA_VALIDA, linha


@pytest.fixture()
def servico() -> CriacaoArquivoContestacao:
    return CriacaoArquivoContestacao()


def _df(*linhas: list[str]) -> pd.DataFrame:
    return pd.DataFrame(list(linhas))


class TestConversaoNumerica:
    """Os arquivos vêm com vírgula decimal; a comparação é feita em float."""

    def test_virgula_decimal_vira_float(self, servico):
        resultado = servico._converter_coluna_numerica(pd.Series(["1234,56", "0,5"]))

        assert list(resultado) == [1234.56, 0.5]

    def test_valor_ilegivel_vira_zero(self, servico):
        """
        Zero é escolha do módulo, não erro: uma célula ilegível não pode derrubar
        a apuração do mês inteiro.
        """
        assert list(servico._converter_coluna_numerica(pd.Series(["abc", ""]))) == [
            0.0,
            0.0,
        ]

    def test_separador_de_milhar_vira_zero(self, servico):
        """
        ⚠️ **Limitação com consequência, fixada aqui e não corrigida.**

        A conversão só troca a vírgula por ponto. Com separador de milhar
        (`"1.234,56"`) o resultado vira `"1.234.56"`, que não é número — e o
        `fillna(0)` transforma em **zero, em silêncio**.

        Um arquivo assim produziria `R$_Bruto` zerado do lado da operadora, e
        `calcular_variacao` devolve **-100%** — sem contestação. Se fosse do lado
        da expectativa, daria **+100%** e contestação indevida.

        Não corrijo às cegas porque a V2 (12ª a 15ª coluna) diz apenas "campo
        valor com até duas casas decimais", sem definir separador de milhar, e
        aceitar `"1.234.56"` como 1234.56 exigiria assumir uma convenção que o
        documento não dá. A proteção real é a validação de colunas (HU-04), que
        reprova o arquivo antes de ele chegar aqui — coberta em
        `test_validacao_colunas.py::TestColunasFinanceiras12a15`.
        """
        assert list(servico._converter_coluna_numerica(pd.Series(["1.234,56"]))) == [0.0]


class TestEnriquecimento:
    def test_tipo_operacao_vem_da_credora(self, servico):
        """
        `tipo_operacao` sai da coluna 0 — a **Credora**, que pela V2 é a
        operadora. É esse o dado que alimenta a dimensão do agrupamento.
        """
        df = servico._enriquecer_com_tipo(_df(LINHA_VALIDA))

        # EOT 021 = CLARO, SMP no Anexo 5 semeado.
        assert df["tipo_operacao"].iloc[0] == "SMP"

    def test_dataframe_vazio_nao_quebra(self, servico):
        assert servico._enriquecer_com_tipo(pd.DataFrame()).empty


class TestPersistenciaNoBanco:
    """
    O formato de `tbl_rpa_log_detraf_despesa_contestacao`. É o contrato com o
    RPA 3 — a chave de busca dele é
    `(eot_operadora, eot_tbra, referencia, trafego, remuneracao)`.
    """

    @pytest.fixture()
    def df_contest(self) -> pd.DataFrame:
        """Uma linha já agregada, no formato que `_gerar_aba_contest` produz."""
        return pd.DataFrame([{
            "Credora": "021",        # operadora (V2: 1ª coluna)
            "Devedora": "011",       # Vivo      (V2: 2ª coluna)
            "Referencia": "202507",
            "Trafego": "202507",
            "GH": "N",
            "tipo_operacao": "SMP",   # tipo de serviço da CREDORA (operadora)
            "tipo_produto": "TU-RL",
            "Minutos_op": 500.0,
            "RS_op": 100.0,
            "Minutos_tbra": 400.0,
            "RS_tbra": 80.0,
            "variacao_rs": 20.0,
            "variacao_pct": 20.0,
        }])

    def test_os_eots_seguem_a_convencao_da_v2(self, servico, df_contest):
        """
        `eot_operadora` ← Credora e `eot_tbra` ← Devedora. Trocar os dois faria o
        RPA 3 nunca casar nenhuma linha, e ele apenas registraria "chave sem
        linha correspondente" — falha silenciosa.
        """
        linhas = servico._preparar_dados_persistencia_contestacao(df_contest, "CLARO")

        assert linhas["eot_operadora"].iloc[0] == "021"
        assert linhas["eot_tbra"].iloc[0] == "011"

    def test_tipo_servico_vivo_e_o_da_vivo(self, servico, df_contest):
        """
        🐛 **Defeito corrigido em 2026-08-04.** A coluna recebia
        `tipo_operacao`, derivado da **Credora** — ou seja, o tipo de serviço da
        *operadora*, não da Vivo.

        A prova de que estava errado é interna ao próprio RPA 2:
        `resultado_validacao.py` preenche a mesma coluna a partir da
        **Devedora**. Dois módulos do mesmo robô gravavam lados opostos na mesma
        coluna.

        Aqui a Devedora é 011 = VIVO/STFC no Anexo 5; a Credora é 021 =
        CLARO/SMP. O valor certo é STFC.
        """
        linhas = servico._preparar_dados_persistencia_contestacao(df_contest, "CLARO")

        assert linhas["tipo_servico_vivo"].iloc[0] == "STFC"

    def test_remuneracao_e_gravada(self, servico, df_contest):
        """
        Acréscimo da unificação (D-15): o Projeto 3 não gravava `remuneracao`,
        mas ela faz parte da chave que o RPA 3 usa. Sem ela, nenhuma linha casa.
        """
        linhas = servico._preparar_dados_persistencia_contestacao(df_contest, "CLARO")

        # Coluna do banco -> `remuneracoes`, plural. O dado de origem é
        # `tipo_produto` no frame Contest; a tradução acontece no INSERT.
        assert linhas["remuneracoes"].iloc[0] == "TU-RL"

    def test_campos_iniciais_ficam_para_quem_vem_depois(self, servico, df_contest):
        """
        `carga_agi` é atualizado pela HU-18 após o upload; `tipo_contestacao`
        pelo analista no WebFat (HU-11) e regravado pela HU-16.
        """
        from comum.dados.tabelas import CARGA_AGI_NAO_CARREGADO

        linhas = servico._preparar_dados_persistencia_contestacao(df_contest, "CLARO")

        assert linhas["carga_agi"].iloc[0] == CARGA_AGI_NAO_CARREGADO
        assert linhas["tipo_contestacao"].iloc[0] is None

    def test_a_diferenca_de_minutos_e_operadora_menos_vivo(self, servico, df_contest):
        linhas = servico._preparar_dados_persistencia_contestacao(df_contest, "CLARO")

        assert linhas["minutos_diferenca"].iloc[0] == pytest.approx(100.0)

    def test_lote_vazio_nao_grava_nada(self, servico):
        assert servico._preparar_dados_persistencia_contestacao(
            pd.DataFrame(), "CLARO"
        ).empty


class TestAnaliseDeContestacao:
    """HU-10 — a flag de contestação e a modalidade da tarifa VU-M."""

    def _contest(self, **campos) -> pd.DataFrame:
        base = {
            "Credora": "021",
            "Devedora": "011",
            "GH": "N",
            "tipo_produto": "TU-RL",
            "variacao_pct": 20.0,
        }
        base.update(campos)
        return pd.DataFrame([base])

    def test_variacao_acima_do_limiar_contesta(self, servico):
        resultado = servico._aplicar_analise_contestacao(self._contest(variacao_pct=5.0))

        assert resultado["flag_contestacao"].iloc[0] == "S"

    def test_variacao_abaixo_do_limiar_nao_contesta(self, servico):
        resultado = servico._aplicar_analise_contestacao(self._contest(variacao_pct=0.5))

        assert resultado["flag_contestacao"].iloc[0] == "N"

    def test_variacao_negativa_nao_contesta(self, servico):
        """
        Só se contesta quando a operadora apresentou **mais** que a expectativa.
        Ela cobrar a menos não é motivo de contestação.
        """
        resultado = servico._aplicar_analise_contestacao(self._contest(variacao_pct=-30.0))

        assert resultado["flag_contestacao"].iloc[0] == "N"

    def test_modalidade_so_existe_para_vum_em_gh_reduzido(self, servico):
        resultado = servico._aplicar_analise_contestacao(
            self._contest(tipo_produto="TU-RL", GH="R")
        )

        assert resultado["modalidade_tarifa"].iloc[0] is None

    def test_vum_reduzido_com_devedora_stfc_e_nao_reduzido(self, servico):
        """
        Depende do tipo de serviço da **Devedora** (a Vivo). EOT 011 = VIVO/STFC.
        """
        resultado = servico._aplicar_analise_contestacao(
            self._contest(tipo_produto="VU-M", GH="R", Devedora="011")
        )

        assert resultado["modalidade_tarifa"].iloc[0] == "NR"

    def test_vum_reduzido_com_devedora_smp_e_reduzido(self, servico):
        """EOT 012 = VIVO/SMP."""
        resultado = servico._aplicar_analise_contestacao(
            self._contest(tipo_produto="VU-M", GH="R", Devedora="012")
        )

        assert resultado["modalidade_tarifa"].iloc[0] == "R"


class TestUniaoDeOperadoras:
    def test_une_os_dois_lados(self, servico):
        """
        Uma operadora que só aparece de um lado ainda precisa ser processada: sem
        Detraf a expectativa é contestada inteira; sem expectativa a variação é
        de 100%.
        """
        operadoras = servico._obter_operadoras(
            {"Claro": []}, {"Algar": []}
        )

        assert operadoras == {"CLARO", "ALGAR"}

    def test_normaliza_para_maiuscula(self, servico):
        assert servico._obter_operadoras({"claro": []}, {"CLARO": []}) == {"CLARO"}

    def test_nao_identificada_fica_de_fora(self, servico):
        """
        O grupo dos arquivos cuja EOT credora não foi reconhecida não é uma
        operadora — não há com quem contestar.
        """
        operadoras = servico._obter_operadoras(
            {"OPERADORA_NAO_IDENTIFICADA": [], "Claro": []}, {}
        )

        assert operadoras == {"CLARO"}


class TestConversaoNumericaQueZera:
    """
    O `fillna(0)` engolia o erro (visibilidade acrescentada em 2026-08-06).

    `"1.234,56"` vira `"1.234.56"` depois do `replace`, o `to_numeric` desiste, e
    o valor vira **zero**. Numa apuração de contestação, mil duzentos e trinta e
    quatro reais virando zero é uma **diferença inventada** — que chega ao
    cliente como carta.

    O comportamento não mudou: zerar continua sendo o que acontece, porque a V2
    não define separador de milhar para estes campos e escolher um lado aqui
    criaria o erro simétrico. O que mudou é que deixou de ser silencioso.
    """

    def _converter(self, valores):
        return CriacaoArquivoContestacao._converter_coluna_numerica(
            pd.Series(valores), rotulo="R$_Bruto (coluna 15)"
        )

    def test_virgula_decimal_continua_convertendo(self):
        assert self._converter(["1234,56"]).tolist() == [1234.56]

    def test_ponto_decimal_continua_convertendo(self):
        assert self._converter(["1234.56"]).tolist() == [1234.56]

    def test_separador_de_milhar_ainda_vira_zero(self, caplog):
        """O comportamento é o mesmo; o que muda é o aviso."""
        with caplog.at_level("ERROR"):
            resultado = self._converter(["1.234,56"])

        assert resultado.tolist() == [0.0]
        assert "ZERO" in caplog.text
        assert "1.234,56" in caplog.text
        assert "R$_Bruto (coluna 15)" in caplog.text, "sem a coluna, o aviso não localiza"
        assert "separador de milhar" in caplog.text

    def test_o_aviso_conta_quantos_cairam(self, caplog):
        with caplog.at_level("ERROR"):
            self._converter(["1.234,56", "2.000,00", "10,00"])

        assert "2 valor(es)" in caplog.text

    def test_vazio_nao_gera_aviso(self, caplog):
        """Vazio já era zero antes; não é perda de dado."""
        with caplog.at_level("ERROR"):
            resultado = self._converter(["", "10,00"])

        assert resultado.tolist() == [0.0, 10.0]
        assert caplog.text == ""

    def test_coluna_toda_boa_nao_gera_aviso(self, caplog):
        with caplog.at_level("ERROR"):
            self._converter(["1,00", "2,50", "3"])

        assert caplog.text == ""


class TestRemuneracaoVemDoCatalogo:
    """
    🔴 **Defeito A4, corrigido em 2026-08-06.**

    A `remuneracao` que este serviço grava é **parte da chave** do sinal do
    analista, que o RPA 3 lê por igualdade exata de string. Até esta correção,
    quem gravava usava a regra fixa do Épico 2 e quem lia usava o catálogo D-5 —
    dois vocabulários que só coincidem em `TU-RL` e `VU-M`.

    Para todo outro descritor, o RPA 3 **não encontrava o sinal**, e o sintoma
    era indistinguível de "o analista não sinalizou": nenhum erro, nenhum aviso,
    simplesmente nada contestado.

    Os testes anteriores não pegaram porque as fixtures usam exatamente os dois
    valores em que as duas fontes concordam.
    """

    def test_descritor_final_c_usa_o_catalogo_e_nao_a_regra_fixa(self, servico, repo_cache):
        """
        `C` é o caso que expõe a diferença: a regra fixa devolve `TUCOM` (sem
        hífen) e o catálogo, `TU-COM`. Um caractere de diferença bastava para a
        contestação nunca acontecer.
        """
        from comum.dominio.classificadores import classificar_descritor_remuneracao

        df = pd.DataFrame([linha(desc="XXC")])

        resultado = servico._enriquecer_com_tipo(df)

        assert resultado.iloc[0]["tipo_produto"] == "TU-COM"
        assert classificar_descritor_remuneracao("XXC") == "TUCOM", (
            "a regra fixa continua existindo — ela é a da validação de tarifa"
        )

    def test_os_valores_em_que_as_duas_fontes_concordam_nao_mudaram(
        self, servico, repo_cache
    ):
        """A correção não pode alterar o que já funcionava."""
        for descritor, esperado in (("XXL", "TU-RL"), ("XXV", "VU-M")):
            df = pd.DataFrame([linha(desc=descritor)])

            resultado = servico._enriquecer_com_tipo(df)

            assert resultado.iloc[0]["tipo_produto"] == esperado

    def test_descritor_fora_do_catalogo_e_nomeado_no_log(
        self, servico, repo_cache, caplog
    ):
        """
        Descritor não mapeado é ignorado por regra (AI/09 §7) — mas em silêncio
        ele vira linha sem remuneração, que o RPA 3 nunca encontra. Nomeá-lo é o
        que permite dizer se falta linha na tabela ou se o arquivo veio errado.

        Desde 2026-09-24 (e-mail da Luciana, 23/09) a linha não vai mais ao
        banco com `remuneracoes` NULL: sai `NAO_REGULADO`, e o aviso continua.
        """
        df = pd.DataFrame([linha(desc="XXZ")])

        with caplog.at_level("WARNING"):
            resultado = servico._enriquecer_com_tipo(df)

        assert resultado.iloc[0]["tipo_produto"] == "NAO_REGULADO"
        assert "XXZ" in caplog.text
        assert "mapeamento_descritores" in caplog.text


class TestContestacaoSemRemuneracaoNula:
    """
    🔴 2026-09-24 — e-mail da Luciana de 23/09/2026. A mesma coluna
    `remuneracoes` existe na tabela de contestação (um valor por linha). SMS
    tem que sair `TIS` — o valor do catálogo — e descritor fora do catálogo
    sai `NAO_REGULADO`, nunca NULL.
    """

    def test_sms_sai_tis_quando_o_catalogo_tem_o_final_s(self, servico, repo_cache, monkeypatch):
        monkeypatch.setattr(
            servico, "_indice_remuneracao", lambda: {"S": ["TIS"], "L": ["TU-RL"]}
        )
        df = pd.DataFrame([linha(desc="SENS", poi="SMS")])

        assert servico._enriquecer_com_tipo(df).iloc[0]["tipo_produto"] == "TIS"

    def test_sms_sai_tis_mesmo_sem_o_final_s_no_catalogo(self, servico, repo_cache):
        """O seed de teste não tem `S`; a reserva cobre o SMS com o mesmo valor."""
        df = pd.DataFrame([linha(desc="SENS", poi="SMS")])

        assert servico._enriquecer_com_tipo(df).iloc[0]["tipo_produto"] == "TIS"

    def test_a_linha_persistida_nao_leva_remuneracao_nula(self, servico, repo_cache):
        df = pd.DataFrame([linha(desc="XXZ"), linha(desc="SENS")])

        enriquecido = servico._enriquecer_com_tipo(df)

        assert enriquecido["tipo_produto"].tolist() == ["NAO_REGULADO", "TIS"]
        assert not enriquecido["tipo_produto"].isna().any()
