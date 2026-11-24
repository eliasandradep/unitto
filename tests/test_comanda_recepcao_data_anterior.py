"""Bug relatado no tenant Renata Rosa Beauty Concept (usuária Adriene Felício,
perfil Recepção): ao tentar fechar uma comanda de uma data anterior a hoje, a
comanda "fechava sozinha" sem explicação. A causa era a regra de negócio de
então — perfil Recepção só tinha acesso financeiro ao dia de hoje — combinada
com um bug real de UX: o bloqueio devolvia uma página HTML (abort 403) e o
JavaScript do modal, ao tentar interpretar essa resposta como JSON, falhava e
fechava o modal silenciosamente.

Depois, a pedido do usuário, a própria regra de negócio mudou: perfil
Recepção passou a ter acesso financeiro total (qualquer comanda, qualquer
data — ver admin/permissions.py::PERFIL_CAPS). Este arquivo cobre essa regra
atual. O mecanismo de mensagem explicativa (em vez de um 403/JSON quebrado
quando o acesso É negado) continua coberto abaixo para o perfil Profissional,
que ainda tem escopo restrito ('own')."""
from datetime import date, time, timedelta

from models import db, User, Profissional, Agendamento, Comanda
from tests.conftest import make_empresa, make_booking_setup


def _login_recepcao(client, empresa):
    user = User(name='Adriene', username=f'recepcao{empresa.id}', email=f'recepcao{empresa.id}@teste.com',
                empresa_id=empresa.id, role='recepcionista')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_recepcao_abre_e_fecha_comanda_de_data_anterior(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    ontem = date.today() - timedelta(days=1)
    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente='Cliente Antigo', data=ontem, hora_inicio=time(10, 0),
                      duracao_min=60, status='concluido')
    db.session.add(ag)
    db.session.commit()
    ag_id = ag.id

    _login_recepcao(client, empresa)

    # 1) Abrir a comanda pelo modal (rota usada por abrirComandaModal) —
    # cria a comanda e já sincroniza o serviço do agendamento (preço 100).
    resp = client.post(f'/admin/api/ag/{ag_id}/comanda')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('ok') is not False
    comanda_id = data['id']
    assert data['saldo'] == 100

    # 2) Registrar a forma de pagamento, cobrindo o valor total
    resp2 = client.post(f'/admin/api/comanda/{comanda_id}/pag-add',
                         json={'forma_pagamento': 'dinheiro', 'valor': 100})
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['ok'] is True

    # 3) Página completa da comanda também acessível, sem 403
    resp3 = client.get(f'/admin/financeiro/comandas/{comanda_id}')
    assert resp3.status_code == 200

    # 4) Fechar a comanda de fato
    resp4 = client.post(f'/admin/financeiro/comandas/{comanda_id}/fechar', follow_redirects=True)
    assert resp4.status_code == 200
    c = db.session.get(Comanda, comanda_id)
    assert c.status == 'fechada'


def test_recepcao_abrir_comanda_do_dia_de_hoje_funciona_normalmente(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    hoje = date.today()
    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente='Cliente Hoje', data=hoje, hora_inicio=time(14, 0),
                      duracao_min=60, status='concluido')
    db.session.add(ag)
    db.session.commit()
    ag_id = ag.id

    _login_recepcao(client, empresa)

    resp = client.post(f'/admin/api/ag/{ag_id}/comanda')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('ok') is not False
    assert 'id' in data


def _login_profissional(client, empresa, nome='Prof A'):
    prof = Profissional(nome=nome, empresa_id=empresa.id, ativo=True, perfil_acesso='profissional')
    db.session.add(prof)
    db.session.flush()
    user = User(name=nome, username=f'{nome.lower().replace(" ", "")}{empresa.id}',
                email=f'{nome.lower().replace(" ", "")}{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user, prof


def test_mensagem_explicativa_em_json_quando_profissional_acessa_comanda_de_outra(client):
    """O mecanismo de erro explicativo (em vez de 403 HTML quebrando o JSON do
    modal) continua valendo pra quem ainda tem escopo restrito — aqui, o
    perfil Profissional tentando abrir a comanda de outra profissional."""
    empresa = make_empresa()
    servico, prof_a = make_booking_setup(empresa)
    _, prof_b = _login_profissional(client, empresa, nome='Prof B')
    client.get('/admin/logout')

    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof_a.id, servico_id=servico.id,
                      nome_cliente='Cliente X', data=date.today(), hora_inicio=time(9, 0),
                      duracao_min=60, status='concluido')
    db.session.add(ag)
    db.session.flush()
    c = Comanda(empresa_id=empresa.id, codigo=1, data=date.today(), profissional_id=prof_a.id,
                agendamento_id=ag.id, status='aberta')
    db.session.add(c)
    db.session.commit()
    ag_id, comanda_id = ag.id, c.id

    client.post('/admin/login', data={'email': f'profb{empresa.id}@teste.com', 'password': 'senha123'},
                follow_redirects=True)

    resp = client.post(f'/admin/api/ag/{ag_id}/comanda')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is False
    assert 'próprias comandas' in data['error']

    resp2 = client.post(f'/admin/api/comanda/{comanda_id}/pag-add',
                         json={'forma_pagamento': 'dinheiro', 'valor': 50})
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['ok'] is False
    assert 'próprias comandas' in data2['error']
