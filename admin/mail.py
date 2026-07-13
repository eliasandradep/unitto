"""
Envio de e-mail via SMTP — usado hoje só para reset de senha.

Variáveis de ambiente:
    SMTP_HOST      (default: smtp.gmail.com)
    SMTP_PORT      (default: 587)
    SMTP_USER      conta que autentica e envia (ex: contato@gmail.com)
    SMTP_PASSWORD  senha de app do Gmail (não a senha normal da conta)
    MAIL_FROM      remetente exibido (default: SMTP_USER)
"""

import os
import smtplib
from email.mime.text import MIMEText


def send_email(to_addr: str, subject: str, body: str) -> bool:
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')
    mail_from = os.getenv('MAIL_FROM', smtp_user)

    if not smtp_user or not smtp_password:
        raise RuntimeError('SMTP_USER/SMTP_PASSWORD não configurados.')

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = mail_from
    msg['To'] = to_addr

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(mail_from, [to_addr], msg.as_string())
    return True
