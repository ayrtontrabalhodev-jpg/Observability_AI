import re
from datetime import datetime
from pathlib import Path

import pandas as pd


# ==================================================
# CAMINHOS
# ==================================================

diretorio_raiz = Path(__file__).resolve().parent.parent.parent
diretorio_base = diretorio_raiz / "base_tratada_rifaina"

arquivo_padroes = diretorio_base / "rifaina_padroes_falha.csv"
arquivo_classificacao = diretorio_base / "rifaina_classificacao_falhas.csv"
arquivo_resumo = diretorio_base / "resumo_classificacao.csv"


# ==================================================
# CATEGORIAS DISPONÍVEIS
# ==================================================

CATEGORIAS_VALIDAS = [
    "Timeout",
    "Autenticacao",
    "WebDriver",
    "Interface Web",
    "Conexao",
    "Capacidade",
    "Codigo Python",
    "Arquivo",
    "Banco de Dados",
    "Regra de Negocio",
    "Sistema Externo",
    "Processamento",
    "Desconhecido",
]


# ==================================================
# LEITURA
# ==================================================

def carregar_padroes_falha():
    """
    Carrega os padrões gerados pelo tratamento.
    """

    if not arquivo_padroes.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {arquivo_padroes}"
        )

    base = pd.read_csv(
        arquivo_padroes,
        encoding="utf-8-sig",
        low_memory=False,
    )

    if base.empty:
        print("[CLASSIFICAÇÃO] A base de padrões está vazia.")
        return pd.DataFrame()

    colunas_obrigatorias = {
        "id_padrao",
        "descricao_normalizada",
        "quantidade_ocorrencias",
        "exemplo_descricao_original",
    }

    colunas_ausentes = colunas_obrigatorias - set(base.columns)

    if colunas_ausentes:
        raise ValueError(
            "Colunas ausentes no arquivo de padrões: "
            + ", ".join(sorted(colunas_ausentes))
        )

    return base


# ==================================================
# FUNÇÕES AUXILIARES
# ==================================================

def contem_padrao(texto, padroes):
    """
    Retorna True quando algum padrão estiver
    presente no texto.
    """

    return any(
        re.search(padrao, texto, flags=re.IGNORECASE)
        for padrao in padroes
    )


def classificar_falha_completa(
    descricao_original,
    descricao_normalizada="",
):
    """
    Classifica uma falha utilizando prioritariamente
    a descrição original.

    Retorna:
        categoria
        subcategoria
        causa
        acao
        criticidade
        confianca
        status_validacao
        observacao
    """

    original = str(descricao_original).strip()
    normalizada = str(descricao_normalizada).strip()

    texto = f"{original} {normalizada}".lower()

    # ==================================================
    # 1. ERRO DE CÓDIGO PYTHON
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"missing 1 required positional argument",
            r"\btypeerror\b",
            r"\battributeerror\b",
            r"\bkeyerror\b",
            r"\bvalueerror\b",
            r"\bnameerror\b",
            r"\bindexerror\b",
            r"object has no attribute",
            r"is not defined",
        ],
    ):
        return {
            "categoria": "Codigo Python",
            "subcategoria": "Erro de implementacao ou assinatura",
            "causa": (
                "Falha identificada no código Python ou "
                "na chamada de uma função."
            ),
            "acao": (
                "Corrigir a assinatura ou chamada indicada "
                "no traceback e executar teste da etapa afetada."
            ),
            "criticidade": "Alta",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "Classificação automática baseada em exceção "
                "explícita do Python."
            ),
        }

    # ==================================================
    # 2. API OU GATEWAY EXTERNO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"502 server error",
            r"bad gateway",
        ],
    ):
        return {
            "categoria": "Sistema Externo",
            "subcategoria": "API HTTP 502",
            "causa": (
                "A API ou gateway externo retornou HTTP 502. "
                "A causa interna do serviço não foi confirmada."
            ),
            "acao": (
                "Validar disponibilidade da API e do gateway, "
                "consultar os logs do serviço e reprocessar "
                "após a normalização."
            ),
            "criticidade": "Alta",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "O código HTTP 502 está explícito na descrição."
            ),
        }

    # ==================================================
    # 3. CONEXÃO REINICIADA OU INTERROMPIDA
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"err_connection_reset",
            r"connectionreseterror",
            r"connection reset",
            r"connection aborted",
            r"forcibly closed by the remote host",
        ],
    ):
        return {
            "categoria": "Conexao",
            "subcategoria": "Conexao reiniciada",
            "causa": (
                "A conexão foi encerrada ou reiniciada durante "
                "o acesso ao sistema."
            ),
            "acao": (
                "Validar rede, proxy e disponibilidade do sistema. "
                "Reprocessar somente após confirmar estabilidade."
            ),
            "criticidade": "Alta",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A interrupção da conexão está explícita na mensagem."
            ),
        }

    # ==================================================
    # 4. ABA DO NAVEGADOR ENCERRADA
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"tab crashed",
        ],
    ):
        return {
            "categoria": "WebDriver",
            "subcategoria": "Aba do Chrome encerrada",
            "causa": (
                "A aba do navegador encerrou durante a automação. "
                "A causa de infraestrutura ainda precisa ser confirmada."
            ),
            "acao": (
                "Verificar memória, CPU, logs do Chrome e compatibilidade "
                "entre Chrome e ChromeDriver. Reiniciar a sessão."
            ),
            "criticidade": "Alta",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A mensagem tab crashed identifica a falha "
                "do navegador."
            ),
        }

    # ==================================================
    # 5. SESSÃO DO WEBDRIVER NÃO CRIADA
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"session not created",
            r"chrome instance exited",
        ],
    ):
        return {
            "categoria": "WebDriver",
            "subcategoria": "Sessao nao criada",
            "causa": (
                "O Chrome encerrou antes que a sessão do "
                "WebDriver fosse criada."
            ),
            "acao": (
                "Analisar o log detalhado do ChromeDriver, "
                "compatibilidade de versões, perfil do navegador "
                "e recursos disponíveis na máquina."
            ),
            "criticidade": "Alta",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A falha de criação da sessão está explícita."
            ),
        }

    # ==================================================
    # 6. CLIQUE INTERCEPTADO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"element click intercepted",
        ],
    ):
        return {
            "categoria": "Interface Web",
            "subcategoria": "Clique interceptado",
            "causa": (
                "Outro elemento da página bloqueou o componente "
                "que deveria receber o clique."
            ),
            "acao": (
                "Tratar ou fechar o modal, aguardar a invisibilidade "
                "do bloqueio e repetir o clique somente depois."
            ),
            "criticidade": "Media",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A mensagem element click intercepted identifica "
                "diretamente a causa observada."
            ),
        }

    # ==================================================
    # 7. ELEMENTO NÃO INTERAGÍVEL
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"element not interactable",
        ],
    ):
        return {
            "categoria": "Interface Web",
            "subcategoria": "Elemento nao interagivel",
            "causa": (
                "O elemento foi localizado, mas não estava disponível "
                "para interação no momento da ação."
            ),
            "acao": (
                "Aguardar o elemento ficar visível e clicável, "
                "validar frame, aba e seletor utilizado."
            ),
            "criticidade": "Media",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A condição element not interactable está explícita."
            ),
        }

    # ==================================================
    # 8. TIMEOUT
    # Deve vir antes de autenticação e WebDriver.
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"timeout ao fazer login",
            r"\btimeout\b",
            r"timed out",
            r"timeoutexception",
            r"transaction timed out",
            r"read timeout",
        ],
    ):
        if "login" in texto:
            subcategoria = "Timeout de login"
            causa = (
                "O login no GPS não foi concluído dentro do "
                "tempo configurado. Não existe evidência de "
                "credencial inválida."
            )
            acao = (
                "Validar disponibilidade e tempo de resposta do GPS, "
                "carregamento da tela e limite de espera antes "
                "do reprocessamento."
            )

        elif "transaction timed out" in texto:
            subcategoria = "Timeout transacional"
            causa = (
                "A transação excedeu o tempo máximo configurado."
            )
            acao = (
                "Analisar o tempo de execução da operação, "
                "disponibilidade da plataforma e logs da transação."
            )

        else:
            subcategoria = "Timeout de comunicacao"
            causa = (
                "A operação excedeu o limite de tempo configurado. "
                "A causa raiz exige análise do componente afetado."
            )
            acao = (
                "Verificar latência, disponibilidade e logs correlatos. "
                "Revisar o limite somente após identificar a causa."
            )

        return {
            "categoria": "Timeout",
            "subcategoria": subcategoria,
            "causa": causa,
            "acao": acao,
            "criticidade": "Alta",
            "confianca": 0.98,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "Timeout explicitamente identificado na descrição."
            ),
        }

    # ==================================================
    # 9. RESULTADO OU PÁGINA NÃO CARREGOU
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"a busca pela instancia .* nao carregou",
            r"nao carregou e nao apresentou mensagem",
        ],
    ):
        return {
            "categoria": "Interface Web",
            "subcategoria": "Pagina ou resultado nao carregou",
            "causa": (
                "A busca no GPS não carregou e a plataforma "
                "não retornou uma mensagem diagnóstica."
            ),
            "acao": (
                "Validar carregamento da página, resposta da consulta "
                "e elementos esperados. Ampliar o log para registrar "
                "URL, seletor e evidência visual."
            ),
            "criticidade": "Media",
            "confianca": 0.90,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A falha observada está no carregamento da página, "
                "mas a causa raiz não está confirmada."
            ),
        }

    # ==================================================
    # 10. GRAU MÁXIMO EXCEDIDO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"grau max.*excedido",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "Grau maximo excedido",
            "causa": (
                "O pedido excedeu o limite de pontos aceito "
                "pela regra de negócio."
            ),
            "acao": (
                "Revisar os dados e a pontuação do pedido e "
                "encaminhar para o tratamento funcional previsto."
            ),
            "criticidade": "Media",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A regra funcional está explícita na descrição."
            ),
        }

    # ==================================================
    # 11. COBERTURA
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"nao foi encontrada rede de cobertura",
            r"check coverage",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "Cobertura indisponivel ou inconsistente",
            "causa": (
                "A tecnologia informada não possui cobertura "
                "compatível no endereço consultado."
            ),
            "acao": (
                "Validar endereço, tecnologia e disponibilidade de "
                "cobertura. Corrigir os dados antes do reprocessamento."
            ),
            "criticidade": "Media",
            "confianca": 0.98,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A inconsistência de cobertura está descrita "
                "explicitamente."
            ),
        }

    # ==================================================
    # 12. ATIVIDADES NÃO GERADAS OU AGENDADAS
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"atividades devem .*geradas e agendadas antes de enviar a ordem",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "Atividades nao geradas ou agendadas",
            "causa": (
                "A ordem foi enviada antes de as atividades "
                "obrigatórias serem geradas e agendadas."
            ),
            "acao": (
                "Gerar e agendar as atividades obrigatórias antes "
                "do envio da ordem e reprocessar."
            ),
            "criticidade": "Media",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A condição funcional está explícita na mensagem."
            ),
        }

    # ==================================================
    # 13. PRODUTO OBRIGATÓRIO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"cliente ativo com protocolo de voz sip",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "Produto obrigatorio ausente",
            "causa": (
                "A regra exige produto de banda larga mínimo "
                "para cliente ativo com voz SIP."
            ),
            "acao": (
                "Validar a composição do pedido e seguir a "
                "orientação funcional ou do backoffice."
            ),
            "criticidade": "Media",
            "confianca": 0.99,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A exigência do produto está explícita na descrição."
            ),
        }

    # ==================================================
    # 14. ENDEREÇO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"duplicate address",
            r"duplicar endereco",
            r"writerecord.*cut address",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "Duplicidade ou atualizacao de endereco",
            "causa": (
                "A plataforma rejeitou ou não concluiu a "
                "gravação do endereço."
            ),
            "acao": (
                "Validar endereço existente, critérios de busca "
                "e dados obrigatórios antes do reprocessamento."
            ),
            "criticidade": "Media",
            "confianca": 0.94,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "Classificação fundamentada na etapa funcional "
                "de endereço."
            ),
        }

    # ==================================================
    # 15. VALIDAÇÃO DOS DADOS DO PEDIDO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"data validation manager",
            r"iss validation",
            r"fins validation service",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "Validacao de dados do pedido",
            "causa": (
                "A plataforma rejeitou os dados durante uma "
                "validação funcional do pedido."
            ),
            "acao": (
                "Identificar a mensagem funcional final, corrigir "
                "os dados apontados e reprocessar após validação."
            ),
            "criticidade": "Media",
            "confianca": 0.94,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "A etapa de validação está explícita, mas os dados "
                "específicos devem ser confirmados."
            ),
        }

    # ==================================================
    # 16. BUSINESS EXCEPTION
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"business exception",
            r"businessexception",
            r"sbl-bpr",
            r"wf_err",
        ],
    ):
        return {
            "categoria": "Regra de Negocio",
            "subcategoria": "BusinessException da plataforma",
            "causa": (
                "A plataforma retornou uma exceção de regra ou "
                "fluxo. A mensagem funcional final deve determinar "
                "a causa específica."
            ),
            "acao": (
                "Extrair e priorizar a última mensagem funcional "
                "da cadeia SBL ou WF, corrigir os dados e reprocessar."
            ),
            "criticidade": "Media",
            "confianca": 0.88,
            "status_validacao": "Validado Automaticamente",
            "observacao": (
                "Categoria validada; causa detalhada ainda depende "
                "da última mensagem funcional da plataforma."
            ),
        }

    # ==================================================
    # 17. BUSCA REINS NÃO CONCLUÍDA
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"falhou na busca do reins",
        ],
    ):
        return {
            "categoria": "Processamento",
            "subcategoria": "Busca REINS nao concluida",
            "causa": (
                "O log registra a falha final da busca REINS, "
                "mas não apresenta a causa raiz."
            ),
            "acao": (
                "Correlacionar o ID e o horário com os logs "
                "anteriores da mesma instância para encontrar "
                "a falha primária."
            ),
            "criticidade": "Media",
            "confianca": 0.82,
            "status_validacao": "Revisao Humana",
            "observacao": (
                "A categoria representa a etapa final. "
                "A causa raiz ainda precisa ser localizada."
            ),
        }

    # ==================================================
    # 18. FALHA GENÉRICA DE PROCESSAMENTO
    # ==================================================

    if contem_padrao(
        texto,
        [
            r"falhou na busca",
            r"processamento.*falhou",
            r"erro na etapa",
        ],
    ):
        return {
            "categoria": "Processamento",
            "subcategoria": "Etapa nao concluida",
            "causa": (
                "O log informa falha na etapa, mas não apresenta "
                "evidência suficiente da causa primária."
            ),
            "acao": (
                "Correlacionar os eventos anteriores da mesma "
                "instância e ampliar o log da exceção original."
            ),
            "criticidade": "Media",
            "confianca": 0.72,
            "status_validacao": "Revisao Humana",
            "observacao": (
                "Classificação provisória por consequência."
            ),
        }

    # ==================================================
    # SEM EVIDÊNCIA SUFICIENTE
    # ==================================================

    return {
        "categoria": "Desconhecido",
        "subcategoria": "Evidencia insuficiente",
        "causa": (
            "A descrição não fornece evidência suficiente "
            "para determinar a causa."
        ),
        "acao": (
            "Correlacionar com outros logs da mesma instância, "
            "horário e componente."
        ),
        "criticidade": "Revisar",
        "confianca": 0.30,
        "status_validacao": "Revisao Humana",
        "observacao": (
            "Necessária classificação humana antes do treinamento."
        ),
    }




# ==================================================
# CLASSIFICAÇÃO POR REGRAS
# ==================================================

def sugerir_categoria(
    descricao_original,
    descricao_normalizada="",
):
    """
    Sugere uma categoria usando principalmente
    a descrição original.

    Essa sugestão auxilia na criação da primeira
    base validada. Depois, o modelo treinado será
    responsável por classificar novas mensagens.
    """

    texto_original = str(
        descricao_original
    ).strip().lower()

    texto_normalizado = str(
        descricao_normalizada
    ).strip().lower()

    texto = (
        f"{texto_original} "
        f"{texto_normalizado}"
    )

    # 1. Erros objetivos de código Python
    if contem_padrao(
        texto,
        [
            r"missing 1 required positional argument",
            r"\btypeerror\b",
            r"\battributeerror\b",
            r"\bkeyerror\b",
            r"\bvalueerror\b",
            r"\bnameerror\b",
        ],
    ):
        return "Codigo Python"

    # 2. API ou gateway externo
    if contem_padrao(
        texto,
        [
            r"502 server error",
            r"bad gateway",
        ],
    ):
        return "Sistema Externo"

    # 3. Conexão reiniciada ou interrompida
    if contem_padrao(
        texto,
        [
            r"err_connection_reset",
            r"connectionreseterror",
            r"connection reset",
            r"connection aborted",
            r"forcibly closed by the remote host",
        ],
    ):
        return "Conexao"

    # 4. WebDriver e navegador
    if contem_padrao(
        texto,
        [
            r"session not created",
            r"chrome instance exited",
            r"tab crashed",
            r"browser not reachable",
            r"chrome not reachable",
            r"invalid session id",
        ],
    ):
        return "WebDriver"

    # 5. Interface web
    if contem_padrao(
        texto,
        [
            r"element click intercepted",
            r"element not interactable",
            r"stale element",
            r"no such element",
            r"unable to locate element",
            r"nao carregou e nao apresentou mensagem",
        ],
    ):
        return "Interface Web"

    # 6. Timeout
    if contem_padrao(
        texto,
        [
            r"timeout ao fazer login",
            r"\btimeout\b",
            r"timed out",
            r"timeoutexception",
            r"transaction timed out",
            r"read timeout",
        ],
    ):
        return "Timeout"

    # 7. Regras funcionais da plataforma
    if contem_padrao(
        texto,
        [
            r"grau max.*excedido",
            r"nao foi encontrada rede de cobertura",
            r"check coverage",
            r"atividades devem .*geradas e agendadas",
            r"cliente ativo com protocolo de voz sip",
            r"duplicate address",
            r"data validation manager",
            r"iss validation",
            r"fins validation service",
            r"business exception",
            r"sbl-bpr",
            r"wf_err",
        ],
    ):
        return "Regra de Negocio"

    # 8. Mensagens finais que não informam a causa
    if contem_padrao(
        texto,
        [
            r"falhou na busca do reins",
            r"falhou na busca",
            r"processamento.*falhou",
        ],
    ):
        return "Processamento"

    return "Desconhecido"

# ==================================================
# CRITICIDADE SUGERIDA
# ==================================================

def sugerir_criticidade(categoria, quantidade):
    """
    Sugere criticidade usando categoria e frequência.

    Essa sugestão também deve ser validada.
    """

    categorias_altas = {
        "Banco de Dados",
        "Codigo Python",
        "Autenticacao",
        "Conexao",
    }

    categorias_medias = {
        "Timeout",
        "WebDriver",
        "Interface Web",
        "Capacidade",
        "Sistema Externo",
        "Processamento",
        "Regra de Negocio",
        "Arquivo",
    }

    if categoria in categorias_altas:
        return "Alta"

    if categoria in categorias_medias and quantidade >= 5:
        return "Alta"

    if categoria in categorias_medias:
        return "Media"

    return "Revisar"


# ==================================================
# CONFIANÇA DA REGRA
# ==================================================

def sugerir_confianca(categoria):
    """
    Fornece uma confiança inicial da regra.

    Não representa a probabilidade de um modelo
    de Machine Learning.
    """

    confiancas = {
        "Codigo Python": 0.95,
        "Autenticacao": 0.90,
        "WebDriver": 0.90,
        "Interface Web": 0.90,
        "Conexao": 0.90,
        "Banco de Dados": 0.90,
        "Arquivo": 0.85,
        "Capacidade": 0.90,
        "Timeout": 0.95,
        "Regra de Negocio": 0.85,
        "Sistema Externo": 0.75,
        "Processamento": 0.75,
        "Desconhecido": 0.00,
    }

    return confiancas.get(categoria, 0.00)


# ==================================================
# PRESERVAÇÃO DA VALIDAÇÃO HUMANA
# ==================================================

def carregar_validacoes_existentes():
    """
    Carrega classificações anteriores para não
    apagar validações humanas em novas execuções.
    """

    if not arquivo_classificacao.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(
            arquivo_classificacao,
            encoding="utf-8-sig",
            low_memory=False,
        )

    except Exception as erro:
        print(
            f"[CLASSIFICAÇÃO] Não foi possível carregar "
            f"as validações existentes: {erro}"
        )

        return pd.DataFrame()


def preservar_validacoes(base_nova, base_anterior):
    """
    Preserva validações humanas já preenchidas.

    Uma validação humana tem prioridade sobre
    a classificação automática.
    """

    if base_anterior.empty:
        return base_nova

    campos_humanos = [
        "categoria_validada",
        "subcategoria_validada",
        "causa_confirmada",
        "acao_recomendada",
        "criticidade_validada",
        "validado_por",
        "data_validacao",
        "observacao_validacao",
        "status_validacao",
    ]

    campos_existentes = [
        campo
        for campo in campos_humanos
        if campo in base_anterior.columns
    ]

    if not campos_existentes:
        return base_nova

    validacoes = base_anterior[
        ["descricao_normalizada"] + campos_existentes
    ].drop_duplicates(
        subset=["descricao_normalizada"],
        keep="last",
    )

    base_nova = base_nova.merge(
        validacoes,
        on="descricao_normalizada",
        how="left",
        suffixes=("", "_anterior"),
    )

    for campo in campos_existentes:
        campo_anterior = f"{campo}_anterior"

        if campo_anterior not in base_nova.columns:
            continue

        valores_anteriores = base_nova[
            campo_anterior
        ]

        # Preserva somente validações humanas.
        if "status_validacao_anterior" in base_nova.columns:
            mascara_humana = (
                base_nova[
                    "status_validacao_anterior"
                ]
                .astype(str)
                .str.strip()
                .eq("Validado")
            )
        else:
            mascara_humana = pd.Series(
                False,
                index=base_nova.index,
            )

        mascara_valor = (
            valores_anteriores.notna()
            & valores_anteriores
            .astype(str)
            .str.strip()
            .ne("")
        )

        mascara = mascara_humana & mascara_valor

        base_nova.loc[
            mascara,
            campo,
        ] = valores_anteriores[
            mascara
        ]

        base_nova = base_nova.drop(
            columns=[campo_anterior]
        )

    return base_nova

# ==================================================
# CRIAÇÃO DA BASE DE CLASSIFICAÇÃO
# ==================================================

def criar_classificacao_inicial():
    """
    Gera a classificação completa dos padrões.

    Campos preenchidos automaticamente:

        categoria_sugerida
        subcategoria_sugerida
        confianca_regra
        criticidade_sugerida
        categoria_validada
        causa_confirmada
        acao_recomendada
        criticidade_validada
        validado_por
        data_validacao
        observacao_validacao
        status_validacao
    """

    base = carregar_padroes_falha()

    if base.empty:
        return pd.DataFrame()

    base_anterior = carregar_validacoes_existentes()

    resultados = base.apply(
        lambda linha: classificar_falha_completa(
            descricao_original=linha.get(
                "exemplo_descricao_original",
                "",
            ),
            descricao_normalizada=linha.get(
                "descricao_normalizada",
                "",
            ),
        ),
        axis=1,
    )

    base["categoria_sugerida"] = resultados.apply(
        lambda resultado: resultado["categoria"]
    )

    base["subcategoria_sugerida"] = resultados.apply(
        lambda resultado: resultado["subcategoria"]
    )

    base["confianca_regra"] = resultados.apply(
        lambda resultado: resultado["confianca"]
    )

    base["criticidade_sugerida"] = resultados.apply(
        lambda resultado: resultado["criticidade"]
    )

    # A categoria validada recebe inicialmente
    # a categoria recomendada pela regra.
    base["categoria_validada"] = resultados.apply(
        lambda resultado: resultado["categoria"]
    )

    base["subcategoria_validada"] = resultados.apply(
        lambda resultado: resultado["subcategoria"]
    )

    # A coluna já existente é mantida, mas deixa claro
    # quando a causa ainda não está realmente confirmada.
    base["causa_confirmada"] = resultados.apply(
        lambda resultado: resultado["causa"]
    )

    base["acao_recomendada"] = resultados.apply(
        lambda resultado: resultado["acao"]
    )

    base["criticidade_validada"] = resultados.apply(
        lambda resultado: resultado["criticidade"]
    )

    base["validado_por"] = resultados.apply(
        lambda resultado: (
            "Motor de regras RIFAINA"
            if resultado["status_validacao"]
            == "Validado Automaticamente"
            else ""
        )
    )

    data_atual = datetime.now().strftime(
        "%Y-%m-%d"
    )

    base["data_validacao"] = resultados.apply(
        lambda resultado: (
            data_atual
            if resultado["status_validacao"]
            == "Validado Automaticamente"
            else ""
        )
    )

    base["observacao_validacao"] = resultados.apply(
        lambda resultado: resultado["observacao"]
    )

    base["status_validacao"] = resultados.apply(
        lambda resultado: resultado["status_validacao"]
    )

    base["data_classificacao"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Preserva uma validação humana feita anteriormente.
    base = preservar_validacoes(
        base_nova=base,
        base_anterior=base_anterior,
    )

    base = base.sort_values(
        by=[
            "quantidade_ocorrencias",
            "confianca_regra",
        ],
        ascending=[
            False,
            False,
        ],
    ).reset_index(drop=True)

    base["id_prioridade"] = range(
        1,
        len(base) + 1,
    )

    colunas_principais = [
        "id_prioridade",
        "id_padrao",
        "descricao_normalizada",
        "quantidade_ocorrencias",
        "primeira_ocorrencia",
        "ultima_ocorrencia",
        "rpas",
        "exemplo_descricao_original",
        "categoria_sugerida",
        "subcategoria_sugerida",
        "confianca_regra",
        "criticidade_sugerida",
        "categoria_validada",
        "subcategoria_validada",
        "causa_confirmada",
        "acao_recomendada",
        "criticidade_validada",
        "validado_por",
        "data_validacao",
        "observacao_validacao",
        "status_validacao",
        "data_classificacao",
    ]

    for coluna in colunas_principais:
        if coluna not in base.columns:
            base[coluna] = ""

    return base[colunas_principais]

# ==================================================
# RESUMO
# ==================================================

def criar_resumo_classificacao(base):
    """
    Cria os indicadores da classificação.
    """

    if base.empty:
        return {}

    return {
        "data_processamento": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "total_padroes": len(base),
        "total_ocorrencias": int(
            base["quantidade_ocorrencias"].sum()
        ),
        "categorias_validadas": int(
            base["categoria_validada"].nunique()
        ),
        "padroes_validados_automaticamente": int(
            (
                base["status_validacao"]
                == "Validado Automaticamente"
            ).sum()
        ),
        "padroes_revisao_humana": int(
            (
                base["status_validacao"]
                == "Revisao Humana"
            ).sum()
        ),
        "padroes_validados_humanamente": int(
            (
                base["status_validacao"]
                == "Validado"
            ).sum()
        ),
        "padroes_desconhecidos": int(
            (
                base["categoria_validada"]
                == "Desconhecido"
            ).sum()
        ),
    }

# ==================================================
# SALVAMENTO
# ==================================================

def salvar_csv_seguro(dataframe, caminho_arquivo):
    """
    Salva o CSV por meio de arquivo temporário.
    """

    diretorio_base.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho_temporario = caminho_arquivo.with_suffix(
        ".tmp"
    )

    dataframe.to_csv(
        caminho_temporario,
        index=False,
        encoding="utf-8-sig",
    )

    caminho_temporario.replace(
        caminho_arquivo
    )


# ==================================================
# FUNÇÃO PRINCIPAL
# ==================================================

def classificar_falhas_rifaina():
    """
    Executa a classificação automática dos padrões
    de falha do RIFAINA.

    Gera:
        rifaina_classificacao_falhas.csv
        resumo_classificacao.csv
    """

    print("\n========================================")
    print("CLASSIFICAÇÃO DAS FALHAS RIFAINA")
    print("========================================")

    base_classificada = criar_classificacao_inicial()

    if base_classificada is None or base_classificada.empty:
        print("[CLASSIFICAÇÃO] Nenhum padrão disponível.")
        return pd.DataFrame()

    salvar_csv_seguro(
        dataframe=base_classificada,
        caminho_arquivo=arquivo_classificacao,
    )

    resumo = criar_resumo_classificacao(
        base_classificada
    )

    if not resumo:
        print("[CLASSIFICAÇÃO] Não foi possível gerar o resumo.")
        return base_classificada

    salvar_csv_seguro(
        dataframe=pd.DataFrame([resumo]),
        caminho_arquivo=arquivo_resumo,
    )

    print(f"Total de padrões: {resumo['total_padroes']}")
    print(f"Total de ocorrências: {resumo['total_ocorrencias']}")
    print(f"Categorias validadas: {resumo['categorias_validadas']}")

    print(
        "Validados automaticamente: "
        f"{resumo['padroes_validados_automaticamente']}"
    )

    print(
        "Pendentes de revisão humana: "
        f"{resumo['padroes_revisao_humana']}"
    )

    print(
        "Validados humanamente: "
        f"{resumo['padroes_validados_humanamente']}"
    )

    print(
        "Padrões desconhecidos: "
        f"{resumo['padroes_desconhecidos']}"
    )

    print("\nQuantidade por categoria validada:")

    print(
        base_classificada[
            "categoria_validada"
        ]
        .value_counts(
            dropna=False
        )
        .to_string()
    )

    print("\nQuantidade por status de validação:")

    print(
        base_classificada[
            "status_validacao"
        ]
        .value_counts(
            dropna=False
        )
        .to_string()
    )

    print("\nArquivos gerados:")
    print(f"- Classificação: {arquivo_classificacao}")
    print(f"- Resumo: {arquivo_resumo}")

    print("\n========================================")
    print("CLASSIFICAÇÃO AUTOMÁTICA FINALIZADA")
    print("========================================")

    return base_classificada