"""Bug relatado: na tela do Lead, clicar numa opção diferente nos cartões
"Status" e "Status comercial" parecia não fazer nada — o <input type="radio">
fica escondido (CSS: .status-option input[type=radio] { display: none }) e a
classe .selected só era aplicada pelo servidor na renderização, então nada
mudava na tela até a página recarregar depois de salvar. O salvamento em si
já funcionava (ver abaixo); faltava só o feedback visual imediato do clique,
adicionado em templates/admin/lead_detail.html via JS."""
import uuid

from models import db, User, Lead, RenataRosaFunilLead
from tests.conftest import make_empresa


def _login(client, empresa):
    sufixo = uuid.uuid4().hex[:8]
    user = User(name='Admin', username=f'admin{empresa.id}{sufixo}', email=f'admin{empresa.id}{sufixo}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_update_status_generico_persiste(client):
    empresa = make_empresa()
    _login(client, empresa)
    lead = Lead(empresa_id=empresa.id, name='Fulana', phone='5511988887777',
                source='whatsapp_meta', status='novo')
    db.session.add(lead)
    db.session.commit()

    resp = client.post(f'/admin/leads/{lead.id}', data={
        'action': 'update_status', 'status': 'qualificado',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(lead)
    assert lead.status == 'qualificado'


def test_pagina_lead_tem_script_de_feedback_visual_do_status(client):
    empresa = make_empresa()
    _login(client, empresa)
    lead = Lead(empresa_id=empresa.id, name='Fulana', phone='5511988887777', source='whatsapp_meta')
    db.session.add(lead)
    db.session.commit()

    resp = client.get(f'/admin/leads/{lead.id}')
    body = resp.data.decode('utf-8')
    assert "querySelectorAll('.status-buttons')" in body
    assert "classList.toggle('selected'" in body
