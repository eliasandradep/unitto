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
    resp = client.post('/admin/login', data={'username': saas_admin.username, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/saas-admin/'

    # Sem deslogar explicitamente, tenta logar como usuário do tenant — antes
    # do fix, isso era ignorado e o app mandava de volta pro saas_admin.
    resp2 = client.post('/admin/login', data={'username': tenant_user.username, 'password': 'senha123'},
                         follow_redirects=False)
    assert resp2.status_code == 302
    assert 'saas-admin' not in resp2.location
