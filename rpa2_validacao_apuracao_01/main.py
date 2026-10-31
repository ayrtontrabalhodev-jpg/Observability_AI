"""RPA 2 — Validação e Apuração de Contestação.

Ponto de entrada do robô. Nenhum dos projetos de origem tinha um ``main.py``:
todos paravam em ``src/main/process_handle.py::run()``, sem nada que o chamasse.

Gatilho: execução em lote, disparada após a data de corte, quando todos os
arquivos do mês já foram recebidos pelo RPA 1. A data de corte é o
``DETRAF_DIA_LIBERACAO`` — **dia 5 por decisão do GP/dev em 2026-08-05**, que é o
que a V1 registrava; a V2 removeu a regra e não pôs nada no lugar.

Cobre HU-04 a HU-11 — reúne os Projetos 2 (validação) e 3 (batimento). Ver
``docs/01-entendimento/responsabilidades-dos-rpas.md``.

Termina num **ponto de decisão humana**: o analista escolhe no WebFat o que
contestar e se haverá retenção. É o que separa este robô do RPA 3.

⚠️ **A segunda execução do mesmo mês processa menos que a primeira.** O histórico
anti-reprocessamento (``DIRETORIO_HISTORICO_ARQUIVOS``) guarda o que já passou, e
repetir um cenário parece defeito quando não é. Para repetir de verdade, use
``python resetar_homologacao.py --referencia AAAAMM``.

Uso::

    python main.py                                     # como na agenda
    python main.py --help                              # todos os argumentos
    python main.py --referencia 202507 --dry-run       # repete julho, sem e-mail
    python main.py --etapa batimento                   # só a segunda metade
"""

import sys
from pathlib import Path

# A base comum (`comum.*`) vive na raiz de `unificado/`; o código do robô
# (`src.*`) vive nesta pasta. Ambas entram no path para que os imports dos
# projetos de origem continuem valendo sem alteração.
_RAIZ_RPA = Path(__file__).resolve().parent
_RAIZ_UNIFICADO = _RAIZ_RPA.parent

for _caminho in (str(_RAIZ_UNIFICADO), str(_RAIZ_RPA)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

#: Nome deste robô. Define o arquivo de log e o sufixo das variáveis por robô
#: (`ENV_RPA2` vence `ENV`). É aplicado ao ambiente **antes** de
#: `comum.config.configuration` ser importado — a configuração lê o ambiente uma
#: vez, no import, e depois disso mexer em `os.environ` não tem efeito.
NOME_RPA = "rpa2_validacao_apuracao"

ETAPAS = ("expectativa", "validacao", "batimento")


def main(argv: list[str] | None = None) -> int:
    """Executa o robô e devolve o código de saída do processo."""
    from comum.config import linha_de_comando as cli

    parser = cli.construir_parser(
        robo="RPA 2",
        descricao=(
            "Valida os arquivos de Detraf e de expectativa, faz o batimento "
            "entre os dois lados e popula a tabela de contestação para o "
            "analista decidir no WebFat."
        ),
        etapas=ETAPAS,
        aceita_de_pasta=True,
    )
    recorte = cli.aplicar(parser.parse_args(argv), NOME_RPA)

    # Só agora — depois de os argumentos terem virado ambiente.
    from comum.config.configuration import resumo_do_ambiente
    from comum.config.diagnostico_execucao import DiagnosticoDeExecucao
    from comum.config.logger_config import logger
    from comum.utils import pausa

    for linha in resumo_do_ambiente() + recorte.descrever():
        logger.info(f"[RPA 2] {linha}")

    # Um `.txt` por execução, com uma seção por etapa: o que ela recebeu, o que
    # produziu, e o erro COM traceback quando houver. Sem isto, o `except`
    # abaixo sabia que algo falhou e não sabia ONDE.
    diagnostico = DiagnosticoDeExecucao(
        robo=NOME_RPA,
        referencia=recorte.referencia or "",
        parametros=recorte.descrever(),
    )

    try:
        # O import entra AQUI, e não junto dos outros: ele puxa os
        # controllers, que puxam `bd_tabelas`, que resolve o banco no
        # import. SQLite faltando ou WebFat fora do ar matavam o
        # processo antes do `try` — e nenhum diagnóstico saía. É
        # justamente a falha que uma homologação encontra primeiro.
        with diagnostico.etapa("arranque") as _arranque:
            from src.main.process_handle import run

            _arranque.produzido = ["módulos carregados, banco resolvido"]

        run(
            etapa=recorte.etapa,
            diagnostico=diagnostico,
            referencia=recorte.referencia,
            de_pasta=recorte.de_pasta,
        )
    except pausa.ExecucaoCanceladaPeloOperador as cancelamento:
        # Não é erro: é decisão humana. Sai com 2 — distinto de 0 (sucesso) e
        # de 1 (falha) —, sem traceback, e dizendo onde parou. O que já foi
        # feito fica feito; as etapas são pontos de retomada.
        logger.warning(f"[RPA 2] {cancelamento} Nada além disto foi executado.")
        return 2
    except Exception:
        logger.excecao(
            f"[RPA 2] Execução interrompida por erro não tratado — "
            f"{diagnostico.desfecho}"
        )
        return 1
    finally:
        # No `finally`: o diagnóstico do que falhou é o mais útil de todos, e
        # ele só existe se for gravado também no caminho de erro.
        destino = diagnostico.gravar()
        if destino:
            logger.info(f"[RPA 2] Diagnóstico das etapas em [{destino}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
