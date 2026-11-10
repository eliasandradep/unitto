"""Reordenação das colunas de profissionais na agenda (drag-and-drop no
front-end) — a ordem escolhida é salva por usuário (User.agenda_ordem_
profissionais, JSON) e reaplicada no próximo GET /admin/agenda daquele
mesmo usuário, sem afetar os demais."""
import json

from models import db, User, Profissional
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _criar_profissionais(empresa, nomes):
    profs = []
    for nome in nomes:
        p = Profissional(nome=nome, empresa_id=empresa.id, ativo=True)
        db.session.add(p)
        profs.append(p)
    db.session.commit()
    return profs


def test_salvar_ordem_colunas(client):
    empresa = make_empresa()
    user = _login_admin(client, empresa)
    profs = _criar_profissionais(empresa, ['Ana', 'Bruno', 'Carla'])
    ordem = [profs[2].id, profs[0].id, profs[1].id]

    resp = client.post('/admin/agenda/ordem-colunas', json={'ordem': ordem})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    db.session.refresh(user)
    assert json.loads(user.agenda_ordem_profissionais) == ordem


def test_agenda_aplica_ordem_salva(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    profs = _criar_profissionais(empresa, ['Ana', 'Bruno', 'Carla'])
    ordem = [profs[2].id, profs[0].id, profs[1].id]
    client.post('/admin/agenda/ordem-colunas', json={'ordem': ordem})

    resp = client.get('/admin/agenda')
    html = resp.get_data(as_text=True)
    pos = [html.index(f'data-prof="{pid}"') for pid in ordem]
    assert pos == sorted(pos)


def test_ordem_ignora_ids_de_outra_empresa(client):
    empresa1 = make_empresa(nome='Empresa 1')
    empresa2 = make_empresa(nome='Empresa 2')
    user = _login_admin(client, empresa1)
    profs1 = _criar_profissionais(empresa1, ['Ana', 'Bruno'])
    profs2 = _criar_profissionais(empresa2, ['Estranho'])

    ordem_enviada = [profs1[0].id, profs2[0].id, profs1[1].id]
    resp = client.post('/admin/agenda/ordem-colunas', json={'ordem': ordem_enviada})
    assert resp.status_code == 200

    db.session.refresh(user)
    ordem_salva = json.loads(user.agenda_ordem_profissionais)
    assert profs2[0].id not in ordem_salva
    assert set(ordem_salva) == {profs1[0].id, profs1[1].id}


def test_ordem_payload_invalido_eh_rejeitado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/agenda/ordem-colunas', json={'ordem': 'não é lista'})
    assert resp.status_code == 400

    resp = client.post('/admin/agenda/ordem-colunas', json={'ordem': ['a', 'b']})
    assert resp.status_code == 400


def test_ordem_e_por_usuario_nao_global(client):
    empresa = make_empresa()
    user1 = _login_admin(client, empresa)
    profs = _criar_profissionais(empresa, ['Ana', 'Bruno', 'Carla'])
    client.post('/admin/agenda/ordem-colunas', json={'ordem': [profs[2].id, profs[0].id, profs[1].id]})
    client.get('/admin/logout')

    user2 = User(name='Admin2', username=f'admin2{empresa.id}', email=f'admin2{empresa.id}@teste.com',
                 empresa_id=empresa.id, role='empresa_admin')
    user2.set_password('senha123')
    db.session.add(user2)
    db.session.commit()
    client.post('/admin/login', data={'email': user2.email, 'password': 'senha123'}, follow_redirects=True)

    resp = client.get('/admin/agenda')
    html = resp.get_data(as_text=True)
    pos = [html.index(f'data-prof="{p.id}"') for p in profs]
    assert pos == sorted(pos)  # ordem alfabética padrão, não a de user1

    db.session.refresh(user1)
    assert user1.agenda_ordem_profissionais is not None
