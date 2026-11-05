"""Expediente (dias/horários de trabalho cadastrados em Profissionais/
Expedientes) só deve restringir o agendamento ONLINE (site público e bot de
WhatsApp, via public/availability.py::get_available_slots). Recepção e a
própria profissional, agendando pelo painel interno (admin/agenda/novo e
.../editar), podem marcar fora desse horário — só bloqueio manual
(BloqueioAgenda) e escala por unidade continuam restringindo qualquer canal."""
from datetime import date, time, timedelta

from models import db, User, Agendamento, BloqueioAgenda
from tests.conftest import make_empresa, make_booking_setup


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _amanha():
    return date.today() + timedelta(days=1)


def test_recepcao_agenda_fora_do_expediente_pelo_painel(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)  # expediente 08:00-18:00 todo dia
    dia = _amanha()

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(),
        'hora_inicio': '20:00',  # fora do expediente (08:00-18:00)
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Fora do Expediente',
        'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert 'Fora do hor' not in resp.get_data(as_text=True)

    ag = Agendamento.query.filter_by(nome_cliente='Cliente Fora do Expediente').first()
    assert ag is not None
    assert ag.hora_inicio == time(20, 0)


def test_editar_agendamento_para_fora_do_expediente_pelo_painel(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()

    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente='Cliente Editado', data=dia, hora_inicio=time(10, 0),
                      duracao_min=60, status='agendado')
    db.session.add(ag)
    db.session.commit()
    ag_id = ag.id

    resp = client.post(f'/admin/agenda/{ag_id}/editar', data={
        'data': dia.isoformat(),
        'hora_inicio': '21:00',  # fora do expediente
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Editado',
        'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(ag)
    assert ag.hora_inicio == time(21, 0)


def test_bloqueio_manual_continua_valendo_no_painel_interno(client):
    """Diferente do expediente, um bloqueio manual (férias, folga etc.)
    continua impedindo o agendamento pelo painel interno — só o expediente
    deixou de restringir esse canal."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = _amanha()

    db.session.add(BloqueioAgenda(profissional_id=prof.id, data_inicio=dia, data_fim=dia,
                                   dia_inteiro=True, motivo='Férias', empresa_id=empresa.id))
    db.session.commit()

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(),
        'hora_inicio': '10:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Bloqueado',
        'servico_id': str(servico.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Bloqueado').first() is None
