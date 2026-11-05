"""A senha de acesso do profissional deixa de ser gerada aleatoriamente —
precisa ser digitada por um administrador, tanto na criação quanto ao
redefinir. Profissional criado por um perfil não-administrador (ex:
atendente, que tem acesso de catálogo) fica sem senha utilizável até um
admin definir uma."""
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


def _login_atendente(client, empresa):
    """'atendente' é um Profissional.perfil_acesso, não um User.role direto."""
    prof = Profissional(nome='Atendente Teste', empresa_id=empresa.id, ativo=True,
                         perfil_acesso='atendente')
    db.session.add(prof)
    db.session.flush()
    user = User(name='Atendente', username=f'atendente{empresa.id}', email=f'atendente{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_admin_cria_profissional_com_senha_definida_por_ele(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/profissionais/novo', data={
        'nome': 'Fernanda Lima',
        'senha': 'minhasenha123',
        'confirmar_senha': 'minhasenha123',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profissional.query.filter_by(nome='Fernanda Lima').first()
    assert prof is not None
    assert prof.user is not None
    assert prof.user.check_password('minhasenha123')


def test_admin_sem_senha_nao_cria_profissional(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/profissionais/novo', data={
        'nome': 'Sem Senha',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Profissional.query.filter_by(nome='Sem Senha').first() is None


def test_admin_com_senhas_diferentes_nao_cria_profissional(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.post('/admin/profissionais/novo', data={
        'nome': 'Senha Divergente',
        'senha': 'senhaabc123',
        'confirmar_senha': 'outraoutra123',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Profissional.query.filter_by(nome='Senha Divergente').first() is None


def test_atendente_cria_profissional_sem_senha_utilizavel(client):
    """Atendente tem acesso ao cadastro de Profissionais (catálogo), mas não
    define senha de acesso — isso fica só com o administrador."""
    empresa = make_empresa()
    _login_atendente(client, empresa)

    resp = client.post('/admin/profissionais/novo', data={
        'nome': 'Criado Por Atendente',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profissional.query.filter_by(nome='Criado Por Atendente').first()
    assert prof is not None
    assert prof.user is not None
    assert not prof.user.password_hash
    assert prof.user.check_password('qualquer-coisa') is False


def test_admin_define_senha_de_profissional_sem_login(client):
    empresa = make_empresa()
    admin = _login_admin(client, empresa)
    prof = Profissional(nome='Precisa De Senha', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    prof_id = prof.id

    resp = client.post(f'/admin/profissionais/{prof_id}/resetar-senha', data={
        'senha': 'novasenha456',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(prof)
    assert prof.user is not None
    assert prof.user.check_password('novasenha456')


def test_resetar_senha_exige_pelo_menos_seis_caracteres(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Prof Curta', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    prof_id = prof.id

    resp = client.post(f'/admin/profissionais/{prof_id}/resetar-senha', data={
        'senha': '123',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(prof)
    assert prof.user is None


def test_atendente_nao_pode_resetar_senha(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)
    prof = Profissional(nome='Alvo Reset', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    prof_id = prof.id

    resp = client.post(f'/admin/profissionais/{prof_id}/resetar-senha', data={
        'senha': 'novasenha456',
    })
    assert resp.status_code == 403
