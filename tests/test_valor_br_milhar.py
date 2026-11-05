"""Bug real relatado em produção: lançar uma Conta a Pagar com valor >= mil
reais (ex: "1.200,00", digitado com o separador de milhar que o próprio
placeholder do campo — "0,00" — não deixa claro que não deve ser usado)
dava 'Dados inválidos'. Causa: `.replace(',', '.')` sozinho, sem antes
remover o ponto de milhar, transforma '1.200,00' em '1.200.00' — dois
pontos, que Decimal()/float() rejeitam. Só aparecia com valores >= 1000,
por isso passou despercebido em testes manuais com valores menores. Corrigido
centralizando a normalização em `_parse_valor_br` (admin/routes.py)."""
from decimal import Decimal

from models import db, User, ContaPagar, ContaReceber
from admin.routes import _parse_valor_br
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_parse_valor_br_milhar():
    assert _parse_valor_br('1.200,00') == '1200.00'
    assert _parse_valor_br('258,58') == '258.58'
    assert _parse_valor_br('1.234.567,89') == '1234567.89'
    assert _parse_valor_br('1234.56') == '1234.56'   # já em formato decimal (ex: campo JS)
    assert _parse_valor_br('') == ''
    assert _parse_valor_br('', '0') == '0'


def test_criar_conta_a_pagar_com_valor_acima_de_mil(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/financeiro/contas-a-pagar', data={
        'action': 'nova',
        'descricao': 'Aluguel',
        'valor': '1.200,00',
        'vencimento': '2026-12-05',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Dados inv\xc3\xa1lidos' not in resp.data

    conta = ContaPagar.query.filter_by(empresa_id=empresa.id, descricao='Aluguel').first()
    assert conta is not None
    assert conta.valor == Decimal('1200.00')


def test_criar_conta_a_receber_com_valor_acima_de_mil(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/financeiro/contas-a-receber', data={
        'action': 'nova',
        'descricao': 'Pacote fechado',
        'valor': '2.350,90',
        'vencimento': '2026-12-10',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Dados inv\xc3\xa1lidos' not in resp.data

    conta = ContaReceber.query.filter_by(empresa_id=empresa.id, descricao='Pacote fechado').first()
    assert conta is not None
    assert conta.valor == Decimal('2350.90')
