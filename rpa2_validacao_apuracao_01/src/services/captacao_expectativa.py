"""Etapa 1 do RPA 2: captura a expectativa Vivo e grava diretamente no banco."""

from __future__ import annotations

import csv
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymysql

from comum.config import configuration
from comum.config.logger_config import logger
from comum.dominio.competencia import obter_competencia
from comum.dominio.expectativa import pasta_por_nome
from comum.integracoes.sftp import MAPA_PASTAS, SFTPError, SFTPService


BANCO_EXPECTATIVA = "dev_rpa"
TABELA_EXPECTATIVA = "tbl_rpa_detraf_expectativa_vivo"
PORTA_EXPECTATIVA = 3306
TAMANHO_LOTE = 100
MARCA_RESUMIDO = "_L_"
PASTAS_GRAVADAS_NO_BANCO = {"TLF", "VIVO"}

# Ordem exata das colunas de dados no banco.
# Os arquivos SMS possuem 19 campos e nao trazem Corredor.
# Os demais arquivos esperados possuem os 20 campos abaixo.
COLUNAS_DETRAF = [
    "Credora",
    "Devedora",
    "Referencia",
    "Trafego",
    "POI",
    "Rel",
    "DESC",
    "GH",
    "Chamadas",
    "Minutos",
    "Tarifa",
    "R$_Liq",
    "PIS_Cofins",
    "ICMS",
    "R$_Bruto",
    "CN_RELACIONAMENTO",
    "CBS",
    "IBS_Municipal",
    "IBS_Estadual",
    "Corredor",
]

COLUNAS_BANCO = [
    "tipo_arquivo",
    *COLUNAS_DETRAF,
    "nome_arquivo",
]


@dataclass
class ResultadoCaptacao:
    """O que a etapa fez, para o diagnostico e a parada entre etapas."""

    periodo: str = ""
    baixados: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    origem: str = "SFTP"

    def resumo(self) -> list[str]:
        linhas = [
            f"Origem:                   {self.origem}",
            f"Periodo procurado:        {self.periodo}",
            f"Arquivos gravados:        {len(self.baixados)}",
        ]
        if self.baixados:
            linhas += [f"  {nome}" for nome in sorted(self.baixados)]
        if self.falhas:
            linhas += ["", f"Falhas ({len(self.falhas)}):"]
            linhas += [f"  {falha}" for falha in self.falhas]
        return linhas


def eh_detalhado_do_periodo(nome: str, periodo: str) -> bool:
    if periodo not in nome:
        return False
    if MARCA_RESUMIDO in nome:
        return False
    return Path(nome).stem.upper().endswith("_D")


class _OrigemEmDisco:
    """Diretorio local com a interface esperada da origem SFTP."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)

    def _pasta(self, caminho_remoto: str) -> Path:
        candidata = self.raiz / caminho_remoto.strip("/").split("/")[-1]
        return candidata if candidata.is_dir() else self.raiz

    def origens(self) -> list[tuple[str, str | None]]:
        espelhada = [
            (remoto, destino)
            for remoto, destino in MAPA_PASTAS.items()
            if (self.raiz / remoto.strip("/").split("/")[-1]).is_dir()
        ]
        if espelhada:
            return espelhada

        logger.info(
            "[Expectativa] A origem e um diretorio plano; "
            "o tipo de cada arquivo sera identificado pelo nome."
        )
        return [(str(self.raiz), None)]

    def conectar(self) -> None:
        if not self.raiz.is_dir():
            raise SFTPError(f"[--de-pasta] O diretorio [{self.raiz}] nao existe.")
        logger.info(f"[Expectativa] Origem simulada em disco: [{self.raiz}]")

    def fechar(self) -> None:
        return None

    def listar(self, caminho_remoto: str) -> list[str]:
        pasta = self._pasta(caminho_remoto)
        return [item.name for item in pasta.iterdir() if item.is_file()]

    def baixar(self, caminho_remoto: str, destino: Path) -> Path:
        origem = (
            self._pasta(caminho_remoto.rsplit("/", 1)[0])
            / Path(caminho_remoto).name
        )
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
        return destino


def _obter_variavel(nome: str) -> str:
    valor = os.getenv(nome)
    if not valor or not valor.strip():
        raise RuntimeError(f"Variavel de ambiente ausente ou vazia: {nome}")
    return valor.strip()


def _conectar_banco():
    """Usa a mesma conexao adotada no teste, apontando para dev_rpa."""
    host = _obter_variavel("RPA_DEV_BANCO_ATACADO_HOST")
    usuario = _obter_variavel("RPA_DEV_BANCO_ATACADO_USER")
    senha = _obter_variavel("RPA_DEV_BANCO_ATACADO_PASS")

    logger.info(
        f"[Expectativa] Conectando ao banco de teste | host=[{host}] | "
        f"banco=[{BANCO_EXPECTATIVA}] | tabela=[{TABELA_EXPECTATIVA}]"
    )

    return pymysql.connect(
        host=host,
        user=usuario,
        password=senha,
        port=PORTA_EXPECTATIVA,
        database=BANCO_EXPECTATIVA,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15,
        read_timeout=120,
        write_timeout=120,
    )


def _consultar_estrutura(conexao) -> dict:
    sql = """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
          FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = %s
           AND TABLE_NAME = %s
         ORDER BY ORDINAL_POSITION
    """
    with conexao.cursor() as cursor:
        cursor.execute(sql, (BANCO_EXPECTATIVA, TABELA_EXPECTATIVA))
        resultado = cursor.fetchall()

    if not resultado:
        raise RuntimeError(
            f"Tabela {BANCO_EXPECTATIVA}.{TABELA_EXPECTATIVA} nao encontrada."
        )

    colunas = {item["COLUMN_NAME"]: item for item in resultado}
    colunas_obrigatorias = {*COLUNAS_BANCO, "create_at"}
    ausentes = colunas_obrigatorias - set(colunas)
    if ausentes:
        raise RuntimeError(
            "A tabela nao possui as colunas esperadas: "
            + ", ".join(sorted(ausentes))
            + f" | destino={BANCO_EXPECTATIVA}.{TABELA_EXPECTATIVA}"
        )

    logger.info(
        f"[Expectativa] Estrutura confirmada em "
        f"[{BANCO_EXPECTATIVA}.{TABELA_EXPECTATIVA}]."
    )
    return colunas


def _detectar_encoding(arquivo: Path) -> str:
    dados = arquivo.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            dados.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Nao foi possivel identificar a codificacao de [{arquivo}].")


def _linha_eh_cabecalho(valores: list[str]) -> bool:
    recebido = [str(valor).strip().casefold() for valor in valores]

    if len(recebido) not in (19, 20):
        return False

    esperado = [nome.casefold() for nome in COLUNAS_DETRAF[: len(recebido)]]
    return recebido == esperado


def _ler_linhas_txt(arquivo: Path) -> list[tuple[int, list[str | None]]]:
    """
    Le por posicao e preserva campos vazios existentes.

    - 19 campos: preserva os 19 e define somente Corredor como NULL.
    - 20 campos: preserva todos exatamente como vieram.
    - Campos entre ;; continuam ocupando sua posicao.
    """
    encoding = _detectar_encoding(arquivo)
    linhas: list[tuple[int, list[str | None]]] = []
    contagem = {19: 0, 20: 0}

    with arquivo.open("r", encoding=encoding, newline="") as stream:
        leitor = csv.reader(stream, delimiter=";", quotechar='"')

        for numero_linha, valores in enumerate(leitor, start=1):
            if not valores or all(valor == "" for valor in valores):
                continue

            if numero_linha == 1 and _linha_eh_cabecalho(valores):
                logger.info(f"[Expectativa] [{arquivo.name}] cabecalho ignorado.")
                continue

            quantidade = len(valores)
            if quantidade not in contagem:
                raise ValueError(
                    f"{arquivo.name}: linha {numero_linha} possui {quantidade} "
                    "campos; os layouts aceitos possuem 19 ou 20 campos."
                )

            linha_normalizada: list[str | None] = list(valores)

            if quantidade == 19:
                linha_normalizada.append(None)

            contagem[quantidade] += 1
            linhas.append((numero_linha, linha_normalizada))

    logger.info(
        f"[Expectativa] [{arquivo.name}] leitura concluida | "
        f"linhas=[{len(linhas)}] | layout_19=[{contagem[19]}] | "
        f"layout_20=[{contagem[20]}]"
    )
    return linhas


def _validar_tamanhos(
    valores: list[str | None],
    tipo_arquivo: str,
    nome_arquivo: str,
    colunas: dict,
    numero_linha: int,
) -> None:
    registro = [tipo_arquivo, *valores, nome_arquivo]

    if len(registro) != len(COLUNAS_BANCO):
        raise RuntimeError(
            f"{nome_arquivo}: linha {numero_linha} gerou {len(registro)} valores; "
            f"o INSERT espera {len(COLUNAS_BANCO)}."
        )

    for nome_coluna, valor in zip(COLUNAS_BANCO, registro):
        limite = colunas[nome_coluna]["CHARACTER_MAXIMUM_LENGTH"]
        if limite is None or valor is None:
            continue

        if len(str(valor)) > limite:
            raise ValueError(
                f"{nome_arquivo}: linha {numero_linha}, coluna "
                f"[{nome_coluna}] possui {len(str(valor))} caracteres; "
                f"o banco permite {limite}."
            )


def _dados_ja_existem_no_banco(
    conexao,
    registros: list[tuple],
    tipo_arquivo: str,
    nome_arquivo: str,
) -> bool:
    """Compara todas as colunas de negocio e ignora colunas como create_at."""
    nomes_sql = ", ".join(f"`{nome}`" for nome in COLUNAS_BANCO)
    sql = f"""
        SELECT {nomes_sql}
          FROM `{BANCO_EXPECTATIVA}`.`{TABELA_EXPECTATIVA}`
         WHERE `tipo_arquivo` = %s
           AND `nome_arquivo` = %s
    """

    with conexao.cursor() as cursor:
        cursor.execute(sql, (tipo_arquivo, nome_arquivo))
        existentes = cursor.fetchall()

    if len(existentes) != len(registros):
        return False

    # Counter preserva inclusive a quantidade de linhas repetidas.
    registros_banco = Counter(
        tuple(linha[nome] for nome in COLUNAS_BANCO)
        for linha in existentes
    )
    registros_arquivo = Counter(registros)
    return registros_banco == registros_arquivo


def _gravar_arquivo_no_banco(
    arquivo: Path,
    tipo_arquivo: str,
    nome_arquivo_original: str,
) -> int:
    """Substitui atomicamente no banco todas as linhas do arquivo capturado."""
    linhas = _ler_linhas_txt(arquivo)
    if not linhas:
        logger.warning(
            f"[Expectativa] [{nome_arquivo_original}] nao possui linhas de dados."
        )
        return 0

    conexao = _conectar_banco()
    try:
        colunas = _consultar_estrutura(conexao)
        registros = []

        for numero_linha, valores in linhas:
            _validar_tamanhos(
                valores,
                tipo_arquivo,
                nome_arquivo_original,
                colunas,
                numero_linha,
            )
            registros.append((tipo_arquivo, *valores, nome_arquivo_original))

        if _dados_ja_existem_no_banco(
            conexao,
            registros,
            tipo_arquivo,
            nome_arquivo_original,
        ):
            logger.info(
                f"[Expectativa] Conteudo ja existe integralmente no banco: "
                f"[{tipo_arquivo}/{nome_arquivo_original}] | "
                "nenhuma linha foi regravada."
            )
            return 0

        nomes_sql = ", ".join(f"`{nome}`" for nome in COLUNAS_BANCO)
        marcadores = ", ".join(["%s"] * len(COLUNAS_BANCO))

        sql_delete = f"""
            DELETE FROM `{BANCO_EXPECTATIVA}`.`{TABELA_EXPECTATIVA}`
             WHERE `tipo_arquivo` = %s
               AND `nome_arquivo` = %s
        """
        sql_insert = f"""
            INSERT INTO `{BANCO_EXPECTATIVA}`.`{TABELA_EXPECTATIVA}` (
                {nomes_sql}, `create_at`
            )
            VALUES ({marcadores}, NOW())
        """

        with conexao.cursor() as cursor:
            cursor.execute(sql_delete, (tipo_arquivo, nome_arquivo_original))
            for inicio in range(0, len(registros), TAMANHO_LOTE):
                lote = registros[inicio : inicio + TAMANHO_LOTE]
                cursor.executemany(sql_insert, lote)

        conexao.commit()
        return len(registros)

    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


class CaptacaoExpectativaService:
    """Captura os arquivos e grava diretamente no banco, sem usar a pasta 33."""

    def __init__(self, sftp=None, de_pasta: str | Path | None = None):
        self._sftp = sftp
        self._de_pasta = Path(de_pasta) if de_pasta else None
        self.resultado = ResultadoCaptacao()

    def executar(self, referencia: str | None = None) -> ResultadoCaptacao:
        periodo = referencia or obter_competencia().competencia
        self.resultado = ResultadoCaptacao(periodo=periodo)

        origem = self._resolver_origem()
        if origem is None:
            return self.resultado

        logger.info(
            f"[Expectativa] Procurando arquivos _D de {periodo} em "
            f"{len(MAPA_PASTAS)} pasta(s) de origem."
        )

        try:
            origem.conectar()
        except SFTPError as erro:
            logger.error(f"[Expectativa] {erro}")
            self.resultado.falhas.append(str(erro))
            return self.resultado

        try:
            for caminho_remoto, subpasta in self._origens_de(origem):
                self._trazer_pasta(origem, caminho_remoto, subpasta, periodo)
        finally:
            origem.fechar()

        if not self.resultado.baixados:
            logger.warning(
                f"[Expectativa] Nenhum arquivo _D de {periodo} foi gravado no banco."
            )

        return self.resultado

    @staticmethod
    def _origens_de(origem) -> list[tuple[str, str | None]]:
        if hasattr(origem, "origens"):
            return origem.origens()
        return list(MAPA_PASTAS.items())

    def _resolver_origem(self):
        if self._de_pasta is not None:
            self.resultado.origem = f"disco [{self._de_pasta}]"
            return _OrigemEmDisco(self._de_pasta)

        if self._sftp is not None:
            return self._sftp

        if not configuration.PERMITIR_DOWNLOAD_SFTP:
            logger.warning(
                "[MODO SEGURO] PERMITIR_DOWNLOAD_SFTP esta desligado; "
                "nada sera capturado nem gravado no banco."
            )
            self.resultado.origem = "nenhuma (PERMITIR_DOWNLOAD_SFTP desligado)"
            return None

        return SFTPService(
            host=configuration.SFTP_HOST,
            usuario=configuration.SFTP_USUARIO,
            senha=configuration.SFTP_SENHA,
            porta=configuration.SFTP_PORT,
        )

    def _trazer_pasta(
        self,
        origem,
        caminho_remoto: str,
        subpasta: str | None,
        periodo: str,
    ) -> None:
        try:
            nomes = origem.listar(caminho_remoto)
        except Exception as erro:  # noqa: BLE001
            logger.error(
                f"[Expectativa] Falha ao listar [{caminho_remoto}]: "
                f"{type(erro).__name__}: {erro}"
            )
            self.resultado.falhas.append(
                f"{caminho_remoto}: {type(erro).__name__}: {erro}"
            )
            return

        alvos = [nome for nome in nomes if eh_detalhado_do_periodo(nome, periodo)]

        logger.info(
            f"[Expectativa] {caminho_remoto} -> {subpasta or 'pelo nome'}: "
            f"{len(alvos)} de {len(nomes)} arquivo(s) casam com o filtro."
        )

        for nome in sorted(alvos):
            pasta = subpasta or pasta_por_nome(
                nome,
                list(configuration.PASTAS_EXPECTATIVAS),
            )

            if pasta is None:
                logger.error(
                    f"[Expectativa] Nao foi possivel identificar o tipo de [{nome}]."
                )
                self.resultado.falhas.append(f"{nome}: tipo indefinido")
                continue

            tipo_arquivo = str(pasta).strip().upper()
            if tipo_arquivo not in PASTAS_GRAVADAS_NO_BANCO:
                logger.info(
                    f"[Expectativa] Ignorado [{pasta}/{nome}]: "
                    "somente Vivo e TLF sao gravados no banco."
                )
                continue

            try:
                with tempfile.TemporaryDirectory(
                    prefix="rpa2_expectativa_"
                ) as diretorio_temporario:
                    temporario = Path(diretorio_temporario) / nome
                    origem.baixar(f"{caminho_remoto}/{nome}", temporario)

                    quantidade = _gravar_arquivo_no_banco(
                        arquivo=temporario,
                        tipo_arquivo=tipo_arquivo,
                        nome_arquivo_original=nome,
                    )

            except Exception as erro:  # noqa: BLE001
                logger.error(
                    f"[Expectativa] Falha ao gravar [{pasta}/{nome}] no banco: "
                    f"{type(erro).__name__}: {erro}"
                )
                self.resultado.falhas.append(
                    f"{pasta}/{nome}: {type(erro).__name__}: {erro}"
                )
                continue

            self.resultado.baixados.append(f"{pasta}/{nome}")
            logger.info(
                f"[Expectativa] Gravado no banco: [{pasta}/{nome}] | "
                f"linhas=[{quantidade}] | "
                f"destino=[{BANCO_EXPECTATIVA}.{TABELA_EXPECTATIVA}]"
            )
