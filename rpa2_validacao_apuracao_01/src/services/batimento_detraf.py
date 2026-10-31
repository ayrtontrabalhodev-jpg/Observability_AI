from comum.utils.decoradores import log_execucao
from comum.config.logger_config import logger
from src.services.expectativa import acusar_expectativa_ausente
from pathlib import Path
from comum.config.configuration import (
    ANO_MES_REFERENCIA,
    EXTENSOES_PERMITIDAS,
    CAMINHO_DETRAF_RECEBIDO,
    ARQUIVOS_VALIDADOS,
    EXPECTATIVA_SUBSTRING,
    CAMINHO_EXPECTATIVA_DETRAF,
    PASTAS_EXPECTATIVAS,
    DIRETORIO_SAIDA_VALIDACAO,
)
from comum.arquivos import estrutura_pastas as ep
from comum.arquivos.historico import ValidadorHistoricoRPA
from comum.integracoes.rede import garantir_conexao_autenticada
from src.services.criacao_arquivo_contestacao import CriacaoArquivoContestacao
from comum.dados.repositorio_tabelas import bd_tabelas
from comum.arquivos.gerenciador import carregar_dados
import pandas as pd
#asassaas

class BatimentoDetrafService:
    def __init__(self):
        garantir_conexao_autenticada(CAMINHO_DETRAF_RECEBIDO)
        self.repositorio_tabelas = bd_tabelas
        self.operadoras_sem_detraf: list[str] = []
        self.historico_rpa = ValidadorHistoricoRPA()
        self.criador_contestacao = CriacaoArquivoContestacao()
        #: Resumo da última execução, para a parada entre etapas mostrar.
        self.resumo: list[str] = []

    CHAVE_ARQUIVOS_NAO_IDENTIFICADOS = "OPERADORA_NAO_IDENTIFICADA"

    def _preparar_arquivos_detrafs(self) -> dict[str, list[Path]]:
        """
        Recolhe os Detraf que a validação aprovou, na pasta de SAÍDA.

        🔴 **Defeito corrigido em 2026-08-10.** Este método varria
        ``{operadora}/{ano}/{aaaamm}`` — sem a subpasta ``Detrafs Recebidos``,
        que é onde a validação grava (e onde `validacao_detrafs` procura, por
        `ep.caminho_detrafs_recebidos`). O resultado é que ele **nunca
        encontrava um Detraf**: toda contestação saía com o lado da operadora
        zerado e variação de -100%, sem um único erro no log. Um caminho
        derivado em dois lugares diverge — agora os dois lados usam
        `estrutura_pastas`, e a validação entrega exatamente onde este método lê.

        Returns:
            dict[str, list[Path]]: Nome da operadora -> arquivos aprovados.
        """
        logger.info("Preparando os detrafs para validação...")

        ano_mes = ANO_MES_REFERENCIA

        caminhos_encontrados: dict[str, list[Path]] = {}

        # Dicionário para rastrear a contagem de arquivos válidos por operadora
        arquivos_por_operadora: dict[str, int] = {}

        # Conjunto de extensões permitidas para validação rápida O(1)
        extensoes_validas = EXTENSOES_PERMITIDAS

        logger.info(
            f"Iniciando busca de arquivos para o período {ano_mes} na saída da "
            f"validação: '{DIRETORIO_SAIDA_VALIDACAO}'"
        )

        try:
            com_saida = ep.listar_operadoras_com_saida(
                ano_mes, raiz_saida=DIRETORIO_SAIDA_VALIDACAO
            )

            # "Sem Detraf no mês" continua sendo o complemento das operadoras que
            # existem na árvore de ENTRADA: é ela que diz quem deveria ter
            # enviado. Quem não tem saída ou não enviou, ou foi reprovado na
            # validação — os dois casos precisam aparecer.
            todas = (
                sorted(p.name for p in CAMINHO_DETRAF_RECEBIDO.iterdir() if p.is_dir())
                if CAMINHO_DETRAF_RECEBIDO.is_dir()
                else []
            )
            self.operadoras_sem_detraf.extend(
                operadora for operadora in todas if operadora not in com_saida
            )

            for nome_operadora in com_saida:
                logger.info(f"Varrendo arquivos da operadora: [{nome_operadora}]")

                arquivos_por_operadora[nome_operadora] = 0
                caminhos_encontrados[nome_operadora] = []

                pasta_alvo = ep.caminho_saida_operadora(
                    nome_operadora, ano_mes, raiz_saida=DIRETORIO_SAIDA_VALIDACAO
                )
                if not pasta_alvo.is_dir():
                    continue

                for arquivo in pasta_alvo.iterdir():
                    if not arquivo.is_file():
                        continue

                    # Só o que a validação aprovou. O `_ERRO` e o `_BK` moram na
                    # mesma pasta de saída, e entram aqui se este filtro cair.
                    if not any(
                        sub in arquivo.name for sub in ARQUIVOS_VALIDADOS
                    ):
                        continue

                    if arquivo.suffix.lower() not in extensoes_validas:
                        continue

                    caminhos_encontrados[nome_operadora].append(arquivo)
                    arquivos_por_operadora[nome_operadora] += 1

        except Exception as erro:
            logger.error(f"Erro inesperado durante a varredura dos diretórios: {erro}")
            raise RuntimeError(f"Falha ao mapear arquivos detrafs: {erro}")

        # Gera o log final com os indicadores de volumetria solicitados
        total_operadoras_encontradas = len(arquivos_por_operadora)
        total_arquivos_encontrados = sum(
            len(arquivos) for arquivos in caminhos_encontrados.values()
        )
        logger.info(
            f"Mapeamento concluído com sucesso. "
            f"Total de operadoras processadas com dados: {total_operadoras_encontradas}. "
            f"Total geral de arquivos encontrados: {total_arquivos_encontrados}"
        )

        # Exibe o detalhamento por operadora no log
        for operadora, qtd_arquivos in arquivos_por_operadora.items():
            logger.info(
                f"-> Operadora [{operadora}]: {qtd_arquivos} arquivo(s) encontrado(s)"
            )

        arquivos_filtrados = self.historico_rpa.filtrar_arquivos_novos(
            [
                arquivo
                for arquivos_operadora in caminhos_encontrados.values()
                for arquivo in arquivos_operadora
            ]
        )
        arquivos_filtrados_set = set(arquivos_filtrados)

        return {
            operadora: [
                arquivo for arquivo in arquivos if arquivo in arquivos_filtrados_set
            ]
            for operadora, arquivos in caminhos_encontrados.items()
        }

    def _mapear_arquivos_por_operadora(
        self, lista_arquivos: list[Path]
    ) -> dict[str, list[Path]]:
        """
        Lê uma lista de arquivos e os agrupa em um dicionário mapeando o
        Nome Fantasia da Operadora (chave) para uma lista de Paths (valor).

        Regras de Negócio:
        - Arquivos vazios são ignorados.
        - Varre a coluna 0 até achar o primeiro EOT válido para evitar ler o arquivo todo.
        - Caso possua dados mas nenhum EOT seja mapeado, agrupa em 'OPERADORA_NAO_IDENTIFICADA'.
        """
        from collections import defaultdict

        # O defaultdict elimina a necessidade de checar se a chave já existe no dicionário
        mapa_operadoras: dict[str, list[Path]] = defaultdict(list)

        logger.info(
            f"Iniciando mapeamento de operadoras para {len(lista_arquivos)} arquivo(s)."
        )

        for caminho_arq in lista_arquivos:
            try:
                # 1. Carrega os dados utilizando a função existente do projeto
                df = carregar_dados(caminho_arq)

                # Regra de Negócio 2: Arquivo vazio é ignorado
                if df is None or df.empty:
                    logger.warning(
                        f"Arquivo ignorado por estar vazio ou ilegível: {caminho_arq.name}"
                    )
                    continue

                operadora_encontrada = None

                # Regra de Negócio 1: Varre sequencialmente a coluna 0 (Mais rápido para achar nas primeiras linhas)
                for eot_bruto in df.iloc[:, 0]:
                    if pd.isna(eot_bruto):
                        continue

                    eot_string = str(eot_bruto).strip()
                    if not eot_string:
                        continue

                    # Tenta validar o EOT contra a tbl_anexo5_processado na memória
                    nome_fantasia = self.repositorio_tabelas.validar_eot(eot_string)

                    if nome_fantasia:
                        operadora_encontrada = nome_fantasia
                        # Encontrou? Interrompe o laço de linhas imediatamente para poupar performance!
                        break

                # 2. Classificação do arquivo no dicionário final
                if operadora_encontrada:
                    mapa_operadoras[operadora_encontrada].append(caminho_arq)
                else:
                    # Regra de Negócio 2: Possui linhas mas nenhum EOT foi localizado no banco
                    logger.error(
                        f"Nenhum EOT válido encontrado para o arquivo: {caminho_arq.name}"
                    )
                    mapa_operadoras[self.CHAVE_ARQUIVOS_NAO_IDENTIFICADOS].append(
                        caminho_arq
                    )

            except Exception as e:
                logger.excecao(
                    f"Erro crítico ao tentar mapear operadora do arquivo {caminho_arq.name}: {e}"
                )
                mapa_operadoras[self.CHAVE_ARQUIVOS_NAO_IDENTIFICADOS].append(
                    caminho_arq
                )

        # Converte de volta para um dicionário padrão do Python para o retorno
        return dict(mapa_operadoras)

    def _preparar_arquivos_expectativa(
        self,
    ) -> list[Path]:
        """
        Varre pastas de operadoras específicas dentro do diretório de expectativa
        e retorna os caminhos dos arquivos válidos (CSV/Planilhas) cujo nome contenha
        ao menos uma das substrings informadas.

        Ao final, exibe um resumo com o número de arquivos válidos e inválidos por pasta.

        Args:
            operadoras_alvo (str): Strings de operadoras separadas por vírgula (ex: "Vivo,TLF").
            substrings_validas (str): Substrings de filtro separadas por vírgula (ex: "_D,_D_").

        Returns:
            list[Path]: Lista com os caminhos completos dos arquivos que passaram nos filtros.
        """
        logger.info("Preparando os arquivos de expectativa para validação...")

        caminhos_encontrados: list[Path] = []
        extensoes_validas = EXTENSOES_PERMITIDAS

        # Validação de segurança do diretório raiz de expectativa.
        #
        # A variável agora é `None` quando não configurada. Antes era `Path(".")`,
        # e esta guarda passava — o diretório atual existe e é um diretório —,
        # fazendo o robô varrer o CWD e concluir "nenhum arquivo" sem erro.
        if CAMINHO_EXPECTATIVA_DETRAF is None:
            raise FileNotFoundError(
                "CAMINHO_EXPECTATIVA_DETRAF não está configurado. É a raiz da "
                "expectativa Vivo (Detrafs Enviados); sem ela não há com o que "
                "comparar os arquivos das operadoras."
            )

        if (
            not CAMINHO_EXPECTATIVA_DETRAF.exists()
            or not CAMINHO_EXPECTATIVA_DETRAF.is_dir()
        ):
            raise FileNotFoundError(
                f"O caminho de expectativa não foi encontrado ou não é um diretório: '{CAMINHO_EXPECTATIVA_DETRAF}'"
            )

        try:
            # 2. Iterar apenas sobre as operadoras solicitadas na lista
            for pasta in PASTAS_EXPECTATIVAS:
                # A expectativa aprovada também vem da SAÍDA da validação, e não
                # da pasta de entrada — mesma correção do lado do Detraf. A
                # entrada continua sendo quem responde "esta pasta existe?", que
                # é a pergunta da Q21.
                pasta_operadora = ep.caminho_saida_expectativa(
                    pasta, ANO_MES_REFERENCIA, raiz_saida=DIRETORIO_SAIDA_VALIDACAO
                )
                pasta_de_entrada = CAMINHO_EXPECTATIVA_DETRAF / pasta

                # Inicializa os contadores para o resumo final desta pasta
                arquivos_validos_pasta = 0
                arquivos_invalidos_pasta = 0

                if pasta_operadora.exists() and pasta_operadora.is_dir():

                    # Varre os arquivos diretamente na pasta da operadora
                    for arquivo in pasta_operadora.iterdir():
                        if arquivo.is_file():
                            nome_arquivo = arquivo.name
                            extensao = arquivo.suffix.lower()

                            # Ignora arquivos que não contêm substrings válidas
                            deve_ignorar = not any(
                                sub in nome_arquivo for sub in ARQUIVOS_VALIDADOS
                            )

                            if deve_ignorar:
                                continue

                            # Critério 1: Validar se a extensão é permitida
                            # Critério 2: Validar se o nome do arquivo contém alguma das substrings alvo
                            possui_extensao_valida = extensao in extensoes_validas
                            possui_substring = any(
                                sub in nome_arquivo for sub in EXPECTATIVA_SUBSTRING
                            )

                            if possui_extensao_valida and possui_substring:
                                caminhos_encontrados.append(arquivo)
                                arquivos_validos_pasta += 1
                            else:
                                # Contabiliza como inválido/ignorado conforme a regra do escopo
                                arquivos_invalidos_pasta += 1

                    # Exibe o resumo consolidado por pasta conforme solicitado (apenas se a pasta existir)
                    logger.info(
                        f"Pasta [{pasta}] processada -> "
                        f"Válidos: {arquivos_validos_pasta} | Inválidos/Ignorados: {arquivos_invalidos_pasta}"
                    )

                    if arquivos_validos_pasta == 0:
                        acusar_expectativa_ausente(
                            pasta_de_entrada,
                            "existe, mas nenhum arquivo passou nos filtros",
                        )
                else:
                    # A pasta de saída não existir significa que a validação não
                    # aprovou nada dali — o alerta precisa nomear a pasta de
                    # ENTRADA, que é a que o operador conhece e vai conferir.
                    acusar_expectativa_ausente(
                        pasta_de_entrada,
                        "não tem nenhum arquivo aprovado pela validação",
                    )

        except Exception as erro:
            logger.error(
                f"Erro inesperado durante a varredura das expectativas: {erro}"
            )
            raise RuntimeError(f"Falha ao mapear arquivos de expectativa: {erro}")

        logger.info(
            f"Mapeamento de expectativa concluído. Total geral de arquivos válidos: {len(caminhos_encontrados)}"
        )
        return self.historico_rpa.filtrar_arquivos_novos(caminhos_encontrados)

    @log_execucao
    def executar(self):
        logger.info("Iniciando processo de batimento dos arquivos Detraf...")
        arquivos_detraf = self._preparar_arquivos_detrafs()
        arquivos_expectativa = self._preparar_arquivos_expectativa()

        if not arquivos_detraf:
            logger.warning(
                "Nenhum arquivo de detraf encontrado para o batimento. Verifique os logs anteriores para detalhes."
            )
        if not arquivos_expectativa:
            logger.warning(
                "Nenhum arquivo de expectativa encontrado para o batimento. Verifique os logs anteriores para detalhes."
            )

        arquivos_detraf_mapeados = (
            arquivos_detraf  # Ja pega o nome da operadora pelo nome da pasta
        )
        arquivos_expectativa_mapeados = self._mapear_arquivos_por_operadora(
            arquivos_expectativa
        )

        self.criador_contestacao.apurar_contestacao(
            arquivos_detraf_mapeados,
            arquivos_expectativa_mapeados,
        )

        # 🔴 2026-08-17: faltava isto. `_preparar_arquivos_detrafs` e
        # `_preparar_arquivos_expectativa` FILTRAM pelo histórico
        # (`filtrar_arquivos_novos`), mas nada aqui GRAVAVA o resultado — ao
        # contrário da validação, que registra em
        # `_salvar_historico_arquivos_processados`. Sem isso, toda reexecução
        # no mesmo mês via os mesmos arquivos de `_SAIDA` como "novos" e
        # reinseria a mesma contestação em `tbl_rpa_log_detraf_despesa_contestacao`
        # — visto de verdade em 2026-08-17, duas rodadas seguidas duplicando as
        # 23 operadoras apuradas.
        arquivos_processados = [
            arquivo
            for arquivos in arquivos_detraf_mapeados.values()
            for arquivo in arquivos
        ] + [
            arquivo
            for arquivos in arquivos_expectativa_mapeados.values()
            for arquivo in arquivos
        ]
        if arquivos_processados:
            self.historico_rpa.registrar_arquivos(
                lista_caminhos=arquivos_processados, status_valido=True
            )

        operadoras = sorted(
            set(arquivos_detraf_mapeados) | set(arquivos_expectativa_mapeados)
        )
        self.resumo = [
            f"Operadoras apuradas:      {len(operadoras)}",
            "",
            "O resultado é a TABELA `tbl_rpa_log_detraf_despesa_contestacao`,",
            "não um arquivo — a Base de Contestação virou tabela em 2026-08-04.",
            "",
            "Próximo passo é humano: o analista sinaliza no WebFat o que",
            "contestar e se haverá retenção. Só então o RPA 3 tem o que fazer.",
        ]
        if operadoras:
            self.resumo += ["", "Operadoras: " + ", ".join(operadoras)]
