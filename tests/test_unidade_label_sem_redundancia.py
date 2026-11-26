"""Bug relatado: quando a unidade se chama igual à cidade (ex: nome="São José
dos Campos", cidade="São José dos Campos", estado="SP" — exatamente os dados
seed de app.py para o tenant Renata Rosa), Unidade.label() duplicava a
informação: "São José dos Campos — São José dos Campos/SP". Corrigido pra
"São José dos Campos — SP" nesse caso (cidade só some quando é igual ao
nome; quando são diferentes continua mostrando os dois, ex: "Loja Centro —
Belo Horizonte/MG"). Também existiam vários <select> de Unidade pela
aplicação que montavam esse mesmo texto manualmente em vez de chamar
label() — unificados aqui."""
from models import db, Unidade
from tests.conftest import make_empresa


def test_label_nao_duplica_quando_nome_igual_a_cidade():
    empresa = make_empresa()
    u = Unidade(nome='São José dos Campos', cidade='São José dos Campos', estado='SP',
                ativo=True, empresa_id=empresa.id)
    db.session.add(u)
    db.session.commit()
    assert u.label() == 'São José dos Campos — SP'


def test_label_mantem_cidade_quando_diferente_do_nome():
    empresa = make_empresa()
    u = Unidade(nome='Loja Centro', cidade='Belo Horizonte', estado='MG',
                ativo=True, empresa_id=empresa.id)
    db.session.add(u)
    db.session.commit()
    assert u.label() == 'Loja Centro — Belo Horizonte/MG'


def test_label_sem_cidade_mostra_so_o_nome():
    empresa = make_empresa()
    u = Unidade(nome='Unidade Sem Endereço', ativo=True, empresa_id=empresa.id)
    db.session.add(u)
    db.session.commit()
    assert u.label() == 'Unidade Sem Endereço'


def _login_admin(client, empresa):
    from models import User
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)


def _duas_unidades_redundantes(empresa):
    u1 = Unidade(nome='Varginha', cidade='Varginha', estado='MG', ativo=True, empresa_id=empresa.id)
    u2 = Unidade(nome='São José dos Campos', cidade='São José dos Campos', estado='SP',
                 ativo=True, empresa_id=empresa.id)
    db.session.add_all([u1, u2])
    db.session.commit()
    return u1, u2


def test_select_de_unidade_na_agenda_sem_redundancia(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    _duas_unidades_redundantes(empresa)

    resp = client.get('/admin/agenda')
    html = resp.data.decode('utf-8')
    assert 'São José dos Campos — SP' in html
    assert 'São José dos Campos — São José dos Campos' not in html
    assert 'Varginha — MG' in html
    assert 'Varginha — Varginha' not in html


def test_select_de_unidade_em_contas_a_pagar_sem_redundancia(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    _duas_unidades_redundantes(empresa)

    resp = client.get('/admin/financeiro/contas-a-pagar')
    html = resp.data.decode('utf-8')
    assert 'São José dos Campos — SP' in html
    assert 'São José dos Campos — São José dos Campos' not in html
