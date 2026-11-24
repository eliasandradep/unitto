"""Bug relatado no tenant Renata Rosa Beauty Concept (usuária Adriene Felício,
perfil Recepção): ao abrir uma comanda de uma data anterior a hoje e tentar
registrar a forma de pagamento, a comanda "fechava sozinha". Causa raiz: o
perfil Recepção só tem acesso financeiro a comandas do dia de hoje (regra de
negócio existente, ver admin/permissions.py::PERFIL_CAPS), mas o bloqueio no
servidor fazia abort(403) com uma página HTML — o JavaScript do modal tentava
interpretar essa resposta como JSON, falhava, e no catch fechava o modal com
um toast genérico, sem explicar a regra. Agora os endpoints JSON usados pelo
modal devolvem {'ok': False, 'error': <explicação>} em vez de abortar."""
from datetime import date, time, timedelta

from models import db, User, Agendamento, Comanda, ComandaItem
from tests.conftest import make_empresa, make_booking_setup


def _login_recepcao(client, empresa):
    user = User(name='Adriene', username=f'recepcao{empresa.id}', email=f'recepcao{empresa.id}@teste.com',
                empresa_id=empresa.id, role='recepcionista')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_recepcao_abrir_comanda_de_outro_dia_retorna_erro_explicativo_em_json(client):
    empresa = make_empresa()
    servico, prof = make_booking_setup(empresa)
    ontem = date.today() - timedelta(days=1)
    ag = Agendamento(empresa_id=empresa.id, profissional_id=prof.id, servico_id=servico.id,
                      nome_cliente='Cliente Antigo', data=ontem, hora_inicio=time(10, 0),
                      duracao_min=60, status='concluido')
    db.session.add(ag)
    db.session.flush()
    c = Comanda(empresa_id=empresa.id, codigo=1, data=ontem, profissional_id=prof.id,
                agendamento_id=ag.id, status='aberta')
    c.itens.append(ComandaItem(descricao='Corte', valor=50, quantidade=1))
    db.session.add(c)
    db.session.commit()
    ag_id = ag.id
    comanda_id = c.id

    _login_recepcao(client, empresa)

    # 1) Abrir a comanda pelo modal (rota usada por abrirComandaModal)
    resp = client.post(f'/admin/api/ag/{ag_id}/comanda')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is False
    assert 'dia de hoje' in data['error']

    # 2) Tentar registrar a forma de pagamento diretamente
    resp2 = client.post(f'/admin/api/comanda/{comanda_id}/pag-add',
                         json={'forma_pagamento': 'dinheiro', 'valor': 50})
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['ok'] is False
    assert 'dia de hoje' in data2['error']

    # 3) Autosave também devolve o mesmo erro explicativo, não um 403 estourado
    resp3 = client.post(f'/admin/financeiro/comandas/{comanda_id}/autosave', data={
        'data': ontem.isoformat(), 'status': 'aberta', 'nome_cliente': '', 'observacoes': '',
        'cliente_id': '', 'unidade_id': '', 'profissional_id': str(prof.id), 'desconto': '0',
    })
    assert resp3.status_code == 200
    data3 = resp3.get_json()
    assert data3['ok'] is False
    assert 'dia de hoje' in data3['error']

    # 4) Página completa da comanda (fora do modal) continua 403, mas agora
    # com a explicação da regra no corpo, em vez da mensagem genérica.
    resp4 = client.get(f'/admin/financeiro/comandas/{comanda_id}')
    assert resp4.status_code == 403
    assert 'dia de hoje' in resp4.get_data(as_text=True)


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
