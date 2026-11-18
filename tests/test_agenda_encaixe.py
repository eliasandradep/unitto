"""Encaixe (duplo-agendamento no mesmo horário pra mesma profissional) na
agenda interna — qualquer perfil interno pode (administrador/atendente/
profissional/recepção/pessoal); só o agendamento online (cliente externo,
sem login) nunca pode, e agora bloqueia incondicionalmente, sem a brecha
antiga de Profissional.agendamentos_simult."""
from datetime import date, time, timedelta

from models import db, User, Profissional, Agendamento
from public.availability import get_available_slots
from tests.conftest import make_empresa, make_booking_setup


def _amanha():
    return date.today() + timedelta(days=1)


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _login_perfil(client, empresa, perfil, prof=None):
    """perfil in ('atendente', 'recepcao', 'profissional', 'pessoal')."""
    if prof is None:
        prof = Profissional(nome=f'{perfil} teste', empresa_id=empresa.id, ativo=True, perfil_acesso=perfil)
        db.session.add(prof)
        db.session.flush()
    else:
        prof.perfil_acesso = perfil
    user = User(name=perfil.title(), username=f'{perfil}{prof.id}', email=f'{perfil}{prof.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user, prof


def _criar_agendamento_existente(empresa, prof, servico, dia, hora='10:00'):
    h, m = map(int, hora.split(':'))
    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente='Cliente Original', data=dia, hora_inicio=time(h, m),
                      duracao_min=60, status='agendado')
    db.session.add(ag)
    db.session.commit()
    return ag


def test_administrador_consegue_encaixar(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia)

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(), 'hora_inicio': '10:00', 'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Encaixada', 'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Encaixada').first() is not None


def test_atendente_consegue_encaixar(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia)
    _login_perfil(client, empresa, 'atendente')

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(), 'hora_inicio': '10:00', 'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Encaixada Atendente', 'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Encaixada Atendente').first() is not None


def test_profissional_consegue_encaixar_na_propria_agenda(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia)
    _login_perfil(client, empresa, 'profissional', prof=prof)

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(), 'hora_inicio': '10:00', 'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Encaixada Profissional', 'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Encaixada Profissional').first() is not None


def test_recepcao_consegue_encaixar(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia)
    _login_perfil(client, empresa, 'recepcao')

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(), 'hora_inicio': '10:00', 'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Encaixada Recepcao', 'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Encaixada Recepcao').first() is not None


def test_pessoal_consegue_encaixar_na_propria_agenda(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia)
    _login_perfil(client, empresa, 'pessoal', prof=prof)

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(), 'hora_inicio': '10:00', 'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Encaixada Pessoal', 'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Encaixada Pessoal').first() is not None


def test_editar_para_sobrepor_e_permitido_pra_recepcao(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia, hora='10:00')
    ag2 = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                       nome_cliente='Cliente a Editar', data=dia, hora_inicio=time(14, 0),
                       duracao_min=60, status='agendado')
    db.session.add(ag2)
    db.session.commit()
    ag2_id = ag2.id
    _login_perfil(client, empresa, 'recepcao')

    resp = client.post(f'/admin/agenda/{ag2_id}/editar', data={
        'data': dia.isoformat(), 'hora_inicio': '10:00', 'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente a Editar', 'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(ag2)
    assert ag2.hora_inicio == time(10, 0)  # mudou — edição com encaixe permitida


def test_agendamento_online_sempre_bloqueia_mesmo_com_flag_antiga_ligada():
    """Prova que o atalho antigo (Profissional.agendamentos_simult liberando
    sobreposição no caminho online) foi removido de verdade."""
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    prof.agendamentos_simult = True  # flag antiga, agora sem nenhum efeito
    db.session.commit()
    dia = _amanha()
    _criar_agendamento_existente(empresa, prof, servico, dia, hora='10:00')

    slots = get_available_slots(prof.id, servico, dia)
    assert time(10, 0) not in slots
