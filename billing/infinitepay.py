"""Integração com o Checkout Integrado da InfinitePay.

A InfinitePay não oferece API pública de assinatura recorrente — apenas
criação de links de pagamento avulsos (Checkout Integrado). Por isso a
assinatura é tratada como uma série de cobranças avulsas: uma no cadastro
e uma a cada renovação (ver rota `billing.renovar`), cada uma rastreada em
`CobrancaInfinitePay`.

Docs: https://www.infinitepay.io/checkout-documentacao
"""
import os
import requests

CHECKOUT_URL = 'https://api.checkout.infinitepay.io/links'
PAYMENT_CHECK_URL = 'https://api.checkout.infinitepay.io/payment_check'


def handle():
    return os.getenv('INFINITEPAY_HANDLE', '').strip()


def configurado():
    return bool(handle())


def criar_checkout_link(empresa, plano, order_nsu, redirect_url, webhook_url):
    """Cria um link de pagamento avulso para o plano e retorna (checkout_url, valor_centavos)."""
    h = handle()
    if not h:
        raise RuntimeError('INFINITEPAY_HANDLE não configurado.')

    valor_centavos = int(round(float(plano.preco) * 100))
    periodo_label = 'Mensal' if plano.tipo != 'anual' else 'Anual'

    payload = {
        'handle': h,
        'redirect_url': redirect_url,
        'webhook_url': webhook_url,
        'order_nsu': order_nsu,
        'items': [{
            'quantity': 1,
            'price': valor_centavos,
            'description': f'Plano {plano.nome} ({periodo_label}) - Unitto',
        }],
        'customer': {
            'name': empresa.nome,
            'email': empresa.email or '',
            'phone_number': empresa.telefone or '',
        },
    }
    resp = requests.post(CHECKOUT_URL, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data['url'], valor_centavos


def verificar_pagamento(order_nsu, transaction_nsu, invoice_slug):
    """Consulta manualmente o status de uma cobrança (fallback caso o webhook falhe)."""
    h = handle()
    if not h:
        raise RuntimeError('INFINITEPAY_HANDLE não configurado.')
    resp = requests.post(PAYMENT_CHECK_URL, json={
        'handle': h,
        'order_nsu': order_nsu,
        'transaction_nsu': transaction_nsu,
        'slug': invoice_slug,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()
