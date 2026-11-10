"""Bug real: Comanda.codigo era UNIQUE na tabela inteira, mas _next_codigo()
calcula o próximo número POR EMPRESA (cada empresa começa do 1). A 2ª
empresa do SaaS a tentar faturar sua primeira comanda batia num
IntegrityError (codigo=1 já usado pela 1ª empresa) e caía num 500. Corrigido
trocando a constraint pra (empresa_id, codigo) — ver _migrate_comanda_codigo_
por_empresa em app.py para a migração em produção (Postgres)."""
from datetime import date, time, timedelta

from models import db, User, Comanda, Agendamento
from tests.conftest import make_empresa, make_booking_setup


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _criar_e_faturar(client, empresa, nome_cliente):
    servico, prof = make_booking_setup(empresa)
    dia = date.today() + timedelta(days=1)
    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente=nome_cliente, data=dia, hora_inicio=time(10, 0),
                      duracao_min=60, status='agendado')
    ag.servicos_lista = [servico]
    db.session.add(ag)
    db.session.commit()
    resp = client.post(f'/admin/api/ag/{ag.id}/comanda')
    assert resp.status_code == 200
    return resp.get_json()


def test_duas_empresas_podem_ter_comanda_codigo_1(client):
    empresa1 = make_empresa(nome='Empresa Codigo 1')
    _login_admin(client, empresa1)
    data1 = _criar_e_faturar(client, empresa1, 'Cliente Empresa 1')
    assert data1['codigo'] == 1

    client.get('/admin/logout')

    empresa2 = make_empresa(nome='Empresa Codigo 2')
    _login_admin(client, empresa2)
    data2 = _criar_e_faturar(client, empresa2, 'Cliente Empresa 2')
    assert data2['codigo'] == 1  # não deve colidir com a comanda #1 da empresa1

    assert Comanda.query.filter_by(empresa_id=empresa1.id, codigo=1).count() == 1
    assert Comanda.query.filter_by(empresa_id=empresa2.id, codigo=1).count() == 1


def test_codigo_continua_unico_dentro_da_mesma_empresa(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    d1 = _criar_e_faturar(client, empresa, 'Cliente A')
    d2 = _criar_e_faturar(client, empresa, 'Cliente B')
    assert d1['codigo'] != d2['codigo']
    assert {d1['codigo'], d2['codigo']} == {1, 2}
