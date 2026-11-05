"""Cadastro de Profissional já provisiona o login sozinho (_provision_login).
A tela de Usuários não deve mais permitir criar/promover uma conta pra papel
'profissional' sem vínculo de verdade (profissional_id vazio = conta
"fantasma", sem agenda/comissão, caindo no perfil mínimo 'leitura'). Editar
uma conta de profissional JÁ vinculada continua funcionando normalmente —
só não é mais possível trocar o papel por essa tela."""
from models import db, User, Profissional
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_dropdown_de_papel_nao_oferece_profissional(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    resp = client.get('/admin/users/new')
    html = resp.get_data(as_text=True)
    assert 'value="profissional"' not in html


def test_criar_usuario_com_papel_profissional_e_rejeitado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/users/new', data={
        'name': 'Tentativa Fantasma', 'username': 'fantasma1', 'email': 'fantasma1@teste.com',
        'password': 'senha123456', 'confirm': 'senha123456', 'role': 'profissional',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert 'cadastro de Profissionais' in resp.get_data(as_text=True)
    assert User.query.filter_by(username='fantasma1').first() is None


def test_promover_usuario_existente_para_profissional_e_rejeitado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    alvo = User(name='Recepção', username='recep1', email='recep1@teste.com',
                empresa_id=empresa.id, role='recepcionista')
    alvo.set_password('senha123')
    db.session.add(alvo)
    db.session.commit()
    alvo_id = alvo.id

    resp = client.post(f'/admin/users/{alvo_id}/edit', data={
        'name': 'Recepção', 'username': 'recep1', 'email': 'recep1@teste.com', 'role': 'profissional',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(alvo)
    assert alvo.role == 'recepcionista'  # não mudou


def test_editar_usuario_profissional_ja_vinculado_continua_funcionando(client):
    """Edição de outros campos (nome, telefone) de uma conta de profissional
    já vinculada continua funcionando — só o papel deixa de ser editável
    por aqui, não a conta inteira."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional Vinculado', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.flush()
    user_prof = User(name='Profissional Vinculado', username='profvinc', email='profvinc@teste.com',
                      empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user_prof.set_password('senha123')
    db.session.add(user_prof)
    db.session.commit()
    user_id = user_prof.id

    # tela de edição não deve quebrar e não deve mostrar o <select> de papel
    resp_get = client.get(f'/admin/users/{user_id}/edit')
    assert resp_get.status_code == 200
    assert '<select name="role">' not in resp_get.get_data(as_text=True)

    # salvar sem campo 'role' no POST (como o form realmente envia agora) mantém o papel
    resp = client.post(f'/admin/users/{user_id}/edit', data={
        'name': 'Profissional Vinculado', 'username': 'profvinc', 'email': 'profvinc@teste.com',
        'phone': '11999998888',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(user_prof)
    assert user_prof.role == 'profissional'
    assert user_prof.profissional_id == prof.id
    assert user_prof.phone == '11999998888'
