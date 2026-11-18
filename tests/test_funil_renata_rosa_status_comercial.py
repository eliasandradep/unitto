"""Fase 3 do funil da Renata Rosa — RN15 (status comercial, 11 estágios,
independente de classificacao) e RN16 (retomada). Mesmo padrão das fases
anteriores: usa _processar_evento diretamente."""
import uuid
from datetime import datetime, timedelta

from models import db, Lead, RenataRosaFunilLead, RenataRosaFunilStatusHistorico, User
import meta_client
from meta_webhook.routes import _processar_evento
from renata_rosa_bot.status_comercial import definir_status, marcar_sem_resposta, SEM_RESPOSTA_HORAS
from tests.conftest import make_empresa, make_integracao_whatsapp


def _empresa_rr(**kwargs):
    defaults = dict(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                     funil_qualificacao_rr_ativo=True)
    defaults.update(kwargs)
    return make_empresa(**defaults)


def _evento(integracao, mensagem, thread_id):
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
        'media_id': None,
        'media_mime_type': None,
    }


def _enviar(integracao, mensagem, thread_id, monkeypatch):
    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    _processar_evento(_evento(integracao, mensagem, thread_id))
    return enviados


def _lead_e_estado(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first() if lead else None
    return lead, estado


def test_caminho_quente_passa_por_novo_lead_qualificacao_e_aguardando_humano(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.status_comercial == 'novo_lead'

    _enviar(integracao, '1', thread_id, monkeypatch)
    db.session.refresh(estado)
    assert estado.status_comercial == 'em_qualificacao'

    _enviar(integracao, '1', thread_id, monkeypatch)   # loiro com mechas
    _enviar(integracao, '1', thread_id, monkeypatch)   # nesta semana
    _enviar(integracao, '2', thread_id, monkeypatch)   # histórico
    _enviar(integracao, '1', thread_id, monkeypatch)   # investimento
    _enviar(integracao, '1', thread_id, monkeypatch)   # avaliação
    _enviar(integracao, 'pronto', thread_id, monkeypatch)  # pula fotos
    _enviar(integracao, '1', thread_id, monkeypatch)   # quer agendar -> 100 = QUENTE

    db.session.refresh(estado)
    assert estado.status_comercial == 'aguardando_atendimento_humano'

    historico = RenataRosaFunilStatusHistorico.query.filter_by(funil_lead_id=estado.id) \
        .order_by(RenataRosaFunilStatusHistorico.id).all()
    transicoes = [(h.status_anterior, h.status_novo) for h in historico]
    assert ('novo_lead', 'em_qualificacao') in transicoes
    assert ('em_qualificacao', 'qualificado_quente') in transicoes
    assert ('qualificado_quente', 'aguardando_atendimento_humano') in transicoes


def test_ja_cliente_pula_direto_pra_aguardando_humano(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '4', thread_id, monkeypatch)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.status_comercial == 'aguardando_atendimento_humano'
    historico = RenataRosaFunilStatusHistorico.query.filter_by(funil_lead_id=estado.id).all()
    assert len(historico) == 1
    assert historico[0].status_anterior == 'novo_lead'
    assert historico[0].status_novo == 'aguardando_atendimento_humano'


def test_menu_reseta_status_comercial_sem_apagar_historico_anterior(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.status_comercial == 'em_qualificacao'

    _enviar(integracao, 'menu', thread_id, monkeypatch)
    db.session.refresh(estado)
    assert estado.status_comercial == 'novo_lead'

    historico = RenataRosaFunilStatusHistorico.query.filter_by(funil_lead_id=estado.id).all()
    assert len(historico) == 2  # novo_lead->em_qualificacao, em_qualificacao->novo_lead — nada apagado


def test_update_manual_via_admin_grava_historico(monkeypatch, client):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    lead, estado = _lead_e_estado(empresa, thread_id)

    username = f'admin{uuid.uuid4().hex[:10]}'
    user = User(name='Admin', username=username, email=f'{username}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)

    resp = client.post(f'/admin/leads/{lead.id}', data={
        'action': 'update_status_comercial', 'status_comercial': 'em_negociacao',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(estado)
    assert estado.status_comercial == 'em_negociacao'
    historico = RenataRosaFunilStatusHistorico.query.filter_by(funil_lead_id=estado.id).all()
    assert any(h.status_novo == 'em_negociacao' for h in historico)


def test_status_manual_nao_e_sobrescrito_por_nova_qualificacao_automatica(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    lead, estado = _lead_e_estado(empresa, thread_id)

    definir_status(estado, 'em_negociacao', forcar=True)  # ação manual da atendente

    _enviar(integracao, '1', thread_id, monkeypatch)  # cliente volta e começa a qualificação de novo
    db.session.refresh(estado)
    assert estado.status_comercial == 'em_negociacao'  # não foi sobrescrito automaticamente


def test_marcar_sem_resposta_so_marca_quem_passou_do_prazo_em_status_ativo(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)

    # Lead A: em_qualificacao, parado há mais tempo que o limite -> marca.
    thread_a = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_a, monkeypatch)
    _enviar(integracao, '1', thread_a, monkeypatch)
    lead_a, estado_a = _lead_e_estado(empresa, thread_a)
    RenataRosaFunilLead.query.filter_by(id=estado_a.id).update(
        {'atualizado_em': datetime.utcnow() - timedelta(hours=SEM_RESPOSTA_HORAS + 1)})
    db.session.commit()

    # Lead B: em_qualificacao, mas recente -> não marca.
    thread_b = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_b, monkeypatch)
    _enviar(integracao, '1', thread_b, monkeypatch)
    lead_b, estado_b = _lead_e_estado(empresa, thread_b)

    # Lead C: status manual (em_negociacao), bem parado -> nunca marca.
    thread_c = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_c, monkeypatch)
    lead_c, estado_c = _lead_e_estado(empresa, thread_c)
    definir_status(estado_c, 'em_negociacao', forcar=True)
    RenataRosaFunilLead.query.filter_by(id=estado_c.id).update(
        {'atualizado_em': datetime.utcnow() - timedelta(hours=SEM_RESPOSTA_HORAS + 100)})
    db.session.commit()

    marcar_sem_resposta()

    db.session.refresh(estado_a)
    db.session.refresh(estado_b)
    db.session.refresh(estado_c)
    assert estado_a.status_comercial == 'sem_resposta'
    assert estado_b.status_comercial == 'em_qualificacao'
    assert estado_c.status_comercial == 'em_negociacao'


def test_mensagem_nova_com_status_sem_resposta_retoma_para_em_qualificacao(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)   # em_qualificacao, estado='tipo_transformacao'
    lead, estado = _lead_e_estado(empresa, thread_id)
    definir_status(estado, 'sem_resposta', forcar=True)

    enviados = _enviar(integracao, '1', thread_id, monkeypatch)  # retoma respondendo a pergunta atual

    db.session.refresh(estado)
    assert estado.status_comercial == 'em_qualificacao'
    assert 'maravilha' in enviados[0].lower()  # texto de PRAZO (RN03) — fluxo continuou de onde parou


def test_definir_status_e_no_op_quando_status_nao_muda(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    lead, estado = _lead_e_estado(empresa, thread_id)

    definir_status(estado, 'novo_lead')  # já é esse status
    historico = RenataRosaFunilStatusHistorico.query.filter_by(funil_lead_id=estado.id).all()
    assert historico == []
