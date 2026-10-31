"""Orquestração do RPA 2 — validação e apuração de contestação.

Encadeia as três etapas do robô. As duas últimas, na origem, eram projetos
separados, cada um com o seu ``process_handle.run()``; a primeira nasceu em
2026-08-10, quando a expectativa passou a vir por SFTP em vez de aparecer na
pasta.

1. **Captação** (2026-08-10): baixa do SFTP do ClickHub os arquivos ``_D`` do
   período e os põe em ``CAMINHO_EXPECTATIVA_DETRAF``. Atrás do
   ``PERMITIR_DOWNLOAD_SFTP``; desligado, a etapa segue com o que já está lá.
2. **Validação** (Projeto 2, Épico 2 — HU-04 a HU-08): valida layout, tarifas e
   descritores dos arquivos da operadora e da expectativa; gera ``_BK`` e
   ``_ERRO``; registra o resultado no WebFat.
3. **Batimento** (Projeto 3, Épico 3 — HU-09 a HU-11): consolida os dois lados,
   sumariza por EOT × remuneração × mês de tráfego, aplica a regra de variação e
   popula a tabela de contestação para o analista decidir.

A ordem importa duas vezes: a validação lê o que a captação trouxe, e o batimento
consome o que a validação registrou. O segundo acoplamento era implícito entre os
dois projetos de origem — agora os dois são explícitos.

O RPA 2 termina num **ponto de decisão humana**: o analista escolhe no WebFat o
que contestar e se haverá retenção. É o que separa este robô do RPA 3.
"""

from comum.config import configuration
from comum.config.diagnostico_execucao import DiagnosticoInativo
from comum.config.logger_config import logger
from comum.utils import pausa
from comum.utils.decoradores import log_execucao
from src.controllers.batimento_detraf_controller import BatimentoDetrafController
from src.controllers.captacao_expectativa_controller import (
    CaptacaoExpectativaController,
)
from src.controllers.validacao_detrafs_controller import ValidacaoDetrafsController


@log_execucao
def run(
    etapa: str | None = None,
    diagnostico=None,
    referencia: str | None = None,
    de_pasta: str | None = None,
) -> None:
    """
    Executa a captação da expectativa, a validação e o batimento, nesta ordem.

    Args:
        etapa: Recorte de ``--etapa``. `None` (o normal) executa as três na
            ordem. ``"batimento"`` sozinho **pressupõe que a validação daquele
            mês já rodou** — ele consome o que ela registrou no WebFat, e é
            justamente esse acoplamento que se quer poder exercitar isolado.
        diagnostico: `DiagnosticoDeExecucao` para registrar o que cada etapa
            recebeu, produziu e — se for o caso — o erro **com o nome da etapa**.
            `None` faz cada etapa rodar solta, como antes.
        referencia: Mês de tráfego, para a captação procurar no SFTP. `None` usa
            a competência do ambiente.
        de_pasta: Diretório local a usar como origem no lugar do SFTP.
    """
    registro = diagnostico or DiagnosticoInativo()

    if etapa in (None, "expectativa"):
        logger.info("[RPA 2] Etapa 1/3 - captação da expectativa Vivo")
        with registro.etapa(
            "expectativa",
            {"origem": de_pasta or "SFTP ClickHub",
             "destino": str(configuration.CAMINHO_EXPECTATIVA_DETRAF)},
        ) as atual:
            resumo = CaptacaoExpectativaController(
                de_pasta=de_pasta
            ).captar_expectativa(referencia=referencia)
            atual.produzido = resumo
        pausa.pausar(
            titulo="RPA 2 — etapa 1/3: captação da expectativa",
            linhas=resumo,
            proxima_etapa=(
                "nenhuma — a execução termina aqui (--etapa=expectativa)"
                if etapa == "expectativa"
                else "validação dos arquivos, que LÊ o que a captação acabou de "
                     "trazer"
            ),
            caminho=configuration.CAMINHO_EXPECTATIVA_DETRAF,
        )
    else:
        # Não é aviso: pular a captação é o normal quando se está repetindo a
        # validação de um mês cujos arquivos já estão em disco.
        logger.info(f"[RPA 2] Captação da expectativa pulada por --etapa={etapa}.")
        registro.pular("expectativa", f"pulada por --etapa={etapa}")

    if etapa in (None, "validacao"):
        logger.info("[RPA 2] Etapa 2/3 - validação dos arquivos de Detraf")
        with registro.etapa(
            "validacao",
            {"CAMINHO_OPERADORAS": str(configuration.CAMINHO_OPERADORAS),
             "CAMINHO_EXPECTATIVA_DETRAF": str(configuration.CAMINHO_EXPECTATIVA_DETRAF)},
        ) as atual:
            resumo = ValidacaoDetrafsController().validar_detrafs()
            atual.produzido = resumo
        pausa.pausar(
            titulo="RPA 2 — etapa 2/3: validação",
            linhas=resumo,
            proxima_etapa=(
                "nenhuma — a execução termina aqui (--etapa=validacao)"
                if etapa == "validacao"
                else "batimento Detraf × expectativa, que LÊ o que a validação "
                     "acabou de registrar"
            ),
            caminho=configuration.CAMINHO_OPERADORAS,
        )
    else:
        # Aviso, e não info: pular a validação é a única das três omissões que
        # esvazia o resultado do batimento sem que isso pareça defeito.
        logger.warning(
            f"[RPA 2] Validação PULADA por --etapa={etapa}. O batimento lê o "
            f"que a validação registrou: se ela não rodou para este mês, o "
            f"resultado será vazio — e isso não é defeito."
        )
        registro.pular(
            "validacao",
            f"pulada por --etapa={etapa}. O batimento lê o que ela registrou: "
            f"se não rodou neste mês, o resultado sai vazio — e não é defeito.",
        )

    if etapa in (None, "batimento"):
        logger.info("[RPA 2] Etapa 3/3 - batimento Detraf x expectativa")
        with registro.etapa(
            "batimento",
            {"CAMINHO_OPERADORAS": str(configuration.CAMINHO_OPERADORAS)},
        ) as atual:
            resumo = BatimentoDetrafController().batimento_detraf()
            atual.produzido = resumo
        pausa.pausar(titulo="RPA 2 — etapa 3/3: batimento", linhas=resumo)
    else:
        logger.info(f"[RPA 2] Batimento pulado por --etapa={etapa}.")
        registro.pular("batimento", f"pulada por --etapa={etapa}")

    logger.info(
        "[RPA 2] Concluído. Aguardando a decisão do analista no WebFat "
        "para o RPA 3 prosseguir."
    )
