import hmac
import hashlib
import os
import re

from flask import request, jsonify, current_app

from . import meta_webhook_bp
from .parsers import parse_whatsapp, parse_messenger, parse_instagram
from models import db, IntegracaoMeta, Lead, Servico, Cliente, META_CANAL_SOURCE
import meta_client
from crypto_utils import decrypt_token

_PARSERS = {
    'whatsapp_business_account': parse_whatsapp,
    'page': parse_messenger,
    'instagram': parse_instagram,
}

# Canais em que a Meta não entrega telefone no payload — por isso pedimos
# nome e telefone automaticamente na primeira mensagem de cada Lead novo.
_CANAIS_SEM_TELEFONE = ('messenger', 'instagram')

_PERGUNTA_CONTATO = (
    'Olá! Para agilizar seu atendimento, pode me enviar seu nome completo, '
    'um telefone/WhatsApp para contato e qual serviço você tem interesse?'
)


_PALAVRAS_TELEFONE = re.compile(
    r'(?i)\b(telefone|tel|fone|whats\s?app|whats|numero|n[uú]mero|contato|cel|celular)\b[:\s]*')

_PREFIXOS_NOME = re.compile(r'(?i)^(meu nome é|me chamo|sou\s+(a|o)\s+)\s*')


def _servicos_ativos(empresa_id):
    return [s.nome for s in Servico.query.filter_by(empresa_id=empresa_id, ativo=True).all()]


def _somente_digitos(texto):
    return re.sub(r'\D', '', texto or '')


def _e_cliente_existente(empresa_id, telefone):
    """Compara os últimos 8 dígitos (ignora formatação e DDI/código de país,
    já que o número que a Meta entrega e o que fica salvo no cadastro do
    cliente raramente vêm no mesmo formato) contra os clientes já cadastrados
    da empresa."""
    alvo = _somente_digitos(telefone)[-8:]
    if len(alvo) < 8:
        return False
    return any(
        _somente_digitos(c.telefone)[-8:] == alvo
        for c in Cliente.query.filter_by(empresa_id=empresa_id).all()
    )


def _extrair_contato(texto, servicos_ativos):
    """Heurística simples: extrai a primeira sequência de 10-13 dígitos como
    telefone e o nome de um serviço ativo da empresa citado no texto (o que
    aparecer primeiro). Contatos costumam responder em mensagens separadas
    (uma só com o nome, outra só com o telefone, outra só com o serviço) em
    vez de tudo numa única mensagem — por isso, quando o texto não tem
    telefone nem serviço reconhecível, ele inteiro é tratado como candidato a
    nome; quando tem, o nome é o que sobra do texto depois de remover o
    trecho numérico/palavras-gatilho ("telefone", "whats" etc.) e o serviço
    encontrado."""
    texto = (texto or '').strip()

    digitos = re.sub(r'\D', '', texto)
    m = re.search(r'\d{10,13}', digitos)
    telefone = m.group(0) if m else None

    servico = None
    texto_lower = texto.lower()
    for nome_serv in servicos_ativos:
        if re.search(r'\b' + re.escape(nome_serv.lower()) + r'\b', texto_lower):
            servico = nome_serv
            break

    if not telefone and not servico:
        nome = _PREFIXOS_NOME.sub('', texto).strip(' ,.-')
        return (nome or None), None, None

    nome = re.sub(r'[\d()+\-.]{6,}', ' ', texto) if telefone else texto
    nome = _PALAVRAS_TELEFONE.sub(' ', nome)
    if servico:
        nome = re.sub(re.escape(servico), ' ', nome, flags=re.IGNORECASE)
    nome = _PREFIXOS_NOME.sub('', nome.strip())
    nome = re.sub(r'\s{2,}', ' ', nome).strip(' ,.-')
    return (nome or None), telefone, servico


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
        if lead.aguardando_contato:
            servicos = _servicos_ativos(integracao.empresa_id)
            nome_extraido, telefone_extraido, servico_extraido = _extrair_contato(evento['mensagem'], servicos)
            if telefone_extraido:
                lead.phone = telefone_extraido
                if lead.status == 'novo' and _e_cliente_existente(integracao.empresa_id, telefone_extraido):
                    lead.status = 'cliente_existente'
            if nome_extraido and not lead.name:
                lead.name = nome_extraido
            if servico_extraido and not lead.service:
                lead.service = servico_extraido
            # Continua "escutando" as próximas mensagens da conversa até ter
            # telefone (essencial) e serviço (quando a empresa tem catálogo
            # ativo) — sem risco de reenviar a pergunta, que só acontece na
            # criação do Lead.
            if lead.phone and (lead.service or not servicos):
                lead.aguardando_contato = False
        lead.message = evento['mensagem']
        if not lead.name and nome:
            lead.name = nome
        db.session.commit()
        return

    status = 'novo'
    if evento['phone'] and _e_cliente_existente(integracao.empresa_id, evento['phone']):
        status = 'cliente_existente'

    lead = Lead(
        empresa_id=integracao.empresa_id,
        external_thread_id=evento['external_thread_id'],
        integracao_id=integracao.id,
        name=nome,
        phone=evento['phone'],
        source=META_CANAL_SOURCE.get(evento['canal'], evento['canal']),
        message=evento['mensagem'],
        status=status,
    )
    db.session.add(lead)

    if evento['canal'] in _CANAIS_SEM_TELEFONE and not lead.phone:
        try:
            token = decrypt_token(integracao.access_token_enc)
            meta_client.enviar_mensagem(
                integracao.identificador_externo, evento['external_thread_id'],
                _PERGUNTA_CONTATO, token)
            lead.aguardando_contato = True
        except Exception:
            current_app.logger.exception('Falha ao enviar pergunta automática de contato')

    db.session.commit()
