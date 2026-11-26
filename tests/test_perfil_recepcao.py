"""Perfil 'recepcao' (role='recepcionista', ou Profissional.perfil_acesso=
'recepcao') ganha acesso às telas de catálogo (mesmo critério do atendente)
e também ao Dashboard, Leads e ao resumo Financeiro — precisa acompanhar
isso no dia a dia (ver tem_acesso_dashboard() em admin/permissions.py).
Continua fora de Usuários, Configurações, Contas a Pagar/Receber e
Integrações — cadastros estratégicos. Exclusão nas telas de catálogo
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


def test_recepcao_acessa_dashboard_leads_e_financeiro(client):
    """Recepção precisa acompanhar o dashboard geral, a lista de leads e o
    resumo financeiro no dia a dia — só Contas a Pagar/Receber (cadastro
    estratégico) continuam fora, cobertos por
    test_recepcao_nao_acessa_cadastros_estrategicos."""
    empresa = make_empresa()
    _login_recepcionista(client, empresa)

    for url in ('/admin/dashboard', '/admin/leads', '/admin/financeiro'):
        resp = client.get(url)
        assert resp.status_code == 200, f'{url} deveria ser 200 pra recepção, veio {resp.status_code}'


def test_recepcao_ve_links_de_dashboard_e_leads_no_menu(client):
    empresa = make_empresa()
    _login_recepcionista(client, empresa)

    html = client.get('/admin/dashboard').data.decode('utf-8')
    assert 'href="/admin/dashboard"' in html
    assert 'href="/admin/leads"' in html


def test_outros_perfis_continuam_sem_acesso_ao_dashboard(client):
    """Atendente (agenda 'all', mas não é recepção) continua sem Dashboard/
    Leads — a liberação é específica pro perfil recepção."""
    empresa = make_empresa()
    from models import Profissional
    prof = Profissional(nome='Atendente', empresa_id=empresa.id, perfil_acesso='atendente')
    db.session.add(prof)
    db.session.commit()
    user = User(name='Atendente', username=f'atend{empresa.id}', email=f'atend{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)

    for url in ('/admin/dashboard', '/admin/leads'):
        resp = client.get(url)
        assert resp.status_code == 403, f'{url} deveria ser 403 pra atendente, veio {resp.status_code}'


def test_recepcao_nao_exclui_categoria(client):
    empresa = make_empresa()
    _login_recepcionista(client, empresa)
    cat = Categoria(nome='Cabelo', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()

    resp = client.post('/admin/categorias', data={'action': 'delete', 'id': cat.id})
    assert resp.status_code == 403
    assert db.session.get(Categoria, cat.id) is not None
