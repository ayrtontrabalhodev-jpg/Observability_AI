import html
from datetime import datetime

import win32com.client


EMAIL_DESTINATARIO = "ayrton.ralmeida@telefonica.com"


def escapar(valor):
    """
    Protege o HTML contra caracteres especiais
    presentes nas mensagens dos logs.
    """

    if valor is None:
        return ""

    return html.escape(str(valor))


def montar_corpo_email(alerta):
    """
    Monta o corpo HTML do alerta.
    """

    descricao = escapar(alerta.get("descricao_original"))
    categoria = escapar(alerta.get("categoria"))
    subcategoria = escapar(alerta.get("subcategoria"))
    causa = escapar(alerta.get("causa"))
    acao = escapar(alerta.get("acao"))
    criticidade = escapar(alerta.get("criticidade"))
    confianca = escapar(alerta.get("confianca"))
    decisao = escapar(alerta.get("decisao"))
    rpa = escapar(alerta.get("rpa"))
    id_log = escapar(alerta.get("id_log"))
    data_log = escapar(alerta.get("data_log"))
    chave_registro = escapar(alerta.get("chave_registro"))

    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #222222;">

            <h2 style="color: #C00000;">
                Falha detectada no RIFAINA
            </h2>

            <p>
                O Observability AI identificou um novo registro
                de erro durante o monitoramento.
            </p>

            <table style="
                border-collapse: collapse;
                width: 850px;
                max-width: 100%;
            ">
                <tr>
                    <td style="{estilo_rotulo()}">Data do erro</td>
                    <td style="{estilo_valor()}">{data_log}</td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">RPA</td>
                    <td style="{estilo_valor()}">{rpa}</td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">ID do log</td>
                    <td style="{estilo_valor()}">{id_log}</td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">Chave</td>
                    <td style="{estilo_valor()}">{chave_registro}</td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">Categoria</td>
                    <td style="{estilo_valor()}">
                        <strong>{categoria}</strong>
                    </td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">Subcategoria</td>
                    <td style="{estilo_valor()}">{subcategoria}</td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">Criticidade</td>
                    <td style="{estilo_valor()}">
                        <strong style="color: #C00000;">
                            {criticidade}
                        </strong>
                    </td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">Confiança</td>
                    <td style="{estilo_valor()}">{confianca}</td>
                </tr>

                <tr>
                    <td style="{estilo_rotulo()}">Decisão</td>
                    <td style="{estilo_valor()}">{decisao}</td>
                </tr>
            </table>

            <h3>Descrição original</h3>

            <div style="{estilo_caixa('#C00000')}">
                {descricao}
            </div>

            <h3>Possível causa</h3>

            <div style="{estilo_caixa('#ED7D31')}">
                {causa}
            </div>

            <h3>Onde verificar e o que fazer</h3>

            <div style="{estilo_caixa('#70AD47')}">
                {acao}
            </div>

            <p style="
                margin-top: 25px;
                color: #666666;
                font-size: 12px;
            ">
                A recomendação automática deve ser confirmada pelo
                responsável técnico. Se a causa for diferente, a
                correção aplicada deverá ser registrada para melhorar
                as próximas classificações.
            </p>

        </body>
    </html>
    """


def estilo_rotulo():
    return (
        "border: 1px solid #D9D9D9;"
        "background-color: #F2F2F2;"
        "padding: 8px;"
        "font-weight: bold;"
        "width: 210px;"
    )


def estilo_valor():
    return (
        "border: 1px solid #D9D9D9;"
        "padding: 8px;"
    )


def estilo_caixa(cor):
    return (
        "background-color: #F7F7F7;"
        f"border-left: 4px solid {cor};"
        "padding: 12px;"
        "margin-bottom: 15px;"
        "line-height: 1.5;"
        "white-space: pre-wrap;"
    )


def enviar_alerta_email(alerta):
    """
    Envia diretamente um alerta pelo Outlook.

    Diferentemente do teste anterior, esta função
    utiliza Send() e não Display().
    """

    categoria = alerta.get("categoria", "Erro não classificado")
    criticidade = alerta.get("criticidade", "Revisar")
    id_log = alerta.get("id_log", "Sem ID")

    assunto = (
        f"[OBSERVABILITY][{criticidade.upper()}]"
        f"[RIFAINA] {categoria} | Log {id_log}"
    )

    corpo_html = montar_corpo_email(alerta)

    try:
        outlook = win32com.client.gencache.EnsureDispatch(
            "Outlook.Application"
        )

        email = outlook.CreateItem(0)
        email.To = EMAIL_DESTINATARIO
        email.Subject = assunto
        email.HTMLBody = corpo_html

        # Envio automático
        email.Send()

        print(
            f"[ALERTA] E-mail enviado para "
            f"{EMAIL_DESTINATARIO}."
        )

        return {
            "enviado": True,
            "data_envio": datetime.now().isoformat(),
            "destinatario": EMAIL_DESTINATARIO,
            "assunto": assunto,
            "erro": None,
        }

    except Exception as erro:
        print(
            "[ALERTA] Erro ao enviar e-mail: "
            f"{type(erro).__name__}: {erro}"
        )

        return {
            "enviado": False,
            "data_envio": None,
            "destinatario": EMAIL_DESTINATARIO,
            "assunto": assunto,
            "erro": f"{type(erro).__name__}: {erro}",
        }