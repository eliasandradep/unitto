"""Bug relatado: no mobile, ao trocar a visão da agenda pra "Listagem", o
filtro (e qualquer jeito de voltar pra Dia/Semana) desaparecia — a Listagem é
uma página separada (/admin/agenda/listagem) sem nenhum controle de volta,
só a saída manual pelo menu lateral. Dois ajustes:

  1. A visão "grade" (1 profissional, linha do tempo por hora) é uma opção
     válida de filtro mobile, igual dia/semana/listagem (admin/routes.py —
     _ler_filtro_mobile, agenda_filtro_mobile_salvar).
  2. /admin/agenda aceita ?tipo= pra trocar e já salvar a preferência — é o
     que os links de volta na Listagem usam (ver templates/admin/
     agenda_listagem.html, .agl-view-tab) pra não deixar o usuário preso lá."""
import json
import re

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


def _filtro_inicial_do_html(body):
    m = re.search(r'const FILTRO_INICIAL = (\{.*?\});', body)
    assert m, 'FILTRO_INICIAL não encontrado no HTML'
    return json.loads(m.group(1))


def test_grade_e_um_tipo_valido_ao_salvar_filtro_mobile(client):
    empresa = make_empresa()
    user = _login_admin(client, empresa)

    resp = client.post('/admin/agenda/filtro-mobile', json={'tipo': 'grade', 'profissional_ids': []})
    assert resp.status_code == 200
    db.session.refresh(user)
    assert json.loads(user.agenda_filtro_mobile)['tipo'] == 'grade'


def test_agenda_tipo_param_troca_e_persiste_a_preferencia(client):
    empresa = make_empresa()
    user = _login_admin(client, empresa)

    resp = client.get('/admin/agenda?tipo=grade')
    assert resp.status_code == 200
    filtro = _filtro_inicial_do_html(resp.data.decode('utf-8'))
    assert filtro['tipo'] == 'grade'

    # persistiu: uma nova visita sem ?tipo= continua trazendo "grade"
    resp2 = client.get('/admin/agenda')
    filtro2 = _filtro_inicial_do_html(resp2.data.decode('utf-8'))
    assert filtro2['tipo'] == 'grade'

    db.session.refresh(user)
    assert json.loads(user.agenda_filtro_mobile)['tipo'] == 'grade'


def test_agenda_tipo_param_invalido_e_ignorado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.get('/admin/agenda?tipo=bagunca')
    assert resp.status_code == 200
    filtro = _filtro_inicial_do_html(resp.data.decode('utf-8'))
    assert filtro['tipo'] == 'dia'  # padrão, não quebrou com valor inválido


def test_listagem_tem_links_de_volta_para_dia_semana_e_grade(client):
    empresa = make_empresa()
    _login_admin(client, empresa)

    resp = client.get('/admin/agenda/listagem')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert '/admin/agenda?tipo=dia' in body
    assert '/admin/agenda?tipo=semana' in body
    assert '/admin/agenda?tipo=grade' in body


def test_agenda_html_tem_grade_mobile_e_abas_de_visao(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    db.session.add(Profissional(nome='Prof A', empresa_id=empresa.id, ativo=True))
    db.session.commit()

    resp = client.get('/admin/agenda')
    body = resp.data.decode('utf-8')
    assert 'id="agmGrade"' in body
    assert 'id="agmGradeCol"' in body
    assert 'class="agm-view-tabs"' in body
    assert 'data-tipo="grade"' in body
