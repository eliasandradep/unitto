"""Visualização da agenda (grid web/mobile via /admin/agenda/dados, e a
tela de Listagem) é liberada pra qualquer perfil ver qualquer profissional
— só CRIAR/EDITAR um agendamento continua restrito por agenda_scope()
(ver tests/test_agenda_interna_ignora_expediente.py e outros, que cobrem
esse lado sem mudança nenhuma aqui)."""
from datetime import date, time, timedelta

from models import db, User, Profissional, Servico, Agendamento
from tests.conftest import make_empresa


def _amanha():
    return date.today() + timedelta(days=1)


def _login_perfil(client, empresa, perfil, prof):
    user = User(name=perfil.title(), username=f'{perfil}{prof.id}', email=f'{perfil}{prof.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _dois_profissionais_com_agendamento(empresa):
    prof_a = Profissional(nome='Profissional A', empresa_id=empresa.id, ativo=True, perfil_acesso='profissional')
    prof_b = Profissional(nome='Profissional B', empresa_id=empresa.id, ativo=True)
    db.session.add_all([prof_a, prof_b])
    db.session.flush()
    servico = Servico(nome='Corte', empresa_id=empresa.id, ativo=True)
    db.session.add(servico)
    db.session.flush()
    dia = _amanha()
    ag_a = Agendamento(empresa_id=empresa.id, profissional_id=prof_a.id, servico_id=servico.id,
                        nome_cliente='Cliente da A', data=dia, hora_inicio=time(10, 0),
                        duracao_min=60, status='agendado')
    ag_b = Agendamento(empresa_id=empresa.id, profissional_id=prof_b.id, servico_id=servico.id,
                        nome_cliente='Cliente da B', data=dia, hora_inicio=time(11, 0),
                        duracao_min=60, status='agendado')
    db.session.add_all([ag_a, ag_b])
    db.session.commit()
    return prof_a, prof_b, ag_a, ag_b, dia


def test_perfil_profissional_ve_agendamento_de_outro_profissional_na_grade(client):
    empresa = make_empresa()
    prof_a, prof_b, ag_a, ag_b, dia = _dois_profissionais_com_agendamento(empresa)
    _login_perfil(client, empresa, 'profissional', prof_a)

    resp = client.get(f'/admin/agenda/dados?data={dia.isoformat()}')
    assert resp.status_code == 200
    ids = {e['id'] for e in resp.get_json()['events']}
    assert ag_a.id in ids
    assert ag_b.id in ids  # antes era filtrado pra só a própria profissional


def test_perfil_pessoal_ve_agendamento_de_outro_profissional_na_grade(client):
    empresa = make_empresa()
    prof_a, prof_b, ag_a, ag_b, dia = _dois_profissionais_com_agendamento(empresa)
    prof_a.perfil_acesso = 'pessoal'
    db.session.commit()
    _login_perfil(client, empresa, 'pessoal', prof_a)

    resp = client.get(f'/admin/agenda/dados?data={dia.isoformat()}')
    ids = {e['id'] for e in resp.get_json()['events']}
    assert ag_a.id in ids
    assert ag_b.id in ids


def test_perfil_leitura_ve_agendamento_de_outro_profissional_na_grade(client):
    empresa = make_empresa()
    prof_a, prof_b, ag_a, ag_b, dia = _dois_profissionais_com_agendamento(empresa)
    prof_a.perfil_acesso = 'leitura'
    db.session.commit()
    _login_perfil(client, empresa, 'leitura', prof_a)

    resp = client.get(f'/admin/agenda/dados?data={dia.isoformat()}')
    ids = {e['id'] for e in resp.get_json()['events']}
    assert ag_a.id in ids
    assert ag_b.id in ids


def test_perfil_profissional_ve_agendamento_de_outro_na_listagem(client):
    empresa = make_empresa()
    prof_a, prof_b, ag_a, ag_b, dia = _dois_profissionais_com_agendamento(empresa)
    _login_perfil(client, empresa, 'profissional', prof_a)

    resp = client.get('/admin/agenda/listagem')
    body = resp.data.decode('utf-8')
    assert 'Cliente da A' in body
    assert 'Cliente da B' in body  # antes era filtrado pra só a própria profissional


def test_criacao_de_agendamento_continua_restrita_a_propria_agenda(client):
    """Confirma que a mudança foi só na visualização — criar continua
    restrito pra perfil 'profissional' (scope 'own'), igual sempre foi."""
    empresa = make_empresa()
    prof_a, prof_b, ag_a, ag_b, dia = _dois_profissionais_com_agendamento(empresa)
    _login_perfil(client, empresa, 'profissional', prof_a)

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(), 'hora_inicio': '15:00', 'profissional_id': str(prof_b.id),
        'nome_cliente': 'Tentativa Indevida', 'servico_id': str(Servico.query.first().id),
    })
    assert resp.status_code == 403
    assert Agendamento.query.filter_by(nome_cliente='Tentativa Indevida').first() is None
