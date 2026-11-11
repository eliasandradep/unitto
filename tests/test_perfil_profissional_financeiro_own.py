"""Regra de negócio: o perfil de acesso 'profissional' (Profissional.perfil_acesso
== 'profissional') só pode ver/editar/fechar/lançar pagamento nas PRÓPRIAS
comandas (comanda.profissional_id == o profissional logado), mas sem
restrição de data (diferente do perfil 'recepcao', que mexe em comanda de
qualquer responsável, só do dia de hoje). Ver admin/permissions.py
(financeiro_pode_acessar, escopo 'own') e admin/routes.py (_save_comanda
força profissional_id = o próprio quando o escopo é 'own')."""
from datetime import date, timedelta

from models import db, User, Profissional, Comanda, ComandaItem
from tests.conftest import make_empresa


def _login_profissional(client, empresa, nome='Prof A'):
    prof = Profissional(nome=nome, empresa_id=empresa.id, ativo=True, perfil_acesso='profissional')
    db.session.add(prof)
    db.session.flush()
    user = User(name=nome, username=f'{nome.lower().replace(" ", "")}{empresa.id}',
                email=f'{nome.lower().replace(" ", "")}{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'email': user.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user, prof


def _login_admin(client, empresa):
    email = f'admin{empresa.id}@teste.com'
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(name='Admin', username=f'admin{empresa.id}', email=email,
                    empresa_id=empresa.id, role='empresa_admin')
        user.set_password('senha123')
        db.session.add(user)
        db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _criar_comanda_admin(client, empresa, prof, dia=None):
    """Cria, via o admin, uma comanda já atribuída a `prof`."""
    _login_admin(client, empresa)
    dia = dia or date.today()
    c = Comanda(codigo=(Comanda.query.filter_by(empresa_id=empresa.id).count() + 1),
                empresa_id=empresa.id, data=dia, profissional_id=prof.id, status='aberta')
    c.itens.append(ComandaItem(descricao='Corte', valor=50, quantidade=1))
    db.session.add(c)
    db.session.commit()
    client.get('/admin/logout')
    return c.id


def test_profissional_fecha_propria_comanda_de_qualquer_data(client):
    empresa = make_empresa()
    _, prof = _login_profissional(client, empresa)
    # recriar sessão: a criação da comanda via _criar_comanda_admin desloga o client
    c_id = _criar_comanda_admin(client, empresa, prof, dia=date.today() - timedelta(days=10))
    _login_profissional_relogin(client, prof)

    resp = client.post(f'/admin/financeiro/comandas/{c_id}', data={
        'data': (date.today() - timedelta(days=10)).isoformat(), 'status': 'aberta',
        'nome_cliente': '', 'observacoes': '', 'cliente_id': '', 'unidade_id': '',
        'profissional_id': str(prof.id), 'desconto': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    resp = client.post(f'/admin/financeiro/comandas/{c_id}/pagamento', data={
        'forma_pagamento': 'dinheiro', 'valor': '50,00', 'parcelas': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    c = db.session.get(Comanda, c_id)
    assert c.status == 'fechada'  # pagamento integral fecha automaticamente


def _login_profissional_relogin(client, prof):
    user = User.query.filter_by(profissional_id=prof.id).first()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)


def test_profissional_nao_mexe_em_comanda_de_outro_profissional(client):
    empresa = make_empresa()
    _, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    client.get('/admin/logout')

    c_id = _criar_comanda_admin(client, empresa, prof_b)

    _login_profissional_relogin(client, prof_a)
    resp = client.get(f'/admin/financeiro/comandas/{c_id}')
    assert resp.status_code == 403

    resp = client.post(f'/admin/financeiro/comandas/{c_id}/fechar')
    assert resp.status_code == 403

    resp = client.post(f'/admin/financeiro/comandas/{c_id}/pagamento', data={
        'forma_pagamento': 'dinheiro', 'valor': '50,00', 'parcelas': '1',
    })
    assert resp.status_code == 403


def test_profissional_so_ve_as_proprias_comandas_na_listagem(client):
    empresa = make_empresa()
    _, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    client.get('/admin/logout')

    c_a = _criar_comanda_admin(client, empresa, prof_a)
    c_b = _criar_comanda_admin(client, empresa, prof_b)

    _login_profissional_relogin(client, prof_a)
    resp = client.get('/admin/financeiro/comandas')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert f'/admin/financeiro/comandas/{c_a}' in body
    assert f'/admin/financeiro/comandas/{c_b}' not in body


def test_criar_comanda_como_profissional_forca_responsavel_a_ser_ele_mesmo(client):
    empresa = make_empresa()
    _, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    _login_profissional_relogin(client, prof_a)

    resp = client.post('/admin/financeiro/comandas/nova', data={
        'data': date.today().isoformat(), 'status': 'aberta', 'nome_cliente': 'Cliente X',
        'observacoes': '', 'cliente_id': '', 'unidade_id': '',
        'profissional_id': str(prof_b.id),  # tenta atribuir a outro profissional
        'desconto': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200
    c = Comanda.query.filter_by(empresa_id=empresa.id, nome_cliente='Cliente X').first()
    assert c is not None
    assert c.profissional_id == prof_a.id  # forçado para o próprio, ignorando o form
