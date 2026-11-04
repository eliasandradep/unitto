"""Contas a Pagar/Receber passam a ter unidade — filtro e coluna só aparecem
quando a empresa tem mais de uma unidade ativa (mesmo padrão de "pula
pergunta" já usado no agendamento). ContaReceber gerada a partir de Comanda
herda a unidade da comanda automaticamente."""
from datetime import date, time
from models import db, User, Unidade, ContaPagar, ContaReceber, Comanda
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


def _duas_unidades(empresa):
    u1 = Unidade(nome='Varginha', cidade='Varginha', estado='MG', ativo=True, empresa_id=empresa.id)
    u2 = Unidade(nome='São José dos Campos', cidade='São José dos Campos', estado='SP',
                 ativo=True, empresa_id=empresa.id)
    db.session.add_all([u1, u2])
    db.session.commit()
    return u1, u2


def test_filtro_e_coluna_de_unidade_so_aparecem_com_mais_de_uma_unidade(client):
    empresa = make_empresa()
    _login(client, empresa)

    # sem nenhuma unidade cadastrada — não deve aparecer filtro nem coluna
    resp = client.get('/admin/financeiro/contas-a-pagar')
    html = resp.get_data(as_text=True)
    assert 'name="unidade"' not in html

    _duas_unidades(empresa)
    resp2 = client.get('/admin/financeiro/contas-a-pagar')
    html2 = resp2.get_data(as_text=True)
    assert 'name="unidade"' in html2
    assert 'Varginha' in html2


def test_nova_conta_a_pagar_grava_unidade_id(client):
    empresa = make_empresa()
    _login(client, empresa)
    u1, u2 = _duas_unidades(empresa)

    resp = client.post('/admin/financeiro/contas-a-pagar', data={
        'action': 'nova', 'descricao': 'Aluguel SJC', 'valor': '900,00',
        'vencimento': '2026-12-05', 'unidade_id': str(u2.id),
    }, follow_redirects=True)
    assert resp.status_code == 200

    conta = ContaPagar.query.filter_by(empresa_id=empresa.id, descricao='Aluguel SJC').first()
    assert conta is not None
    assert conta.unidade_id == u2.id


def test_filtro_por_unidade_so_retorna_contas_daquela_unidade(client):
    empresa = make_empresa()
    _login(client, empresa)
    u1, u2 = _duas_unidades(empresa)
    db.session.add_all([
        ContaPagar(descricao='Conta Varginha', valor=100, vencimento=date(2026, 12, 1),
                   unidade_id=u1.id, empresa_id=empresa.id),
        ContaPagar(descricao='Conta SJC', valor=200, vencimento=date(2026, 12, 2),
                   unidade_id=u2.id, empresa_id=empresa.id),
    ])
    db.session.commit()

    resp = client.get(f'/admin/financeiro/contas-a-pagar?unidade={u1.id}')
    html = resp.get_data(as_text=True)
    assert 'Conta Varginha' in html
    assert 'Conta SJC' not in html


def test_conta_receber_de_comanda_herda_unidade_da_comanda(client):
    """_sync_conta_receber deve setar unidade_id = comanda.unidade_id ao
    fechar a comanda com saldo devedor."""
    from admin.routes import _sync_conta_receber
    empresa = make_empresa()
    u1, u2 = _duas_unidades(empresa)

    comanda = Comanda(codigo=1, data=date(2026, 12, 1), nome_cliente='Cliente Teste',
                       status='fechada', empresa_id=empresa.id, unidade_id=u2.id)
    db.session.add(comanda)
    db.session.flush()
    from models import ComandaItem
    db.session.add(ComandaItem(comanda_id=comanda.id, descricao='Corte', valor=100, quantidade=1))
    db.session.commit()

    _sync_conta_receber(comanda)
    db.session.commit()

    cr = ContaReceber.query.filter_by(comanda_id=comanda.id).first()
    assert cr is not None
    assert cr.unidade_id == u2.id
