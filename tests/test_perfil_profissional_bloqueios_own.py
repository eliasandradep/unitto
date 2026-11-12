"""Regra de negócio: o perfil de acesso 'profissional' (Profissional.perfil_acesso
== 'profissional') pode acessar a tela de Bloqueios de Agenda, mas só para
criar/editar/excluir bloqueios da PRÓPRIA agenda — nunca um bloqueio geral
(sem profissional) nem de outro profissional. O perfil 'pessoal' (que também
tem agenda_scope() == 'own') continua sem acesso a essa tela, pois a regra
foi pedida especificamente para o perfil 'profissional'. Ver
admin/permissions.py (bloqueios_pode_gerenciar) e admin/routes.py
(agenda_bloqueios, agenda_bloqueio_editar, agenda_bloqueio_excluir)."""
from datetime import date, timedelta

from models import db, User, Profissional, BloqueioAgenda
from tests.conftest import make_empresa


def _login_profissional(client, empresa, nome='Prof A', perfil='profissional'):
    prof = Profissional(nome=nome, empresa_id=empresa.id, ativo=True, perfil_acesso=perfil)
    db.session.add(prof)
    db.session.flush()
    user = User(name=nome, username=f'{nome.lower().replace(" ", "")}{empresa.id}',
                email=f'{nome.lower().replace(" ", "")}{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'email': user.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user, prof


def _login_admin(client, empresa):
    email = f'admin{empresa.id}@teste.com'
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(name='Admin', username=f'admin{empresa.id}', email=email,
                    empresa_id=empresa.id, role='empresa_admin')
        user.set_password('senha123')
        db.session.add(user)
        db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _criar_bloqueio_admin(client, empresa, prof_id, dia=None):
    """Cria, via o admin, um bloqueio de dia inteiro já atribuído a `prof_id`
    (ou geral, se None)."""
    _login_admin(client, empresa)
    dia = dia or date.today()
    b = BloqueioAgenda(empresa_id=empresa.id, profissional_id=prof_id,
                        data_inicio=dia, data_fim=dia, dia_inteiro=True)
    db.session.add(b)
    db.session.commit()
    client.get('/admin/logout')
    return b.id


def _login_relogin(client, user):
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)


def test_profissional_acessa_tela_e_cria_bloqueio_para_si_mesmo(client):
    empresa = make_empresa()
    _, prof = _login_profissional(client, empresa)

    resp = client.get('/admin/agenda/bloqueios')
    assert resp.status_code == 200

    hoje = date.today()
    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof.id),
        'data_inicio': hoje.isoformat(), 'data_fim': hoje.isoformat(),
        'dia_inteiro': '1', 'motivo': 'Consulta médica',
    }, follow_redirects=True)
    assert resp.status_code == 200

    b = BloqueioAgenda.query.filter_by(empresa_id=empresa.id).first()
    assert b is not None
    assert b.profissional_id == prof.id


def test_profissional_tenta_criar_bloqueio_geral_ou_de_outro_forca_para_si_mesmo(client):
    empresa = make_empresa()
    user, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    _login_relogin(client, user)

    hoje = date.today()
    # tenta criar bloqueio "geral" (sem profissional)
    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': '',
        'data_inicio': hoje.isoformat(), 'data_fim': hoje.isoformat(),
        'dia_inteiro': '1', 'motivo': 'Feriado',
    }, follow_redirects=True)
    assert resp.status_code == 200
    b1 = BloqueioAgenda.query.filter_by(empresa_id=empresa.id, motivo='Feriado').first()
    assert b1 is not None
    assert b1.profissional_id == prof_a.id

    # tenta criar bloqueio atribuído ao Prof B
    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof_b.id),
        'data_inicio': hoje.isoformat(), 'data_fim': hoje.isoformat(),
        'dia_inteiro': '1', 'motivo': 'Tentativa outro prof',
    }, follow_redirects=True)
    assert resp.status_code == 200
    b2 = BloqueioAgenda.query.filter_by(empresa_id=empresa.id, motivo='Tentativa outro prof').first()
    assert b2 is not None
    assert b2.profissional_id == prof_a.id


def test_profissional_nao_ve_bloqueio_de_outro_profissional_na_listagem(client):
    empresa = make_empresa()
    user, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    client.get('/admin/logout')

    _criar_bloqueio_admin(client, empresa, prof_a.id)
    _criar_bloqueio_admin(client, empresa, prof_b.id)
    # Bloqueio geral (profissional_id=None) numa data fixa bem no passado —
    # de propósito fora de "hoje", pra não vazar como falso conflito em
    # outros testes que chamam get_available_slots sem contexto de tenant
    # (tq() despenca pra query sem filtro quando g.empresa_id não está setado).
    _criar_bloqueio_admin(client, empresa, None, dia=date(2000, 1, 1))

    _login_relogin(client, user)
    resp = client.get('/admin/agenda/bloqueios')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Prof B' not in body
    assert 'Todos os profissionais' not in body


def test_profissional_nao_pode_editar_ou_excluir_bloqueio_de_outro_profissional(client):
    empresa = make_empresa()
    user, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    client.get('/admin/logout')

    b_id = _criar_bloqueio_admin(client, empresa, prof_b.id)

    _login_relogin(client, user)
    resp = client.post(f'/admin/agenda/bloqueios/{b_id}/editar', data={
        'profissional_id': str(prof_b.id),
        'data_inicio': date.today().isoformat(), 'data_fim': date.today().isoformat(),
        'dia_inteiro': '1',
    })
    assert resp.status_code == 403

    resp = client.post(f'/admin/agenda/bloqueios/{b_id}/excluir')
    assert resp.status_code == 403
    assert db.session.get(BloqueioAgenda, b_id) is not None


def test_profissional_edita_proprio_bloqueio_mas_nao_consegue_reatribuir_a_outro(client):
    empresa = make_empresa()
    user, prof_a = _login_profissional(client, empresa, nome='Prof A')
    client.get('/admin/logout')
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    client.get('/admin/logout')

    b_id = _criar_bloqueio_admin(client, empresa, prof_a.id)

    _login_relogin(client, user)
    hoje = date.today()
    resp = client.post(f'/admin/agenda/bloqueios/{b_id}/editar', data={
        'profissional_id': str(prof_b.id),  # tenta reatribuir a outro profissional
        'data_inicio': hoje.isoformat(), 'data_fim': hoje.isoformat(),
        'dia_inteiro': '1', 'motivo': 'Atualizado',
    }, follow_redirects=True)
    assert resp.status_code == 200
    b = db.session.get(BloqueioAgenda, b_id)
    assert b.motivo == 'Atualizado'
    assert b.profissional_id == prof_a.id  # permanece com o próprio


def test_perfil_pessoal_nao_acessa_tela_de_bloqueios(client):
    """O perfil 'pessoal' também tem agenda_scope() == 'own', mas a regra foi
    pedida só para o perfil 'profissional' — 'pessoal' continua sem acesso."""
    empresa = make_empresa()
    _login_profissional(client, empresa, nome='Prof Pessoal', perfil='pessoal')

    resp = client.get('/admin/agenda/bloqueios')
    assert resp.status_code == 403
