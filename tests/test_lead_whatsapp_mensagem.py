"""Botão de WhatsApp da tela de Lead (detalhe e listagem) passa a abrir com
uma mensagem pré-preenchida (?text=) voltada pra puxar o lead pro
fechamento — nunca enviada sozinha, só preenche o campo de texto no
WhatsApp. Reaproveita o que já foi coletado (Lead.service, e os dados mais
ricos do funil da Renata Rosa quando houver)."""
from models import db, User, Lead, RenataRosaFunilLead
from admin.routes import _texto_whatsapp_lead
from tests.conftest import make_empresa


def _login(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'email': user.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user


def _lead(empresa, **kwargs):
    defaults = dict(empresa_id=empresa.id, name='Fulana Silva', phone='5511988887777', source='manual')
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def test_texto_generico_sem_nenhum_dado_coletado():
    empresa = make_empresa(nome='Salão Teste')
    lead = _lead(empresa, name=None, service=None)

    texto = _texto_whatsapp_lead(lead, empresa)
    assert texto.startswith('Oi!')
    assert 'Salão Teste' in texto
    assert 'Posso confirmar seu agendamento agora?' in texto


def test_texto_usa_primeiro_nome_e_servico_de_interesse():
    empresa = make_empresa(nome='Salão Teste')
    lead = _lead(empresa, name='Fulana Silva', service='Mechas')

    texto = _texto_whatsapp_lead(lead, empresa)
    assert texto.startswith('Oi, Fulana!')
    assert 'Mechas' in texto


def test_texto_usa_objetivo_e_prazo_do_funil_renata_rosa():
    empresa = make_empresa(nome='Renata Rosa Beauty Concept')
    lead = _lead(empresa, service=None)
    estado = RenataRosaFunilLead(
        lead_id=lead.id, empresa_id=empresa.id,
        servico_opcao_label='Coloração',
        resultado_desejado_texto='ficar com um loiro mais claro',
        prazo_texto='essa semana',
    )
    db.session.add(estado)
    db.session.commit()
    db.session.refresh(lead)

    texto = _texto_whatsapp_lead(lead, empresa)
    assert 'Coloração' in texto
    assert 'ficar com um loiro mais claro' in texto
    assert 'essa semana' in texto


def test_botao_whatsapp_no_detalhe_do_lead_tem_texto_pre_preenchido(client):
    empresa = make_empresa()
    _login(client, empresa)
    lead = _lead(empresa, name='Fulana Silva', service='Mechas')

    resp = client.get(f'/admin/leads/{lead.id}')
    html = resp.get_data(as_text=True)
    assert 'wa.me/555511988887777?text=' in html
    assert 'Oi%2C+Fulana' in html or 'Oi%2C%20Fulana' in html


def test_botao_whatsapp_na_listagem_de_leads_tem_texto_pre_preenchido(client):
    empresa = make_empresa()
    _login(client, empresa)
    _lead(empresa, name='Fulana Silva', service='Mechas')

    resp = client.get('/admin/leads')
    html = resp.get_data(as_text=True)
    assert 'wa.me/555511988887777?text=' in html
