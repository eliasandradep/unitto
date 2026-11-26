"""Pedido do usuário: as listagens de Contas a Pagar/Receber não tinham
paginação — com muitos registros a tabela ficava enorme. Adiciona paginação
(seletor "por página" acima E abaixo da listagem, mesmo padrão já usado em
/admin/clientes) e remove as colunas Fornecedor/Forma da listagem de Contas
a Pagar (sobravam pouco usadas e a tabela não cabia com o menu lateral
expandido — Forma de pagamento continua disponível no modal "Dar Baixa")."""
from datetime import date, timedelta
from decimal import Decimal

from models import db, User, ContaPagar, ContaReceber
from tests.conftest import make_empresa


def _login(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)


def _criar_contas_pagar(empresa, n):
    base = date.today()
    for i in range(n):
        db.session.add(ContaPagar(
            empresa_id=empresa.id, descricao=f'Conta {i}', valor=Decimal('10.00'),
            vencimento=base + timedelta(days=i), fornecedor=f'Fornecedor {i}',
        ))
    db.session.commit()


def _criar_contas_receber(empresa, n):
    base = date.today()
    for i in range(n):
        db.session.add(ContaReceber(
            empresa_id=empresa.id, descricao=f'Conta {i}', valor=Decimal('10.00'),
            vencimento=base + timedelta(days=i),
        ))
    db.session.commit()


def test_contas_pagar_nao_mostra_mais_fornecedor_e_forma_na_listagem(client):
    empresa = make_empresa()
    _login(client, empresa)
    _criar_contas_pagar(empresa, 1)

    resp = client.get('/admin/financeiro/contas-a-pagar')
    html = resp.data.decode('utf-8')
    assert '<th>Fornecedor</th>' not in html
    assert '<th>Forma</th>' not in html
    # o campo "Fornecedor" do modal "Nova Conta a Pagar" continua existindo
    assert 'name="fornecedor"' in html
    # a forma de pagamento continua disponível no modal "Dar Baixa"
    assert 'name="forma_pagamento"' in html


def test_contas_pagar_pagina_a_listagem(client):
    empresa = make_empresa()
    _login(client, empresa)
    _criar_contas_pagar(empresa, 30)

    resp = client.get('/admin/financeiro/contas-a-pagar?per_page=25')
    html = resp.data.decode('utf-8')
    assert html.count('<tr ') == 25
    assert 'Exibindo 1' in html
    assert 'de 30 conta(s)' in html

    resp2 = client.get('/admin/financeiro/contas-a-pagar?per_page=25&page=2')
    html2 = resp2.data.decode('utf-8')
    assert html2.count('<tr ') == 5


def test_contas_pagar_seletor_de_por_pagina_acima_e_abaixo(client):
    empresa = make_empresa()
    _login(client, empresa)
    _criar_contas_pagar(empresa, 3)

    resp = client.get('/admin/financeiro/contas-a-pagar')
    html = resp.data.decode('utf-8')
    assert html.count('<select name="per_page"') == 2  # um acima, um abaixo da listagem


def test_contas_pagar_total_pendente_nao_muda_entre_paginas(client):
    """Os totalizadores (Pendente/Pago) continuam somando o filtro inteiro,
    não só a página atual sendo exibida."""
    empresa = make_empresa()
    _login(client, empresa)
    _criar_contas_pagar(empresa, 30)

    resp1 = client.get('/admin/financeiro/contas-a-pagar?per_page=10&page=1')
    resp2 = client.get('/admin/financeiro/contas-a-pagar?per_page=10&page=2')
    html1 = resp1.data.decode('utf-8')
    html2 = resp2.data.decode('utf-8')
    total1 = html1[html1.index('Pendente</div>'):][:200]
    total2 = html2[html2.index('Pendente</div>'):][:200]
    assert 'R$ 300,00' in total1
    assert 'R$ 300,00' in total2


def test_contas_receber_pagina_a_listagem(client):
    empresa = make_empresa()
    _login(client, empresa)
    _criar_contas_receber(empresa, 30)

    resp = client.get('/admin/financeiro/contas-a-receber?per_page=25')
    html = resp.data.decode('utf-8')
    assert html.count('<tr ') == 25

    resp2 = client.get('/admin/financeiro/contas-a-receber?per_page=25&page=2')
    html2 = resp2.data.decode('utf-8')
    assert html2.count('<tr ') == 5


def test_per_page_invalido_cai_no_padrao(client):
    empresa = make_empresa()
    _login(client, empresa)
    _criar_contas_pagar(empresa, 3)

    resp = client.get('/admin/financeiro/contas-a-pagar?per_page=99999')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert 'selected' in html  # não quebrou o select do per_page
