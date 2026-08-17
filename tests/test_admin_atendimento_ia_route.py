"""Autorização no backend da tela de configuração — não só esconder no
frontend. Tenant fora do plano PRO recebe 404 mesmo acessando a URL direto."""
from models import db, User
from tests.conftest import make_empresa


def _login(client, empresa, role='empresa_admin'):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role=role)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'username': user.username, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_atendimento_ia_404_para_plano_nao_pro(client):
    empresa = make_empresa(plano='free', atendimento_ia_ativo=False)
    _login(client, empresa)
    resp = client.get('/admin/atendimento-ia')
    assert resp.status_code == 404


def test_atendimento_ia_200_para_plano_pro_mesmo_com_toggle_desligado(client):
    """Tenant PRO precisa conseguir ABRIR a tela mesmo com o toggle ainda
    desligado — é como ele liga a feature pela primeira vez (autoativação)."""
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=False)
    _login(client, empresa)
    resp = client.get('/admin/atendimento-ia')
    assert resp.status_code == 200


def test_toggle_post_ativa_atendimento_ia(client):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=False)
    _login(client, empresa)
    resp = client.post('/admin/atendimento-ia', data={'section': 'toggle', 'atendimento_ia_ativo': 'on'},
                        follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(empresa)
    assert empresa.atendimento_ia_ativo is True


def test_post_404_para_plano_nao_pro_mesmo_direto_no_endpoint(client):
    """Autorização está na rota (backend), não só escondendo o link no
    template — um POST direto tentando ligar o toggle também é bloqueado."""
    empresa = make_empresa(plano='free', atendimento_ia_ativo=False)
    _login(client, empresa)
    resp = client.post('/admin/atendimento-ia', data={'section': 'toggle', 'atendimento_ia_ativo': 'on'})
    assert resp.status_code == 404
    db.session.refresh(empresa)
    assert empresa.atendimento_ia_ativo is False
