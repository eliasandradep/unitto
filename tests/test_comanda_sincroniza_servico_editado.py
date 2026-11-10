"""Bug real relatado: a comanda é montada a partir dos serviços do
agendamento só uma vez, no momento em que é criada (ao clicar em "Faturar"
pela primeira vez). Se o atendimento foi agendado sem nenhum serviço (ou
com o serviço errado) e só depois, editando o agendamento, o serviço certo
foi adicionado, reabrir "Faturar" devolvia a mesma comanda já existente sem
nunca saber do serviço novo — ele nunca aparecia na comanda. Corrigido com
_sync_servicos_agendamento_comanda (admin/routes.py), chamada toda vez que
uma comanda já existente é reaberta (agenda_faturar e api_ag_comanda)."""
from datetime import date, time, timedelta

from models import db, User, Servico, Comanda, ComandaItem, Agendamento
from tests.conftest import make_empresa, make_booking_setup


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_comanda_sincroniza_servico_adicionado_apos_editar_agendamento(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = date.today() + timedelta(days=1)

    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id,
                      nome_cliente='Cliente Sem Servico', data=dia,
                      hora_inicio=time(11, 0), duracao_min=60, status='agendado')
    db.session.add(ag)
    db.session.commit()
    ag_id = ag.id

    # 1ª vez que abre "Faturar": agendamento ainda sem serviço, comanda nasce vazia.
    client.post(f'/admin/api/ag/{ag_id}/comanda')
    c = Comanda.query.filter_by(agendamento_id=ag_id).first()
    assert c is not None
    assert ComandaItem.query.filter_by(comanda_id=c.id).count() == 0

    # Edita o agendamento e agora sim adiciona o serviço.
    resp = client.post(f'/admin/agenda/{ag_id}/editar', data={
        'data': dia.isoformat(),
        'hora_inicio': '11:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Sem Servico',
        'servico_ids[]': [str(servico.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Reabre "Faturar": a comanda já existia, mas agora deve vir com o serviço.
    r2 = client.post(f'/admin/api/ag/{ag_id}/comanda')
    itens = ComandaItem.query.filter_by(comanda_id=c.id).all()
    assert len(itens) == 1
    assert itens[0].servico_id == servico.id
    assert r2.get_json()['itens'][0]['servico_id'] == servico.id


def test_sincronizacao_nao_duplica_servico_ja_presente(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    dia = date.today() + timedelta(days=1)

    resp = client.post('/admin/agenda/novo', data={
        'data': dia.isoformat(),
        'hora_inicio': '10:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Com Servico',
        'servico_ids[]': [str(servico.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    ag = Agendamento.query.filter_by(nome_cliente='Cliente Com Servico').first()

    client.post(f'/admin/api/ag/{ag.id}/comanda')
    c = Comanda.query.filter_by(agendamento_id=ag.id).first()
    assert ComandaItem.query.filter_by(comanda_id=c.id).count() == 1

    # Reabrir de novo (sem editar nada) não deve duplicar o item.
    client.post(f'/admin/api/ag/{ag.id}/comanda')
    assert ComandaItem.query.filter_by(comanda_id=c.id).count() == 1


def test_sincronizacao_nao_mexe_em_comanda_ja_fechada(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    servico2 = Servico(nome='Hidratação', preco=50, empresa_id=empresa.id, ativo=True)
    db.session.add(servico2)
    db.session.commit()
    dia = date.today() + timedelta(days=1)

    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id,
                      nome_cliente='Cliente Fechado', data=dia,
                      hora_inicio=time(9, 0), duracao_min=60, status='agendado')
    db.session.add(ag)
    ag.servicos_lista = [servico]
    db.session.commit()
    ag_id = ag.id

    client.post(f'/admin/api/ag/{ag_id}/comanda')
    c = Comanda.query.filter_by(agendamento_id=ag_id).first()
    c.status = 'fechada'
    db.session.commit()

    # Edita o agendamento acrescentando um 2º serviço depois de a comanda já
    # estar fechada (faturada) — não deve ser reaberta nem alterada.
    client.post(f'/admin/agenda/{ag_id}/editar', data={
        'data': dia.isoformat(),
        'hora_inicio': '09:00',
        'profissional_id': str(prof.id),
        'nome_cliente': 'Cliente Fechado',
        'servico_ids[]': [str(servico.id), str(servico2.id)],
    }, follow_redirects=True)

    client.post(f'/admin/api/ag/{ag_id}/comanda')
    db.session.refresh(c)
    assert c.status == 'fechada'
    assert ComandaItem.query.filter_by(comanda_id=c.id).count() == 1
