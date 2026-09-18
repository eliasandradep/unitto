"""Marcar um Lead como spam/pessoal ou removê-lo apaga a linha do Lead — se
esse Lead tiver conversa/eventos do atendimento por IA associados (FK sem ON
DELETE SET NULL no banco), o delete falhava com IntegrityError -> 500.
Bug real observado em produção: /admin/leads/<id>/marcar-spam."""
from models import db, User, AtendimentoIAConversa, AtendimentoIAEvento
from tests.conftest import make_empresa, make_integracao_whatsapp, make_lead


def _login(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'username': user.username, 'password': 'senha123'})


def _lead_com_ia_associada(empresa, integracao):
    lead = make_lead(empresa, integracao)
    conversa = AtendimentoIAConversa(empresa_id=empresa.id, lead_id=lead.id, telefone=lead.phone)
    db.session.add(conversa)
    db.session.flush()  # precisa do conversa.id pra referenciar no evento abaixo
    # evento com AMBAS as FKs setadas (lead_id e conversa_id) — é exatamente
    # essa combinação que reproduzia o 500 em produção: soltar só lead_id e
    # depois apagar a conversa ainda quebrava via conversa_id.
    evento = AtendimentoIAEvento(empresa_id=empresa.id, lead_id=lead.id,
                                  conversa_id=conversa.id, tipo='AI_MENU_DISPLAYED')
    db.session.add(evento)
    db.session.commit()
    return lead, conversa, evento


def test_marcar_spam_nao_quebra_com_conversa_e_evento_ia_associados(client):
    empresa = make_empresa()
    integracao = make_integracao_whatsapp(empresa)
    lead, conversa, evento = _lead_com_ia_associada(empresa, integracao)
    lead_id, conversa_id, evento_id = lead.id, conversa.id, evento.id
    _login(client, empresa)

    resp = client.post(f'/admin/leads/{lead_id}/marcar-spam', follow_redirects=True)
    assert resp.status_code == 200

    db.session.expunge_all()  # objetos em memória ficam "expirados" após o commit
    # da request; sem isso, session.get() tenta refresh de uma PK já deletada
    # e levanta ObjectDeletedError em vez de simplesmente retornar None.
    from models import Lead
    assert db.session.get(Lead, lead_id) is None
    assert db.session.get(AtendimentoIAConversa, conversa_id) is None  # conversa some junto
    evento_restante = db.session.get(AtendimentoIAEvento, evento_id)
    assert evento_restante is not None          # log/auditoria é preservado
    assert evento_restante.lead_id is None      # só a referência é solta
    assert evento_restante.conversa_id is None  # idem pra FK de conversa


def test_marcar_pessoal_nao_quebra_com_conversa_e_evento_ia_associados(client):
    empresa = make_empresa()
    integracao = make_integracao_whatsapp(empresa)
    lead, conversa, evento = _lead_com_ia_associada(empresa, integracao)
    lead_id, conversa_id = lead.id, conversa.id
    _login(client, empresa)

    resp = client.post(f'/admin/leads/{lead_id}/marcar-pessoal', follow_redirects=True)
    assert resp.status_code == 200
    db.session.expunge_all()
    assert db.session.get(AtendimentoIAConversa, conversa_id) is None


def test_lead_delete_nao_quebra_com_conversa_e_evento_ia_associados(client):
    empresa = make_empresa()
    integracao = make_integracao_whatsapp(empresa)
    lead, conversa, evento = _lead_com_ia_associada(empresa, integracao)
    lead_id, conversa_id = lead.id, conversa.id
    _login(client, empresa)

    resp = client.post(f'/admin/leads/{lead_id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    db.session.expunge_all()
    assert db.session.get(AtendimentoIAConversa, conversa_id) is None
