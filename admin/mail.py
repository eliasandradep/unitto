"""
Envio de e-mail via Resend (API HTTPS) — usado hoje só para reset de senha.

SMTP puro é bloqueado/instável em muitos PaaS (inclusive Railway), então
usamos a API HTTP do Resend em vez de smtplib.

Variáveis de ambiente:
    RESEND_API_KEY  chave da conta Resend (resend.com/api-keys)
    MAIL_FROM       remetente exibido (precisa ser de um domínio verificado
                     no Resend, ou onboarding@resend.dev para testes)
"""

import os
import requests

RESEND_API_URL = 'https://api.resend.com/emails'


def send_email(to_addr: str, subject: str, body: str) -> bool:
    api_key = os.getenv('RESEND_API_KEY')
    mail_from = os.getenv('MAIL_FROM')

    if not api_key or not mail_from:
        raise RuntimeError('RESEND_API_KEY/MAIL_FROM não configurados.')

    resp = requests.post(
        RESEND_API_URL,
        headers={'Authorization': f'Bearer {api_key}'},
        json={
            'from': mail_from,
            'to': [to_addr],
            'subject': subject,
            'text': body,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return True
