"""Cliente para a Graph API da Meta (conexão OAuth de WhatsApp/Instagram/Messenger).

Segue o mesmo estilo de billing/infinitepay.py: funções soltas, sem estado,
usando `requests` direto e `raise RuntimeError` quando a integração não está
configurada via variáveis de ambiente.
"""
import os

import requests

GRAPH_URL = 'https://graph.facebook.com/v21.0'
OAUTH_DIALOG_URL = 'https://www.facebook.com/v21.0/dialog/oauth'

_SCOPES = {
    'whatsapp':  'whatsapp_business_management,whatsapp_business_messaging',
    'instagram': 'instagram_basic,instagram_manage_messages,pages_show_list',
    'messenger': 'pages_messaging,pages_show_list',
}


def app_id():
    return os.getenv('META_APP_ID', '').strip()


def app_secret():
    return os.getenv('META_APP_SECRET', '').strip()


def redirect_uri():
    return os.getenv('META_REDIRECT_URI', '').strip()


def configurado():
    return bool(app_id()) and bool(app_secret()) and bool(redirect_uri())


def oauth_dialog_url(canal, state):
    if not configurado():
        raise RuntimeError('Integração com a Meta não configurada (META_APP_ID/META_APP_SECRET/META_REDIRECT_URI).')
    params = {
        'client_id': app_id(),
        'redirect_uri': redirect_uri(),
        'state': state,
        'scope': _SCOPES.get(canal, ''),
    }
    query = '&'.join(f'{k}={requests.utils.quote(str(v))}' for k, v in params.items())
    return f'{OAUTH_DIALOG_URL}?{query}'


def trocar_code_por_token(code):
    """Troca o `code` do redirect OAuth por um token de acesso de longa duração (~60 dias)."""
    resp = requests.get(f'{GRAPH_URL}/oauth/access_token', params={
        'client_id': app_id(),
        'client_secret': app_secret(),
        'redirect_uri': redirect_uri(),
        'code': code,
    }, timeout=15)
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
    token_curto = resp.json()['access_token']

    resp = requests.get(f'{GRAPH_URL}/oauth/access_token', params={
        'grant_type': 'fb_exchange_token',
        'client_id': app_id(),
        'client_secret': app_secret(),
        'fb_exchange_token': token_curto,
    }, timeout=15)
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
    return resp.json()['access_token']


def listar_ativos(canal, access_token):
    """Retorna [{'identificador_externo': ..., 'nome_conta': ...}] dos ativos conectáveis para o canal."""
    if canal == 'whatsapp':
        resp = requests.get(f'{GRAPH_URL}/me/businesses', params={'access_token': access_token}, timeout=15)
        if not resp.ok:
            raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
        ativos = []
        for biz in resp.json().get('data', []):
            nums = requests.get(f'{GRAPH_URL}/{biz["id"]}/phone_numbers',
                                 params={'access_token': access_token}, timeout=15)
            if not nums.ok:
                continue
            for num in nums.json().get('data', []):
                ativos.append({
                    'identificador_externo': num['id'],
                    'nome_conta': num.get('verified_name') or num.get('display_phone_number') or num['id'],
                })
        return ativos

    resp = requests.get(f'{GRAPH_URL}/me/accounts', params={'access_token': access_token}, timeout=15)
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
    paginas = resp.json().get('data', [])

    if canal == 'messenger':
        return [{'identificador_externo': p['id'], 'nome_conta': p.get('name') or p['id'],
                  'access_token': p.get('access_token')} for p in paginas]

    if canal == 'instagram':
        ativos = []
        for p in paginas:
            info = requests.get(f'{GRAPH_URL}/{p["id"]}',
                                 params={'fields': 'instagram_business_account', 'access_token': access_token},
                                 timeout=15)
            if not info.ok:
                continue
            ig = info.json().get('instagram_business_account')
            if ig:
                ativos.append({'identificador_externo': ig['id'], 'nome_conta': p.get('name') or ig['id'],
                                'access_token': p.get('access_token')})
        return ativos

    return []


def enviar_mensagem(identificador_externo, destinatario_id, texto, access_token):
    """Envia mensagem de texto via Send API (Messenger/Instagram). Best-effort — quem chama trata a exceção."""
    resp = requests.post(
        f'{GRAPH_URL}/{identificador_externo}/messages',
        params={'access_token': access_token},
        json={'recipient': {'id': destinatario_id}, 'message': {'text': texto}},
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')


def buscar_nome_perfil(psid, access_token):
    """Busca o nome do remetente de uma mensagem do Instagram/Messenger. Best-effort — nunca levanta exceção."""
    try:
        resp = requests.get(f'{GRAPH_URL}/{psid}', params={'fields': 'name', 'access_token': access_token},
                             timeout=10)
        if resp.ok:
            return resp.json().get('name')
    except requests.RequestException:
        pass
    return None
