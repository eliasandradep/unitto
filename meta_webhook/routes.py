import hmac
import hashlib
import os
import re

from flask import request, jsonify, current_app, url_for

from . import meta_webhook_bp
from .parsers import parse_whatsapp, parse_messenger, parse_instagram
from models import db, IntegracaoMeta, Lead, Servico, Cliente, ContatoIgnorado, META_CANAL_SOURCE
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
_PERGUNTA_SERVICO = 'Olá! Para agilizar seu atendimento, qual serviço você tem interesse?'
_PERGUNTA_TELEFONE = 'Perfeito! Agora me diga seu nome completo e um telefone/WhatsApp para contato.'

_MENU_WHATSAPP = (
    'Olá! Bem-vindo(a) à {empresa}. Escolha uma opção:\n'
    '1. Agendamento\n'
    '2. Serviços\n'
    '3. Falar com Atendente'
)
_SEM_MATCH_WHATSAPP = (
    'Não entendi. Digite *1* para Agendamento, *2* para Serviços ou '
    '*3* para falar com um atendente.'
)
_RE_OPCAO_ATENDENTE   = re.compile(r'(?i)^\s*3\b|atendente|humano|\bpessoa\b')
_RE_OPCAO_AGENDAMENTO = re.compile(r'(?i)^\s*1\b|agend')
_RE_OPCAO_SERVICOS    = re.compile(r'(?i)^\s*2\b|servi[cç]o')


def _classificar_intent_whatsapp(texto):
    """Classifica a mensagem numa das 3 opções do menu. 'atendente' é checado
    primeiro de propósito: independente do sub-estado atual, o cliente sempre
    consegue escapar pro humano digitando '3'/'atendente' a qualquer momento."""
    texto = (texto or '').strip()
    if _RE_OPCAO_ATENDENTE.search(texto):
        return 'atendente'
    if _RE_OPCAO_AGENDAMENTO.search(texto):
        return 'agendamento'
    if _RE_OPCAO_SERVICOS.search(texto):
        return 'servicos'
    return None


_PALAVRAS_TELEFONE = re.compile(
    r'(?i)\b(telefone|tel|fone|whats\s?app|whats|numero|n[uú]mero|contato|cel|celular)\b[:\s]*')

_PREFIXOS_NOME = re.compile(r'(?i)^(meu nome é|me chamo|sou\s+(a|o)\s+)\s*')


def _servicos_ativos(empresa_id):
    return [s.nome for s in Servico.query.filter_by(empresa_id=empresa_id, ativo=True).all()]


def _servicos_bookable(empresa_id):
    return Servico.query.filter_by(empresa_id=empresa_id, ativo=True, agendamento_online=True) \
        .order_by(Servico.nome).all()


def _texto_servicos_whatsapp(empresa_id):
    servicos = _servicos_bookable(empresa_id)
    if not servicos:
        return 'No momento não temos serviços disponíveis para agendamento online.'
    linhas = ['Nossos serviços:']
    for s in servicos:
        if s.exibir_preco_online and s.preco:
            linhas.append(f'- {s.nome} — R$ {s.preco:.2f}'.replace('.', ','))
        else:
            linhas.append(f'- {s.nome}')
    return '\n'.join(linhas)


def _texto_atendente_whatsapp(empresa):
    numero = empresa.whatsapp_humano_resolvido()
    if numero:
        return f'Você pode falar direto com um de nossos atendentes por aqui: https://wa.me/{numero}'
    return 'Um atendente vai continuar seu atendimento por aqui em breve.'


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


def _truncar_titulo(nome, limite=20):
    """Corta no último espaço antes do limite, evitando cortar uma palavra ao meio."""
    if len(nome) <= limite:
        return nome
    corte = nome[:limite].rsplit(' ', 1)[0]
    return corte if corte else nome[:limite]


def _quick_replies_servicos(servicos):
    """None se os títulos truncados colidirem entre si (dois serviços com o mesmo
    prefixo de 20 caracteres viram botões indistinguíveis pro cliente, mesmo com
    payloads diferentes por baixo) — nesse caso o chamador cai pro fluxo de texto livre."""
    titulos = [_truncar_titulo(s.nome) for s in servicos]
    if len(set(titulos)) != len(titulos):
        return None
    return [{'content_type': 'text', 'title': t, 'payload': f'SVC_{s.id}'}
            for s, t in zip(servicos, titulos)]


def _extrair_servico(texto, servicos_ativos):
    """Extraído de _extrair_contato: só a parte de casar nome de serviço no texto."""
    texto_lower = (texto or '').lower()
    for nome in servicos_ativos:
        if re.search(r'\b' + re.escape(nome.lower()) + r'\b', texto_lower):
            return nome
    return None


def _extrair_nome_e_telefone(texto):
    """Extraído de _extrair_contato: mesma lógica, sem a parte de serviço."""
    texto = (texto or '').strip()
    digitos = re.sub(r'\D', '', texto)
    m = re.search(r'\d{10,13}', digitos)
    telefone = m.group(0) if m else None
    if not telefone:
        nome = _PREFIXOS_NOME.sub('', texto).strip(' ,.-')
        return (nome or None), None
    nome = re.sub(r'[\d()+\-.]{6,}', ' ', texto)
    nome = _PALAVRAS_TELEFONE.sub(' ', nome)
    nome = _PREFIXOS_NOME.sub('', nome.strip())
    nome = re.sub(r'\s{2,}', ' ', nome).strip(' ,.-')
    return (nome or None), telefone


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
    if ContatoIgnorado.query.filter_by(
            empresa_id=integ.empresa_id, canal=evento['canal'],
            external_thread_id=evento['external_thread_id']).first():
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
            etapa = lead.contato_etapa or 'tudo'  # leads em andamento antes do deploy caem no fallback antigo

            if etapa == 'servico':
                servico = None
                payload = evento.get('quick_reply_payload')
                if payload and payload.startswith('SVC_'):
                    s = Servico.query.filter_by(id=payload[4:], empresa_id=integracao.empresa_id, ativo=True).first()
                    servico = s.nome if s else None
                if not servico:
                    servico = _extrair_servico(evento['mensagem'], _servicos_ativos(integracao.empresa_id))
                if servico:
                    lead.service = servico
                    try:
                        token = decrypt_token(integracao.access_token_enc)
                        meta_client.enviar_mensagem(
                            integracao.identificador_externo, evento['external_thread_id'],
                            _PERGUNTA_TELEFONE, token)
                        lead.contato_etapa = 'telefone'
                    except Exception:
                        current_app.logger.exception('Falha ao enviar pergunta de telefone')
                        lead.contato_etapa = None
                        lead.aguardando_contato = False
                # sem match (ex: cliente respondeu algo não reconhecível, ou o
                # serviço foi desativado nesse meio-tempo): não avança, continua
                # em 'servico' esperando uma resposta que dê pra casar.

            elif etapa == 'telefone':
                nome_extraido, telefone_extraido = _extrair_nome_e_telefone(evento['mensagem'])
                if telefone_extraido:
                    lead.phone = telefone_extraido
                    if lead.status == 'novo' and _e_cliente_existente(integracao.empresa_id, telefone_extraido):
                        lead.status = 'cliente_existente'
                    lead.contato_etapa = None
                    lead.aguardando_contato = False
                if nome_extraido and not lead.name:
                    lead.name = nome_extraido
                # sem telefone reconhecível: continua em 'telefone', esperando resposta melhor.

            else:  # 'tudo' — fallback quando não há botões (sem serviços ativos, ou mais de 13)
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
                    lead.contato_etapa = None
                    lead.aguardando_contato = False
        elif evento['canal'] == 'whatsapp' and lead.contato_etapa != 'transferido':
            intent = _classificar_intent_whatsapp(evento['mensagem'])
            try:
                token = decrypt_token(integracao.access_token_enc)
                if intent == 'atendente':
                    meta_client.enviar_mensagem_whatsapp(
                        integracao.identificador_externo, evento['external_thread_id'],
                        _texto_atendente_whatsapp(integracao.empresa), token)
                    lead.contato_etapa = 'transferido'
                elif intent == 'agendamento':
                    link = url_for('public.vitrine', slug=integracao.empresa.slug, _external=True)
                    meta_client.enviar_mensagem_whatsapp(
                        integracao.identificador_externo, evento['external_thread_id'],
                        f'Agende seu horário aqui: {link}', token)
                    lead.contato_etapa = 'wa_menu'
                elif intent == 'servicos':
                    meta_client.enviar_mensagem_whatsapp(
                        integracao.identificador_externo, evento['external_thread_id'],
                        _texto_servicos_whatsapp(integracao.empresa_id), token)
                    lead.contato_etapa = 'wa_menu'
                else:
                    meta_client.enviar_mensagem_whatsapp(
                        integracao.identificador_externo, evento['external_thread_id'],
                        _SEM_MATCH_WHATSAPP, token)
                    lead.contato_etapa = 'wa_menu'
            except Exception:
                current_app.logger.exception('Falha ao processar resposta automática de WhatsApp')
        lead.message = evento['mensagem']
        if not lead.name and nome:
            lead.name = nome
        if not lead.ad_id and evento.get('ad_id'):
            lead.ad_id = evento['ad_id']
            lead.ad_title = evento.get('ad_title')
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
        ad_id=evento.get('ad_id'),
        ad_title=evento.get('ad_title'),
    )
    db.session.add(lead)

    if evento['canal'] in _CANAIS_SEM_TELEFONE and not lead.phone:
        servicos_obj = Servico.query.filter_by(empresa_id=integracao.empresa_id, ativo=True) \
            .order_by(Servico.nome).all()
        quick_replies = _quick_replies_servicos(servicos_obj) if 0 < len(servicos_obj) <= 13 else None
        try:
            token = decrypt_token(integracao.access_token_enc)
            if quick_replies:
                meta_client.enviar_mensagem(
                    integracao.identificador_externo, evento['external_thread_id'],
                    _PERGUNTA_SERVICO, token, quick_replies=quick_replies)
                lead.contato_etapa = 'servico'
            else:
                meta_client.enviar_mensagem(
                    integracao.identificador_externo, evento['external_thread_id'],
                    _PERGUNTA_CONTATO, token)
                lead.contato_etapa = 'tudo'
            lead.aguardando_contato = True
        except Exception:
            current_app.logger.exception('Falha ao enviar pergunta automática de contato')
    elif evento['canal'] == 'whatsapp':
        try:
            token = decrypt_token(integracao.access_token_enc)
            meta_client.enviar_mensagem_whatsapp(
                integracao.identificador_externo, evento['external_thread_id'],
                _MENU_WHATSAPP.format(empresa=integracao.empresa.nome), token)
            lead.contato_etapa = 'wa_menu'
        except Exception:
            current_app.logger.exception('Falha ao enviar menu automático de WhatsApp')

    db.session.commit()
