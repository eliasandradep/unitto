"""Bug relatado: a atendente conseguia marcar um agendamento sem nenhum
serviço vinculado porque selecionava o serviço na lista mas esquecia de
clicar em "+ Adicionar Serviço" — o dropdown não tem `name`, então nada ia
no POST. Agora /admin/agenda/novo e /editar exigem ao menos um serviço."""
from datetime import date, time, timedelta

from models import db, User, Agendamento
from tests.conftest import make_empresa, make_booking_setup


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_agenda_novo_rejeita_sem_servico(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = (date.today() + timedelta(days=1)).isoformat()

    resp = client.post('/admin/agenda/novo', data={
        'data': dia,
        'hora_inicio': '10:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Sem Servico',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Agendamento.query.filter_by(nome_cliente='Cliente Sem Servico').first() is None
    assert 'Selecione ao menos um servi' in resp.get_data(as_text=True)


def test_agenda_editar_rejeita_remover_todos_os_servicos(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = date.today() + timedelta(days=1)

    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente='Cliente X', data=dia, hora_inicio=time(10, 0),
                      duracao_min=60, status='agendado')
    ag.servicos_lista = [servico]
    db.session.add(ag)
    db.session.commit()
    ag_id = ag.id

    resp = client.post(f'/admin/agenda/{ag_id}/editar', data={
        'data': dia.isoformat(),
        'hora_inicio': '10:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente X',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(ag)
    assert len(ag.servicos_lista) == 1  # não apagou o serviço que já existia


def test_agenda_novo_aceita_com_servico(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = (date.today() + timedelta(days=1)).isoformat()

    resp = client.post('/admin/agenda/novo', data={
        'data': dia,
        'hora_inicio': '10:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Com Servico',
        'servico_ids[]': [str(servico.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    ag = Agendamento.query.filter_by(nome_cliente='Cliente Com Servico').first()
    assert ag is not None
    assert len(ag.servicos_lista) == 1
