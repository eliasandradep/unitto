"""O cartão "Status comercial" na tela de Lead (funil Renata Rosa) nunca
destacava a opção atual — a classe `status-option-rr--<key>` que ativa a
cor (ver static/css/admin.css) estava faltando no template, diferente do
cartão "Status" logo acima, que já tinha o equivalente. Sem isso, parecia
que o botão "Atualizar status comercial" não fazia nada, antes ou depois
de salvar — bug real reportado pelo usuário."""
import uuid

from models import db, User, Lead, RenataRosaFunilLead
from tests.conftest import make_empresa


def _login(client, empresa):
    # slug='renatarosa' reaproveita a MESMA empresa (id fixo) em toda a
    # sessão de testes (ver tests/conftest.py::make_empresa) — sufixo
    # próprio por chamada evita UNIQUE constraint ao logar duas vezes.
    sufixo = uuid.uuid4().hex[:8]
    user = User(name='Admin', username=f'admin{empresa.id}{sufixo}', email=f'admin{empresa.id}{sufixo}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def test_status_comercial_atual_aparece_destacado_na_tela(client):
    empresa = make_empresa(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                            funil_qualificacao_rr_ativo=True)
    _login(client, empresa)
    lead = Lead(empresa_id=empresa.id, name='Fulana', phone='5511988887777', source='whatsapp_meta')
    db.session.add(lead)
    db.session.flush()
    estado = RenataRosaFunilLead(lead_id=lead.id, empresa_id=empresa.id, status_comercial='em_qualificacao')
    db.session.add(estado)
    db.session.commit()

    resp = client.get(f'/admin/leads/{lead.id}')
    html = resp.get_data(as_text=True)
    assert 'status-option-rr--em_qualificacao selected' in html


def test_atualizar_status_comercial_muda_o_destaque_apos_salvar(client):
    empresa = make_empresa(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                            funil_qualificacao_rr_ativo=True)
    _login(client, empresa)
    lead = Lead(empresa_id=empresa.id, name='Fulana', phone='5511988887777', source='whatsapp_meta')
    db.session.add(lead)
    db.session.flush()
    estado = RenataRosaFunilLead(lead_id=lead.id, empresa_id=empresa.id, status_comercial='novo_lead')
    db.session.add(estado)
    db.session.commit()

    resp = client.post(f'/admin/leads/{lead.id}', data={
        'action': 'update_status_comercial', 'status_comercial': 'agendamento_confirmado',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(estado)
    assert estado.status_comercial == 'agendamento_confirmado'
    html = resp.get_data(as_text=True)
    assert 'status-option-rr--agendamento_confirmado selected' in html
