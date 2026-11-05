"""Criação de Bloqueio de Agenda aceita múltiplas janelas de horário num só
envio (ex: almoço das 12:30 às 13:30 e pausa das 16:00 às 16:30), gerando um
BloqueioAgenda por janela — todos com o mesmo profissional/período/motivo.
A conflito-checagem (_find_bloqueio_conflict) já trata data_inicio/data_fim
como recorrência diária do horário, então cada linha criada passa a bloquear
aquele horário em TODOS os dias do período, sem precisar de mudança naquela
função."""
from datetime import date, time, timedelta

from models import db, User, Profissional, BloqueioAgenda
from admin.routes import _find_bloqueio_conflict
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_criar_bloqueio_com_duas_janelas_de_horario_gera_duas_linhas(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional X', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    prof_id = prof.id

    hoje = date.today()
    fim = hoje + timedelta(days=30)
    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof_id),
        'data_inicio': hoje.isoformat(),
        'data_fim': fim.isoformat(),
        'motivo': 'Almoço e pausa da tarde',
        'hora_inicio[]': ['12:30', '16:00'],
        'hora_fim[]': ['13:30', '16:30'],
    }, follow_redirects=True)
    assert resp.status_code == 200

    bloqueios = BloqueioAgenda.query.filter_by(profissional_id=prof_id).order_by(BloqueioAgenda.hora_inicio).all()
    assert len(bloqueios) == 2
    assert bloqueios[0].hora_inicio == time(12, 30) and bloqueios[0].hora_fim == time(13, 30)
    assert bloqueios[1].hora_inicio == time(16, 0) and bloqueios[1].hora_fim == time(16, 30)
    for b in bloqueios:
        assert b.data_inicio == hoje
        assert b.data_fim == fim
        assert b.motivo == 'Almoço e pausa da tarde'
        assert b.dia_inteiro is False


def test_bloqueio_recorrente_conflita_em_qualquer_dia_do_periodo(client):
    """Cada janela de horário criada bloqueia o mesmo horário em TODOS os dias
    do período — não só no dia de início."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional Y', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    prof_id = prof.id

    hoje = date.today()
    fim = hoje + timedelta(days=30)
    client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof_id),
        'data_inicio': hoje.isoformat(),
        'data_fim': fim.isoformat(),
        'motivo': 'Almoço',
        'hora_inicio[]': ['12:30'],
        'hora_fim[]': ['13:30'],
    })

    dia_no_meio_do_periodo = hoje + timedelta(days=15)
    conflito = _find_bloqueio_conflict(prof_id, dia_no_meio_do_periodo, time(13, 0), 30)
    assert conflito is not None

    sem_conflito = _find_bloqueio_conflict(prof_id, dia_no_meio_do_periodo, time(14, 0), 30)
    assert sem_conflito is None


def test_criar_bloqueio_sem_nenhuma_janela_de_horario_e_rejeitado(client):
    """profissional_id vazio bloquearia TODOS os profissionais — usamos um
    profissional dedicado aqui pra não vazar um bloqueio global (que poderia
    afetar outros testes da sessão) mesmo que a criação falhe."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional Z', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    hoje = date.today()

    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof.id),
        'data_inicio': hoje.isoformat(),
        'data_fim': hoje.isoformat(),
        'hora_inicio[]': [''],
        'hora_fim[]': [''],
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert BloqueioAgenda.query.filter_by(empresa_id=empresa.id).count() == 0


def test_dia_inteiro_ignora_janelas_de_horario(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional W', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    hoje = date.today()

    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof.id),
        'data_inicio': hoje.isoformat(),
        'data_fim': hoje.isoformat(),
        'dia_inteiro': 'on',
        'motivo': 'Feriado',
    }, follow_redirects=True)
    assert resp.status_code == 200
    bloqueios = BloqueioAgenda.query.filter_by(empresa_id=empresa.id).all()
    assert len(bloqueios) == 1
    assert bloqueios[0].dia_inteiro is True
    assert bloqueios[0].hora_inicio is None


def test_bloqueio_diario_nao_exige_datas_e_vale_indefinidamente(client):
    """Toggle 'recorrente_diario' dispensa data_inicio/data_fim do usuário —
    o bloqueio recebe um horizonte bem distante (hoje + 10 anos) como
    'sem término', e vale a partir de hoje em qualquer dia futuro."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional Diário', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    prof_id = prof.id

    resp = client.post('/admin/agenda/bloqueios', data={
        'profissional_id': str(prof_id),
        'recorrente_diario': 'on',
        'motivo': 'Almoço',
        'hora_inicio[]': ['12:30'],
        'hora_fim[]': ['13:30'],
    }, follow_redirects=True)
    assert resp.status_code == 200

    bloqueios = BloqueioAgenda.query.filter_by(profissional_id=prof_id).all()
    assert len(bloqueios) == 1
    b = bloqueios[0]
    assert b.recorrente_diario is True
    assert b.data_inicio == date.today()
    assert b.data_fim >= date.today() + timedelta(days=365 * 5)

    um_ano_no_futuro = date.today() + timedelta(days=365)
    conflito = _find_bloqueio_conflict(prof_id, um_ano_no_futuro, time(13, 0), 30)
    assert conflito is not None


def test_editar_bloqueio_continua_aceitando_uma_unica_janela(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Profissional V', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    b = BloqueioAgenda(data_inicio=date.today(), data_fim=date.today(),
                        hora_inicio=time(9, 0), hora_fim=time(10, 0),
                        profissional_id=prof.id, motivo='Original', empresa_id=empresa.id)
    db.session.add(b)
    db.session.commit()
    bl_id = b.id

    resp = client.post(f'/admin/agenda/bloqueios/{bl_id}/editar', data={
        'profissional_id': str(prof.id),
        'data_inicio': date.today().isoformat(),
        'data_fim': date.today().isoformat(),
        'motivo': 'Editado',
        'hora_inicio[]': ['11:00'],
        'hora_fim[]': ['12:00'],
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(b)
    assert b.motivo == 'Editado'
    assert b.hora_inicio == time(11, 0)
    assert b.hora_fim == time(12, 0)
