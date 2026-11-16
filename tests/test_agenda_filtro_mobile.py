"""Agenda no mobile: visão de 1 profissional por vez (dia ou semana), com
filtro (tipo de agenda + profissionais) salvo por usuário e reaplicado
automaticamente no próximo acesso. Cobre as duas peças de backend que
sustentam essa visão:

  - GET /admin/agenda/dados aceita um intervalo (data + data_fim opcional)
    pra trazer a semana inteira numa só chamada, com 'data' em cada evento
    (a visão semanal mistura eventos de dias diferentes) e 'data_inicio'/
    'data_fim' em cada bloqueio.
  - POST /admin/agenda/filtro-mobile salva o filtro em
    User.agenda_filtro_mobile (JSON), validando tipo e profissional_ids;
    GET /admin/agenda devolve esse filtro salvo como 'filtro_mobile' pro
    template (renderizado em FILTRO_INICIAL, no JS).

Ver admin/routes.py (agenda, agenda_dados, agenda_filtro_mobile_salvar,
_ler_filtro_mobile)."""
import json
import re
from datetime import date, timedelta, time

from models import db, User, Profissional, Agendamento, BloqueioAgenda, Servico
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _criar_profissional(empresa, nome):
    prof = Profissional(nome=nome, empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()
    return prof


def _criar_agendamento(empresa, prof, dia, hora='10:00'):
    h, m = map(int, hora.split(':'))
    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, data=dia,
                      hora_inicio=time(h, m), duracao_min=60, nome_cliente='Cliente Teste',
                      status='agendado')
    db.session.add(ag)
    db.session.commit()
    return ag


def _filtro_inicial_do_html(body):
    m = re.search(r'const FILTRO_INICIAL = (\{.*?\});', body)
    assert m, 'FILTRO_INICIAL não encontrado no HTML'
    return json.loads(m.group(1))


def test_agenda_dados_sem_data_fim_mantem_comportamento_de_um_dia_so(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = _criar_profissional(empresa, 'Prof A')
    hoje = date.today()
    _criar_agendamento(empresa, prof, hoje)
    _criar_agendamento(empresa, prof, hoje + timedelta(days=1))

    resp = client.get(f'/admin/agenda/dados?data={hoje.isoformat()}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['events']) == 1
    assert data['events'][0]['data'] == hoje.isoformat()


def test_agenda_dados_com_data_fim_traz_a_semana_inteira(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = _criar_profissional(empresa, 'Prof A')
    hoje = date.today()
    fim = hoje + timedelta(days=6)
    _criar_agendamento(empresa, prof, hoje, '09:00')
    _criar_agendamento(empresa, prof, hoje + timedelta(days=3), '11:00')
    _criar_agendamento(empresa, prof, fim, '14:00')
    _criar_agendamento(empresa, prof, fim + timedelta(days=1), '15:00')  # fora do intervalo

    resp = client.get(f'/admin/agenda/dados?data={hoje.isoformat()}&data_fim={fim.isoformat()}')
    assert resp.status_code == 200
    data = resp.get_json()
    datas_retornadas = sorted(e['data'] for e in data['events'])
    assert datas_retornadas == [hoje.isoformat(), (hoje + timedelta(days=3)).isoformat(), fim.isoformat()]


def test_agenda_dados_bloqueio_traz_data_inicio_e_data_fim(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = _criar_profissional(empresa, 'Prof A')
    hoje = date.today()
    bloqueio = BloqueioAgenda(empresa_id=empresa.id, profissional_id=prof.id,
                               data_inicio=hoje, data_fim=hoje + timedelta(days=10), dia_inteiro=True)
    db.session.add(bloqueio)
    db.session.commit()

    resp = client.get(f'/admin/agenda/dados?data={hoje.isoformat()}&data_fim={(hoje + timedelta(days=6)).isoformat()}')
    assert resp.status_code == 200
    bls = resp.get_json()['bloqueios']
    assert len(bls) == 1
    assert bls[0]['data_inicio'] == hoje.isoformat()
    assert bls[0]['data_fim'] == (hoje + timedelta(days=10)).isoformat()


def test_filtro_mobile_default_antes_de_qualquer_preferencia_salva(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    _criar_profissional(empresa, 'Prof A')

    resp = client.get('/admin/agenda')
    assert resp.status_code == 200
    filtro = _filtro_inicial_do_html(resp.data.decode('utf-8'))
    assert filtro == {'tipo': 'dia', 'profissional_ids': []}


def test_salvar_filtro_mobile_e_reabrir_agenda_traz_a_preferencia_salva(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof_a = _criar_profissional(empresa, 'Prof A')
    prof_b = _criar_profissional(empresa, 'Prof B')

    resp = client.post('/admin/agenda/filtro-mobile', json={
        'tipo': 'semana', 'profissional_ids': [prof_a.id, prof_b.id],
    })
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True}

    resp = client.get('/admin/agenda')
    filtro = _filtro_inicial_do_html(resp.data.decode('utf-8'))
    assert filtro['tipo'] == 'semana'
    assert sorted(filtro['profissional_ids']) == sorted([prof_a.id, prof_b.id])


def test_salvar_filtro_mobile_com_tipo_invalido_cai_no_padrao(client):
    empresa = make_empresa()
    user = _login_admin(client, empresa)

    resp = client.post('/admin/agenda/filtro-mobile', json={'tipo': 'bagunça', 'profissional_ids': []})
    assert resp.status_code == 200
    db.session.refresh(user)
    salvo = json.loads(user.agenda_filtro_mobile)
    assert salvo['tipo'] == 'dia'


def test_salvar_filtro_mobile_ignora_profissional_de_outra_empresa(client):
    empresa = make_empresa()
    outra_empresa = make_empresa(nome='Outra Empresa')
    user = _login_admin(client, empresa)
    prof_proprio = _criar_profissional(empresa, 'Prof Próprio')
    prof_alheio  = _criar_profissional(outra_empresa, 'Prof Alheio')

    resp = client.post('/admin/agenda/filtro-mobile', json={
        'tipo': 'dia', 'profissional_ids': [prof_proprio.id, prof_alheio.id],
    })
    assert resp.status_code == 200
    db.session.refresh(user)
    salvo = json.loads(user.agenda_filtro_mobile)
    assert salvo['profissional_ids'] == [prof_proprio.id]


def test_agenda_html_traz_lista_de_profissionais_pro_js_mobile(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = _criar_profissional(empresa, 'Prof A')

    resp = client.get('/admin/agenda')
    body = resp.data.decode('utf-8')
    m = re.search(r'const PROFS = (\[.*?\]);', body)
    assert m, 'PROFS não encontrado no HTML'
    profs = json.loads(m.group(1))
    assert len(profs) == 1
    assert profs[0]['id'] == prof.id
    assert profs[0]['nome'] == 'Prof A'
    assert 'cor' in profs[0] and 'iniciais' in profs[0]
