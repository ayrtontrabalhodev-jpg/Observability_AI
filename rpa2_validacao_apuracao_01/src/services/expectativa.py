"""Aviso comum às duas varreduras da expectativa Vivo (Q21).

A `validacao_detrafs` e a `batimento_detraf` percorrem as mesmas
`PASTAS_EXPECTATIVAS` com filtros um pouco diferentes. O que elas têm em comum é
o que a Q21 resolveu: **uma pasta sem expectativa não pode passar batido.**

## Por que isso é grave

Sem o arquivo da Vivo, não há com o que comparar o Detraf da operadora. A
variação sai como 100% e **a operadora inteira é contestada indevidamente** — um
erro que chega ao cliente na forma de carta assinada. Até 2026-08-05 a pasta
ausente era simplesmente ignorada: o `if pasta.exists()` não tinha `else`.

## Por que avisa em vez de abortar

Uma pasta vazia pode ser legítima — a operadora pode não ter tráfego no mês, ou a
pasta pode existir por padronização e só ser usada em parte do ano. Abortar faria
uma pasta vazia bloquear o mês inteiro. Então: `error` nomeando a pasta, e a
execução segue.
"""

from __future__ import annotations

from pathlib import Path

from comum.config.logger_config import logger


def acusar_expectativa_ausente(pasta_operadora: Path, motivo: str) -> None:
    """
    Registra em `error` que uma pasta de expectativa não rendeu arquivo algum.

    Args:
        pasta_operadora: A pasta varrida, nomeada por extenso no log — é o que
            permite ir direto ao lugar certo no compartilhamento de rede.
        motivo: O que aconteceu com ela ("não existe", "existe, mas nenhum dos N
            arquivos passou nos filtros").
    """

    logger.error(
        f"[Q21] Sem expectativa Vivo em [{pasta_operadora}]: {motivo}. "
        f"As operadoras desta pasta ficam sem comparação — a variação daria 100% "
        f"e elas seriam contestadas indevidamente. Confira o conteúdo da pasta "
        f"antes de considerar a apuração deste mês concluída."
    )
