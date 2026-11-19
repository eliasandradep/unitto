"""Campo "Link do Street View" no cadastro de Unidade (admin/routes.py::unidades),
disponível pra qualquer tenant — pedido do usuário pra divulgar o espaço no
atendimento por IA (ver renata_rosa_bot/orquestrador.py::_texto_street_view
pro uso específico da Renata Rosa)."""
from models import db, User, Unidade
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


def test_cria_unidade_com_street_view_url(client):
    empresa = make_empresa()
    _login(client, empresa)

    resp = client.post('/admin/unidades', data={
        'action': 'save', 'id': '', 'nome': 'Centro',
        'street_view_url': 'https://maps.app.goo.gl/exemplo123',
    }, follow_redirects=True)
    assert resp.status_code == 200

    unidade = Unidade.query.filter_by(empresa_id=empresa.id, nome='Centro').first()
    assert unidade.street_view_url == 'https://maps.app.goo.gl/exemplo123'


def test_edita_unidade_pra_limpar_street_view_url(client):
    empresa = make_empresa()
    _login(client, empresa)
    unidade = Unidade(nome='Centro', empresa_id=empresa.id, ativo=True,
                       street_view_url='https://maps.app.goo.gl/antigo')
    db.session.add(unidade)
    db.session.commit()

    client.post('/admin/unidades', data={
        'action': 'save', 'id': str(unidade.id), 'nome': 'Centro', 'street_view_url': '',
    }, follow_redirects=True)

    db.session.refresh(unidade)
    assert unidade.street_view_url is None


def test_pagina_de_unidades_mostra_link_cadastrado(client):
    empresa = make_empresa()
    _login(client, empresa)
    db.session.add(Unidade(nome='Centro', empresa_id=empresa.id, ativo=True,
                            street_view_url='https://maps.app.goo.gl/exemplo123'))
    db.session.commit()

    resp = client.get('/admin/unidades')
    html = resp.get_data(as_text=True)
    assert 'https://maps.app.goo.gl/exemplo123' in html
