"""Fase 2 do funil da Renata Rosa — RN07 (recebimento opcional de fotos via
WhatsApp). Cobre: 1ª/2ª foto classificadas como 'atual'/'referencia' com ack
só na 1ª, teto de MAX_FOTOS_POR_LEAD, skip por texto (ausência de foto não
impede continuidade), falha de download não derruba a conversa, delete sem
violar FK, e a rota de serving restrita a administrador.

Mesmo padrão de test_funil_renata_rosa.py: usa _processar_evento diretamente
(bypassa a camada HTTP/assinatura do webhook)."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilFoto, User
import meta_client
from meta_webhook.routes import _processar_evento
from renata_rosa_bot.fotos import MAX_FOTOS_POR_LEAD
from tests.conftest import make_empresa, make_integracao_whatsapp


def _empresa_rr(**kwargs):
    defaults = dict(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                     funil_qualificacao_rr_ativo=True)
    defaults.update(kwargs)
    return make_empresa(**defaults)


def _evento(integracao, mensagem, thread_id, media_id=None, media_mime_type=None):
    return {
        'identificador_externo': integracao.identificador_externo,
        'external_thread_id': thread_id,
        'phone': thread_id,
        'nome': 'Cliente Teste',
        'mensagem': mensagem,
        'canal': 'whatsapp',
        'quick_reply_payload': None,
        'ad_id': None,
        'ad_title': None,
        'media_id': media_id,
        'media_mime_type': media_mime_type,
    }


def _enviar(integracao, mensagem, thread_id, monkeypatch, media_id=None, media_mime_type=None):
    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    _processar_evento(_evento(integracao, mensagem, thread_id, media_id, media_mime_type))
    return enviados


def _enviar_foto(integracao, thread_id, monkeypatch, media_id=None):
    return _enviar(integracao, '[image]', thread_id, monkeypatch,
                    media_id=media_id or uuid.uuid4().hex, media_mime_type='image/jpeg')


def _lead_e_fotos(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    fotos = RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).order_by(RenataRosaFunilFoto.id).all() if lead else []
    return lead, fotos


def _chegar_ate_fotos(integracao, thread_id, monkeypatch):
    """Percorre o funil (mechas/coloração) até o estado 'fotos' (RN07)."""
    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)   # mechas/coloração
    _enviar(integracao, '1', thread_id, monkeypatch)   # loiro com mechas
    _enviar(integracao, '1', thread_id, monkeypatch)   # nesta semana
    _enviar(integracao, '2', thread_id, monkeypatch)   # histórico
    _enviar(integracao, '1', thread_id, monkeypatch)   # investimento
    _enviar(integracao, '1', thread_id, monkeypatch)   # avaliação -> agora em 'fotos'


def test_primeira_foto_grava_como_atual_e_manda_ack(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)

    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'fake-bytes', 'image/jpeg')):
        enviados = _enviar_foto(integracao, thread_id, monkeypatch)

    assert enviados == ['Recebido! 💕 Pode mandar mais uma, se quiser, ou é só seguir quando terminar.']
    lead, fotos = _lead_e_fotos(empresa, thread_id)
    assert len(fotos) == 1
    assert fotos[0].papel == 'atual'
    assert fotos[0].dados == b'fake-bytes'
    assert fotos[0].mime == 'image/jpeg'


def test_segunda_foto_grava_como_referencia_e_fica_silenciosa(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)

    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'foto1', 'image/jpeg')):
        _enviar_foto(integracao, thread_id, monkeypatch)
    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'foto2', 'image/png')):
        enviados = _enviar_foto(integracao, thread_id, monkeypatch)

    assert enviados == []  # sem ack repetido
    lead, fotos = _lead_e_fotos(empresa, thread_id)
    assert len(fotos) == 2
    assert fotos[1].papel == 'referencia'
    assert fotos[1].mime == 'image/png'


def test_teto_de_fotos_nao_grava_mais_e_avisa(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)

    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'x', 'image/jpeg')):
        for _ in range(MAX_FOTOS_POR_LEAD):
            _enviar_foto(integracao, thread_id, monkeypatch)
        enviados = _enviar_foto(integracao, thread_id, monkeypatch)  # além do teto

    assert enviados == ['Já recebi fotos suficientes, obrigada! 💕 Pode seguir quando quiser.']
    lead, fotos = _lead_e_fotos(empresa, thread_id)
    assert len(fotos) == MAX_FOTOS_POR_LEAD


def test_mensagem_de_texto_pula_fotos_sem_gravar_nada(monkeypatch):
    """RN07: ausência de foto não pode impedir a continuidade do atendimento."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)

    enviados = _enviar(integracao, 'não quero enviar, pode seguir', thread_id, monkeypatch)

    assert 'Estamos quase terminando' in enviados[0]  # texto de AGENDAMENTO (RN08)
    lead, fotos = _lead_e_fotos(empresa, thread_id)
    assert fotos == []


def test_falha_no_download_nao_derruba_a_conversa(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)

    with patch('meta_client.baixar_midia_whatsapp', side_effect=RuntimeError('mídia expirada')):
        enviados = _enviar_foto(integracao, thread_id, monkeypatch)

    assert enviados == ['Não consegui receber essa imagem agora 😕 Mas sem problemas, pode '
                         'tentar enviar de novo ou seguir sem ela.']
    lead, fotos = _lead_e_fotos(empresa, thread_id)
    assert fotos == []
    assert lead.contato_etapa != 'transferido'  # conversa continua normalmente

    # Ainda em 'fotos' — uma mensagem de texto agora avança normalmente.
    enviados2 = _enviar(integracao, 'ok', thread_id, monkeypatch)
    assert 'Estamos quase terminando' in enviados2[0]


def test_delete_lead_com_fotos_nao_viola_fk(monkeypatch, client):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)
    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'x', 'image/jpeg')):
        _enviar_foto(integracao, thread_id, monkeypatch)

    lead, fotos = _lead_e_fotos(empresa, thread_id)
    assert len(fotos) == 1
    lead_id, foto_id = lead.id, fotos[0].id

    username = f'admin{uuid.uuid4().hex[:10]}'
    user = User(name='Admin', username=username, email=f'{username}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()

    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    resp = client.post(f'/admin/leads/{lead_id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    db.session.expunge_all()
    assert db.session.get(Lead, lead_id) is None
    assert db.session.get(RenataRosaFunilFoto, foto_id) is None


def test_rota_de_foto_restrita_a_administrador(monkeypatch, client):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _chegar_ate_fotos(integracao, thread_id, monkeypatch)
    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'bytes-da-foto', 'image/jpeg')):
        _enviar_foto(integracao, thread_id, monkeypatch)
    lead, fotos = _lead_e_fotos(empresa, thread_id)
    foto = fotos[0]

    username_admin = f'admin{uuid.uuid4().hex[:10]}'
    admin_user = User(name='Admin', username=username_admin, email=f'{username_admin}@teste.com',
                       empresa_id=empresa.id, role='empresa_admin')
    admin_user.set_password('senha123')
    db.session.add(admin_user)
    db.session.commit()

    client.post('/admin/login', data={'email': admin_user.email, 'password': 'senha123'}, follow_redirects=True)
    resp = client.get(f'/admin/leads/{lead.id}/fotos/{foto.id}')
    assert resp.status_code == 200
    assert resp.data == b'bytes-da-foto'
    assert resp.mimetype == 'image/jpeg'
    client.get('/admin/logout')

    # role='profissional' sem Profissional vinculado resolve pro perfil
    # 'leitura' (ver admin/permissions.py::current_perfil) — qualquer coisa
    # != administrador já basta pra provar a restrição.
    username_nao_admin = f'naoadmin{uuid.uuid4().hex[:10]}'
    nao_admin = User(name='Não-admin', username=username_nao_admin, email=f'{username_nao_admin}@teste.com',
                      empresa_id=empresa.id, role='profissional')
    nao_admin.set_password('senha123')
    db.session.add(nao_admin)
    db.session.commit()

    client.post('/admin/login', data={'email': nao_admin.email, 'password': 'senha123'}, follow_redirects=True)
    resp2 = client.get(f'/admin/leads/{lead.id}/fotos/{foto.id}')
    assert resp2.status_code == 403
