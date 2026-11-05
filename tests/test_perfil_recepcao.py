"""Perfil 'recepcao' (role='recepcionista', ou Profissional.perfil_acesso=
'recepcao') ganha acesso às telas de catálogo (mesmo critério do atendente),
mas continua fora de Usuários, Configurações, Financeiro e Integrações —
cadastros estratégicos, não de catálogo. Exclusão nas telas de catálogo
continua restrita a administrador."""
from models import db, User, Categoria
from tests.conftest import make_empresa


def _login_recepcionista(client, empresa):
    """role='recepcionista' direto no User — caminho usado hoje em produção,
    sem passar por Profissional.perfil_acesso."""
    user = User(name='Recepção', username=f'recepcao{empresa.id}', email=f'recepcao{empresa.id}@teste.com',
                empresa_id=empresa.id, role='recepcionista')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'email': user.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_recepcao_acessa_telas_de_catalogo(client):
    empresa = make_empresa()
    _login_recepcionista(client, empresa)

    for url in ('/admin/servicos', '/admin/categorias', '/admin/produtos',
                '/admin/produtos/categorias', '/admin/profissionais',
                '/admin/unidades', '/admin/expedientes', '/admin/servicos/pacotes'):
        resp = client.get(url)
        assert resp.status_code == 200, f'{url} deveria ser 200 pra recepção, veio {resp.status_code}'


def test_recepcao_nao_acessa_cadastros_estrategicos(client):
    empresa = make_empresa()
    _login_recepcionista(client, empresa)

    for url in ('/admin/users', '/admin/users/new', '/admin/configuracoes',
                '/admin/financeiro/contas-a-pagar', '/admin/financeiro/contas-a-receber',
                '/admin/integracoes'):
        resp = client.get(url)
        assert resp.status_code == 403, f'{url} deveria ser 403 pra recepção, veio {resp.status_code}'


def test_recepcao_nao_exclui_categoria(client):
    empresa = make_empresa()
    _login_recepcionista(client, empresa)
    cat = Categoria(nome='Cabelo', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()

    resp = client.post('/admin/categorias', data={'action': 'delete', 'id': cat.id})
    assert resp.status_code == 403
    assert db.session.get(Categoria, cat.id) is not None
