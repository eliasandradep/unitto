"""Seção de Faturamento no Dashboard: um gráfico (Chart.js) alimentado por
GET /admin/dashboard/faturamento, com filtro padrão "dia atual" e opções de
semana, mês e período específico. Mesma fonte de dados do dashboard
Financeiro (PagamentoComanda de comandas fechadas + RecebimentoCliente,
atribuídos à data da comanda) — por isso só aparece/funciona pra quem tem
acesso de administrador, igual ao link "Financeiro / Dashboard" no menu
(perm.financeiro == 'full'). Ver admin/routes.py (dashboard_faturamento,
_faturamento_por_dia) e admin/__init__.py (_ADMIN_ONLY_ENDPOINTS)."""
from datetime import date, timedelta

from models import db, User, Profissional, Comanda, ComandaItem, PagamentoComanda
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _login_recepcionista(client, empresa):
    user = User(name='Recepção', username=f'recepcao{empresa.id}', email=f'recepcao{empresa.id}@teste.com',
                empresa_id=empresa.id, role='recepcionista')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _criar_comanda_fechada(empresa, dia, valor, codigo):
    prof = Profissional(nome=f'Prof {codigo}', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.flush()
    c = Comanda(codigo=codigo, empresa_id=empresa.id, data=dia, status='fechada', profissional_id=prof.id)
    c.itens.append(ComandaItem(descricao='Serviço', valor=valor, quantidade=1))
    db.session.add(c)
    db.session.flush()
    db.session.add(PagamentoComanda(comanda_id=c.id, forma_pagamento='dinheiro', valor=valor, data_pagamento=dia))
    db.session.commit()
    return c


def test_dashboard_mostra_secao_de_faturamento_pro_admin(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    resp = client.get('/admin/dashboard')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'chartFaturamentoDash' in body
    assert '/admin/dashboard/faturamento' in body


def test_filtro_dia_traz_so_o_faturamento_de_hoje(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    _criar_comanda_fechada(empresa, hoje, 100, codigo=1)
    _criar_comanda_fechada(empresa, hoje - timedelta(days=1), 500, codigo=2)

    resp = client.get('/admin/dashboard/faturamento?periodo=dia')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['labels'] == [hoje.strftime('%d/%m')]
    assert data['values'] == [100.0]
    assert data['total'] == 100.0


def test_filtro_semana_soma_do_inicio_da_semana_at_hoje(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())
    _criar_comanda_fechada(empresa, hoje, 100, codigo=1)
    _criar_comanda_fechada(empresa, inicio_semana, 50, codigo=2)
    if inicio_semana > date(2000, 1, 1):
        _criar_comanda_fechada(empresa, inicio_semana - timedelta(days=1), 999, codigo=3)  # fora da semana

    resp = client.get('/admin/dashboard/faturamento?periodo=semana')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['data_ini'] == inicio_semana.isoformat()
    assert data['data_fim'] == hoje.isoformat()
    assert data['total'] == 150.0


def test_filtro_mes_soma_do_dia_1_at_hoje(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    inicio_mes = hoje.replace(day=1)
    _criar_comanda_fechada(empresa, hoje, 200, codigo=1)
    _criar_comanda_fechada(empresa, inicio_mes, 300, codigo=2)

    resp = client.get('/admin/dashboard/faturamento?periodo=mes')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['data_ini'] == inicio_mes.isoformat()
    assert data['total'] == 500.0


def test_filtro_personalizado_usa_as_datas_informadas(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    d1 = hoje - timedelta(days=10)
    d2 = hoje - timedelta(days=5)
    _criar_comanda_fechada(empresa, d1, 70, codigo=1)
    _criar_comanda_fechada(empresa, d2, 30, codigo=2)
    _criar_comanda_fechada(empresa, hoje, 999, codigo=3)  # fora do período

    resp = client.get(f'/admin/dashboard/faturamento?periodo=personalizado&data_ini={d1.isoformat()}&data_fim={d2.isoformat()}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] == 100.0
    assert len(data['labels']) == (d2 - d1).days + 1


def test_filtro_personalizado_com_datas_invertidas_funciona_normalmente(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    d1 = hoje - timedelta(days=3)
    d2 = hoje
    _criar_comanda_fechada(empresa, hoje, 40, codigo=1)

    # data_ini > data_fim de propósito
    resp = client.get(f'/admin/dashboard/faturamento?periodo=personalizado&data_ini={d2.isoformat()}&data_fim={d1.isoformat()}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['data_ini'] == d1.isoformat()
    assert data['data_fim'] == d2.isoformat()
    assert data['total'] == 40.0


def test_filtro_personalizado_com_data_invalida_retorna_erro(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    resp = client.get('/admin/dashboard/faturamento?periodo=personalizado&data_ini=abc&data_fim=def')
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_filtro_personalizado_com_periodo_maior_que_366_dias_retorna_erro(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    ini = hoje - timedelta(days=400)
    resp = client.get(f'/admin/dashboard/faturamento?periodo=personalizado&data_ini={ini.isoformat()}&data_fim={hoje.isoformat()}')
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_recepcao_nao_acessa_dashboard_nem_o_endpoint_de_faturamento(client):
    """Faturamento no Dashboard é a mesma visão (empresa toda, todos os
    profissionais) do dashboard Financeiro — restrito a administrador."""
    empresa = make_empresa()
    _login_recepcionista(client, empresa)

    resp = client.get('/admin/dashboard')
    assert resp.status_code == 403

    resp = client.get('/admin/dashboard/faturamento?periodo=dia')
    assert resp.status_code == 403
