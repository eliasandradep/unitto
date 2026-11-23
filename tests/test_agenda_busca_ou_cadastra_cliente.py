"""Pedido do usuário: no momento de criar/editar um agendamento, buscar a
cliente pelo mesmo campo de nome tanto por nome quanto por telefone; se não
existir nenhuma cliente com aquele telefone, cadastrá-la automaticamente ao
salvar (nome + telefone), evitando duplicar quem já existe."""
from datetime import date, timedelta

from models import db, User, Agendamento, Cliente
from tests.conftest import make_empresa, make_booking_setup


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_busca_de_cliente_encontra_por_nome_ou_telefone(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    c = Cliente(empresa_id=empresa.id, nome='Maria da Silva', telefone='(35) 99999-1111')
    db.session.add(c)
    db.session.commit()

    resp_nome = client.get('/admin/api/clientes/busca?q=Maria')
    assert resp_nome.get_json()[0]['id'] == c.id

    resp_tel = client.get('/admin/api/clientes/busca?q=35999991111')
    assert resp_tel.get_json()[0]['id'] == c.id

    resp_tel_formatado = client.get('/admin/api/clientes/busca?q=99999-1111')
    assert resp_tel_formatado.get_json()[0]['id'] == c.id


def test_agendar_com_telefone_novo_cadastra_cliente_automaticamente(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = (date.today() + timedelta(days=1)).isoformat()

    assert Cliente.query.filter_by(empresa_id=empresa.id).count() == 0

    resp = client.post('/admin/agenda/novo', data={
        'data': dia,
        'hora_inicio': '10:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Joana Nova',
        'telefone': '(35) 98888-2222',
        'servico_ids[]': [str(servico.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    ag = Agendamento.query.filter_by(nome_cliente='Joana Nova').first()
    assert ag is not None
    cliente = Cliente.query.filter_by(empresa_id=empresa.id).first()
    assert cliente is not None
    assert cliente.nome == 'Joana Nova'
    assert cliente.telefone == '(35) 98888-2222'
    assert ag.cliente_id == cliente.id


def test_agendar_com_telefone_ja_cadastrado_reaproveita_cliente_existente(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = (date.today() + timedelta(days=1)).isoformat()

    existente = Cliente(empresa_id=empresa.id, nome='Carla Antiga', telefone='(35) 97777-3333')
    db.session.add(existente)
    db.session.commit()
    existente_id = existente.id

    resp = client.post('/admin/agenda/novo', data={
        'data': dia,
        'hora_inicio': '11:00',
        'profissional_id': str(prof.id),
        # digitada sem formatação e com nome levemente diferente — mesma
        # pessoa identificada pelo telefone, sem duplicar o cadastro.
        'nome_cliente': 'Carla',
        'telefone': '35977773333',
        'servico_ids[]': [str(servico.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    assert Cliente.query.filter_by(empresa_id=empresa.id).count() == 1
    ag = Agendamento.query.filter_by(nome_cliente='Carla').first()
    assert ag is not None
    assert ag.cliente_id == existente_id


def test_agendar_sem_telefone_nao_cadastra_cliente(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = (date.today() + timedelta(days=1)).isoformat()

    resp = client.post('/admin/agenda/novo', data={
        'data': dia,
        'hora_inicio': '12:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Sem Telefone',
        'servico_ids[]': [str(servico.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    ag = Agendamento.query.filter_by(nome_cliente='Sem Telefone').first()
    assert ag is not None
    assert ag.cliente_id is None
    assert Cliente.query.filter_by(empresa_id=empresa.id).count() == 0
