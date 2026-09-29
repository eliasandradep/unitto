"""Login deve processar as credenciais enviadas mesmo com uma sessão antiga
ainda ativa no navegador, em vez de ignorá-las e redirecionar pra sessão
anterior (bug observado: logar como tenant enquanto a sessão do saas_admin
ainda estava ativa mandava de volta pro saas_admin, ignorando o formulário)."""
from models import db, User
from tests.conftest import make_empresa


def _criar_user(role, empresa_id=None, username=None, senha='senha123'):
    username = username or f'{role}-{empresa_id or "saas"}'
    user = User(name='Teste', username=username, email=f'{username}@teste.com',
                empresa_id=empresa_id, role=role)
    user.set_password(senha)
    db.session.add(user)
    db.session.commit()
    return user


def test_login_com_sessao_antiga_ativa_processa_credenciais_novas(client):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    saas_admin = _criar_user('saas_admin')
    tenant_user = _criar_user('empresa_admin', empresa_id=empresa.id, username='tenantuser')

    # Loga primeiro como saas_admin — sessão fica ativa no client (cookies)
    resp = client.post('/admin/login', data={'email': saas_admin.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/saas-admin/'

    # Sem deslogar explicitamente, tenta logar como usuário do tenant — antes
    # do fix, isso era ignorado e o app mandava de volta pro saas_admin.
    resp2 = client.post('/admin/login', data={'email': tenant_user.email, 'password': 'senha123'},
                         follow_redirects=False)
    assert resp2.status_code == 302
    assert 'saas-admin' not in resp2.location


def test_login_e_exclusivamente_por_email(client):
    """Decisão de produto: username/CPF/telefone deixam de autenticar — só
    e-mail+senha entra. Os outros campos continuam existindo no cadastro
    (usados em outras telas), só não servem mais de credencial de login."""
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    user = User(name='Teste', username='meuusuario', email='pessoa@teste.com',
                cpf='123.456.789-00', phone='(11) 98888-7777',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()

    for identificador in ('meuusuario', '123.456.789-00', '(11) 98888-7777'):
        resp = client.post('/admin/login', data={'email': identificador, 'password': 'senha123'})
        assert resp.status_code == 200  # fica na tela de login (falhou), não redireciona
        assert 'incorretos' in resp.get_data(as_text=True).lower()

    resp_ok = client.post('/admin/login', data={'email': 'pessoa@teste.com', 'password': 'senha123'},
                           follow_redirects=False)
    assert resp_ok.status_code == 302
    assert '/login' not in resp_ok.location
