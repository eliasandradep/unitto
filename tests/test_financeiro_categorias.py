"""Categoria de Contas a Pagar/Receber deixa de ser texto livre e passa a
ser selecionada de uma lista pré-cadastrada (CategoriaFinanceira), com tela
própria de gestão — mesmo padrão já usado em Categorias de Produtos."""
from datetime import date
from models import db, User, CategoriaFinanceira, ContaPagar, ContaReceber
from tests.conftest import make_empresa


def _login(client, empresa, role='empresa_admin'):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role=role)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'email': user.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_criar_editar_e_listar_categoria_financeira(client):
    empresa = make_empresa()
    _login(client, empresa)

    resp = client.post('/admin/financeiro/categorias',
                        data={'action': 'save', 'nome': 'Aluguel', 'descricao': 'Aluguel do salão'},
                        follow_redirects=True)
    assert resp.status_code == 200
    cat = CategoriaFinanceira.query.filter_by(empresa_id=empresa.id, nome='Aluguel').first()
    assert cat is not None
    assert cat.descricao == 'Aluguel do salão'
    assert cat.ativo is True

    resp2 = client.post('/admin/financeiro/categorias',
                         data={'action': 'save', 'id': cat.id, 'nome': 'Aluguel e Condomínio', 'descricao': ''},
                         follow_redirects=True)
    assert resp2.status_code == 200
    db.session.refresh(cat)
    assert cat.nome == 'Aluguel e Condomínio'
    assert cat.descricao is None


def test_toggle_e_delete_categoria_financeira(client):
    empresa = make_empresa()
    _login(client, empresa)
    cat = CategoriaFinanceira(nome='Marketing', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()
    cat_id = cat.id

    client.post('/admin/financeiro/categorias', data={'action': 'toggle', 'id': cat_id})
    db.session.refresh(cat)
    assert cat.ativo is False

    resp = client.post('/admin/financeiro/categorias', data={'action': 'delete', 'id': cat_id},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(CategoriaFinanceira, cat_id) is None


def test_categoria_em_uso_nao_pode_ser_excluida(client):
    empresa = make_empresa()
    _login(client, empresa)
    cat = CategoriaFinanceira(nome='Fornecedores', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.flush()
    db.session.add(ContaPagar(descricao='Compra de produtos', valor=100, vencimento=date(2026, 12, 1),
                               categoria_id=cat.id, empresa_id=empresa.id))
    db.session.commit()
    cat_id = cat.id

    resp = client.post('/admin/financeiro/categorias', data={'action': 'delete', 'id': cat_id},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(CategoriaFinanceira, cat_id) is not None  # não foi excluída
    assert 'em uso' in resp.get_data(as_text=True).lower()


def test_nova_conta_a_pagar_grava_categoria_id(client):
    empresa = make_empresa()
    _login(client, empresa)
    cat = CategoriaFinanceira(nome='Aluguel', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()

    resp = client.post('/admin/financeiro/contas-a-pagar', data={
        'action': 'nova', 'descricao': 'Aluguel de novembro', 'valor': '1500,00',
        'vencimento': '2026-12-05', 'categoria_id': str(cat.id),
    }, follow_redirects=True)
    assert resp.status_code == 200

    conta = ContaPagar.query.filter_by(empresa_id=empresa.id, descricao='Aluguel de novembro').first()
    assert conta is not None
    assert conta.categoria_id == cat.id
    assert conta.categoria_financeira.nome == 'Aluguel'


def test_nova_conta_a_receber_grava_categoria_id(client):
    empresa = make_empresa()
    _login(client, empresa)
    cat = CategoriaFinanceira(nome='Serviços', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()

    resp = client.post('/admin/financeiro/contas-a-receber', data={
        'action': 'nova', 'descricao': 'Pacote de mechas', 'valor': '680,00',
        'vencimento': '2026-12-10', 'categoria_id': str(cat.id),
    }, follow_redirects=True)
    assert resp.status_code == 200

    conta = ContaReceber.query.filter_by(empresa_id=empresa.id, descricao='Pacote de mechas').first()
    assert conta is not None
    assert conta.categoria_id == cat.id
    assert conta.categoria_financeira.nome == 'Serviços'


def test_conta_pagar_legado_sem_categoria_id_cai_no_texto_livre(client):
    """Conta antiga criada antes dessa migração (campo texto livre
    'categoria', sem categoria_id) continua exibindo o texto legado — nada
    deve quebrar nem some da listagem."""
    empresa = make_empresa()
    _login(client, empresa)
    db.session.add(ContaPagar(descricao='Conta antiga', valor=50, vencimento=date(2026, 11, 1),
                               categoria='Água e luz', empresa_id=empresa.id))
    db.session.commit()

    resp = client.get('/admin/financeiro/contas-a-pagar')
    assert resp.status_code == 200
    assert 'Água e luz' in resp.get_data(as_text=True)
