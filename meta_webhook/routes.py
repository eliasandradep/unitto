import hmac
import hashlib
import os

from flask import request, jsonify, current_app

from . import meta_webhook_bp
from .parsers import parse_whatsapp, parse_messenger, parse_instagram
from models import db, IntegracaoMeta, Lead, META_CANAL_SOURCE
import meta_client
from crypto_utils import decrypt_token

_PARSERS = {
    'whatsapp_business_account': parse_whatsapp,
    'page': parse_messenger,
    'instagram': parse_instagram,
}


@meta_webhook_bp.route('/webhook', methods=['GET'])
def verificar():
    verify_token = os.getenv('META_VERIFY_TOKEN', '').strip()
    if request.args.get('hub.mode') == 'subscribe' and \
            verify_token and request.args.get('hub.verify_token') == verify_token:
        return request.args.get('hub.challenge', ''), 200
    return 'Forbidden', 403


@meta_webhook_bp.route('/webhook', methods=['POST'])
def receber():
    app_secret = meta_client.app_secret()
    assinatura = request.headers.get('X-Hub-Signature-256', '')
    if not app_secret or not assinatura.startswith('sha256='):
        return 'Forbidden', 403

    esperado = hmac.new(app_secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura[len('sha256='):], esperado):
        return 'Forbidden', 403

    body = request.get_json(silent=True) or {}
    parser = _PARSERS.get(body.get('object'))
    if not parser:
        return jsonify({'success': True}), 200

    try:
        for evento in parser(body):
            _processar_evento(evento)
    except Exception:
        current_app.logger.exception('Falha ao processar webhook da Meta')

    return jsonify({'success': True}), 200


def _processar_evento(evento):
    integ = IntegracaoMeta.query.filter_by(
        canal=evento['canal'],
        identificador_externo=evento['identificador_externo'],
        status='conectado',
    ).first()
    if not integ:
        return
    _upsert_lead(integ, evento)


def _upsert_lead(integracao, evento):
    lead = Lead.query.filter_by(
        empresa_id=integracao.empresa_id,
        external_thread_id=evento['external_thread_id'],
    ).first()

    nome = evento['nome']
    if not nome and evento['canal'] in ('instagram', 'messenger'):
        try:
            token = decrypt_token(integracao.access_token_enc)
            nome = meta_client.buscar_nome_perfil(evento['external_thread_id'], token)
        except Exception:
            nome = None

    if lead:
        lead.message = evento['mensagem']
        if not lead.name and nome:
            lead.name = nome
    else:
        lead = Lead(
            empresa_id=integracao.empresa_id,
            external_thread_id=evento['external_thread_id'],
            integracao_id=integracao.id,
            name=nome,
            phone=evento['phone'],
            source=META_CANAL_SOURCE.get(evento['canal'], evento['canal']),
            message=evento['mensagem'],
            status='novo',
        )
        db.session.add(lead)
    db.session.commit()
