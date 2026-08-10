"""Cliente para a Graph API da Meta (conexão OAuth de WhatsApp/Instagram/Messenger).

Segue o mesmo estilo de billing/infinitepay.py: funções soltas, sem estado,
usando `requests` direto e `raise RuntimeError` quando a integração não está
configurada via variáveis de ambiente.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

GRAPH_URL = 'https://graph.facebook.com/v21.0'
OAUTH_DIALOG_URL = 'https://www.facebook.com/v21.0/dialog/oauth'

_SCOPES = {
    'whatsapp':  'whatsapp_business_management,whatsapp_business_messaging,business_management',
    'instagram': 'instagram_basic,instagram_manage_messages,pages_show_list,pages_read_engagement',
    'messenger': 'pages_messaging,pages_show_list,pages_manage_metadata',
    'ads':       'ads_read,business_management',
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
        negocios = resp.json().get('data', [])
        logger.warning('/me/businesses retornou %d empresa(s): %s',
                        len(negocios), [b.get('id') for b in negocios])
        ativos = []
        waba_ids_vistos = set()
        for biz in negocios:
            for edge in ('owned_whatsapp_business_accounts', 'client_whatsapp_business_accounts'):
                wabas = requests.get(f'{GRAPH_URL}/{biz["id"]}/{edge}',
                                      params={'access_token': access_token}, timeout=15)
                if not wabas.ok:
                    logger.warning('%s (%s) falhou: %s %s', edge, biz.get('id'), wabas.status_code, wabas.text[:300])
                    continue
                lista = wabas.json().get('data', [])
                logger.warning('%s (%s) retornou %d WABA(s): %s', edge, biz.get('id'), len(lista), [w.get('id') for w in lista])
                for waba in lista:
                    if waba['id'] in waba_ids_vistos:
                        continue
                    waba_ids_vistos.add(waba['id'])
                    nums = requests.get(f'{GRAPH_URL}/{waba["id"]}/phone_numbers',
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
    logger.warning('/me/accounts (%s) retornou %d página(s): %s',
                    canal, len(paginas), [p.get('id') for p in paginas])

    if canal == 'messenger':
        return [{'identificador_externo': p['id'], 'nome_conta': p.get('name') or p['id'],
                  'access_token': p.get('access_token'), 'page_id': p['id']} for p in paginas]

    if canal == 'instagram':
        ativos = []
        for p in paginas:
            info = requests.get(f'{GRAPH_URL}/{p["id"]}',
                                 params={'fields': 'instagram_business_account', 'access_token': access_token},
                                 timeout=15)
            if not info.ok:
                logger.warning('Falha ao buscar instagram_business_account da página %s: %s %s',
                                p.get('id'), info.status_code, info.text[:500])
                continue
            ig = info.json().get('instagram_business_account')
            if not ig:
                logger.warning('Página %s (%s) sem instagram_business_account vinculado. Resposta: %s',
                                p.get('id'), p.get('name'), info.text[:500])
                continue
            ativos.append({'identificador_externo': ig['id'], 'nome_conta': p.get('name') or ig['id'],
                            'access_token': p.get('access_token'), 'page_id': p['id']})
        return ativos

    return []


def assinar_pagina(page_id, page_access_token, campos='messages'):
    """Assina a Página nos campos de webhook do app (ex: 'messages'). Sem isso, mesmo
    com os campos configurados no App, a Meta não envia eventos para essa Página
    específica — a configuração no nível do App só define o que está disponível,
    a assinatura por Página é o que efetivamente liga o fluxo."""
    resp = requests.post(f'{GRAPH_URL}/{page_id}/subscribed_apps',
                          params={'subscribed_fields': campos, 'access_token': page_access_token},
                          timeout=15)
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
    return resp.json()


def enviar_mensagem(identificador_externo, destinatario_id, texto, access_token, quick_replies=None):
    """Envia mensagem de texto via Send API (Messenger/Instagram). Best-effort — quem chama trata a exceção."""
    payload_msg = {'text': texto}
    if quick_replies:
        payload_msg['quick_replies'] = quick_replies
    resp = requests.post(
        f'{GRAPH_URL}/{identificador_externo}/messages',
        params={'access_token': access_token},
        json={'recipient': {'id': destinatario_id}, 'message': payload_msg},
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')


def listar_contas_anuncio(access_token):
    """Retorna [{'identificador_externo': 'act_...', 'nome_conta': ...}] das contas de anúncio
    acessíveis — tanto as vinculadas diretamente ao perfil pessoal (/me/adaccounts) quanto as de
    Negócios (Business Manager) onde o usuário tem papel, sejam contas próprias (owned) ou de
    clientes (client). Mesmo padrão de listar_ativos('whatsapp', ...): /me/adaccounts sozinho não
    enxerga contas que só existem dentro de um Business Manager."""
    def _com_prefixo(cid):
        """owned_ad_accounts/client_ad_accounts às vezes devolvem o id sem o
        prefixo 'act_' (inconsistência conhecida da Graph API — /me/adaccounts
        sempre devolve prefixado, esses dois edges nem sempre). Sem o prefixo,
        a Insights API não erra, só devolve dado vazio silenciosamente."""
        return cid if cid.startswith('act_') else f'act_{cid}'

    resp = requests.get(f'{GRAPH_URL}/me/adaccounts',
                         params={'fields': 'id,name', 'access_token': access_token}, timeout=15)
    if not resp.ok:
        raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
    contas = resp.json().get('data', [])
    logger.warning('/me/adaccounts retornou %d conta(s): %s', len(contas), [c.get('id') for c in contas])
    vistas = {_com_prefixo(c['id']): (c.get('name') or c['id']) for c in contas}

    resp_biz = requests.get(f'{GRAPH_URL}/me/businesses', params={'access_token': access_token}, timeout=15)
    if resp_biz.ok:
        negocios = resp_biz.json().get('data', [])
        logger.warning('/me/businesses retornou %d negócio(s): %s', len(negocios), [b.get('id') for b in negocios])
        for biz in negocios:
            for edge in ('owned_ad_accounts', 'client_ad_accounts'):
                r = requests.get(f'{GRAPH_URL}/{biz["id"]}/{edge}',
                                  params={'fields': 'id,name', 'access_token': access_token}, timeout=15)
                if not r.ok:
                    logger.warning('%s (%s) falhou: %s %s', edge, biz.get('id'), r.status_code, r.text[:300])
                    continue
                lista = r.json().get('data', [])
                logger.warning('%s (%s) retornou %d conta(s): %s', edge, biz.get('id'), len(lista), [c.get('id') for c in lista])
                for c in lista:
                    cid = _com_prefixo(c['id'])
                    vistas.setdefault(cid, c.get('name') or cid)
    else:
        logger.warning('/me/businesses falhou: %s %s', resp_biz.status_code, resp_biz.text[:300])

    return [{'identificador_externo': cid, 'nome_conta': nome} for cid, nome in vistas.items()]


def buscar_insights_diarios(ad_account_id, access_token, desde, ate):
    """Retorna gasto/impressões/cliques por anúncio por dia num intervalo. Uma única
    chamada (paginada) já devolve o nome do anúncio e da campanha junto com o gasto —
    não precisa de chamadas separadas a /campaigns ou /ads."""
    import json as _json
    linhas = []
    url = f'{GRAPH_URL}/{ad_account_id}/insights'
    params = {
        'level': 'ad', 'time_increment': 1,
        'time_range': _json.dumps({'since': desde.isoformat(), 'until': ate.isoformat()}),
        'fields': 'ad_id,ad_name,campaign_id,campaign_name,spend,impressions,clicks,date_start',
        'access_token': access_token, 'limit': 500,
    }
    while url:
        resp = requests.get(url, params=params, timeout=30)
        if not resp.ok:
            raise RuntimeError(f'{resp.status_code} {resp.reason}: {resp.text[:300]}')
        body = resp.json()
        linhas.extend(body.get('data', []))
        url = body.get('paging', {}).get('next')
        params = None  # a URL de 'next' já vem com querystring completa
    logger.warning('buscar_insights_diarios(%s, %s..%s) retornou %d linha(s)',
                    ad_account_id, desde, ate, len(linhas))
    return linhas


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
