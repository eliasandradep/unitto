"""Bug relatado: profissional com perfil 'Profissional' tentava editar/
fechar a própria comanda e a tela fechava sozinha. Causa real: o campo
"Responsável" no modal de comanda da agenda é só leitura (não existe select
pra trocar quem é o profissional da comanda ali) — mas `_buildCmdFormData()`
em templates/admin/agenda.html mandava sempre `profissional_id=''` pro
autosave, em vez do valor atual. Pra quem tem escopo financeiro 'own'
(perfil Profissional), `_save_comanda` reforça profissional_id pro próprio
usuário depois (mascarando o bug); mas quando ADMINISTRADOR ou RECEPÇÃO
(escopo 'full') salvavam/pagavam a mesma comanda pelo modal, o campo era
zerado de verdade no banco. Na próxima vez que a profissional responsável
tentava abrir/fechar essa comanda, `financeiro_pode_acessar` (escopo 'own')
via c.profissional_id = None != seu id e bloqueava — exatamente como "a
tela fecha sozinha", só que a comanda era mesmo dela; o campo é que tinha
sido apagado por outra pessoa salvando antes. Corrigido guardando
profissional_id/unidade_id em variáveis JS (_cmdProfissionalId/_cmdUnidadeId,
preenchidas em _carregarCmdUI) e reenviando-os no autosave, igual já se
fazia com _cmdClienteId."""
from datetime import date

from models import db, User, Profissional, Comanda, ComandaItem, Cliente
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)


def _login_profissional(client, prof):
    user = User.query.filter_by(profissional_id=prof.id).first()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)


def _criar_profissional_e_comanda(empresa):
    prof = Profissional(nome='Prof A', empresa_id=empresa.id, ativo=True, perfil_acesso='profissional')
    db.session.add(prof)
    db.session.flush()
    user = User(name='Prof A', username=f'profa{empresa.id}', email=f'profa{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    cliente = Cliente(nome='Cliente X', telefone='11988887777', empresa_id=empresa.id)
    db.session.add(cliente)
    db.session.flush()
    c = Comanda(codigo=1, empresa_id=empresa.id, data=date.today(),
                profissional_id=prof.id, cliente_id=cliente.id, status='aberta')
    c.itens.append(ComandaItem(descricao='Corte', valor=50, quantidade=1))
    db.session.add(c)
    db.session.commit()
    return prof, c.id, cliente.id


def _form_modal(comanda_id, profissional_id, cliente_id=None):
    """Simula exatamente o FormData que _buildCmdFormData() monta no modal
    da agenda (templates/admin/agenda.html), já com o fix: profissional_id/
    cliente_id/unidade_id vêm dos valores atuais (_cmdProfissionalId/
    _cmdClienteId/_cmdUnidadeId), nunca mais de uma string vazia fixa."""
    return {
        'data': date.today().isoformat(), 'nome_cliente': '', 'observacoes': '',
        'status': 'aberta', 'desconto': '0',
        'profissional_id': str(profissional_id) if profissional_id else '',
        'cliente_id': str(cliente_id) if cliente_id else '', 'unidade_id': '',
        'item_descricao': ['Corte'], 'item_valor': ['50'], 'item_quantidade': ['1'],
        'item_servico_id': [''], 'item_produto_id': [''], 'item_venda_pacote_item_id': [''],
        'item_profissional_id': [''], 'item_comissao_valor': [''], 'item_comissao_tipo': ['%'],
    }


def test_admin_salva_comanda_pelo_modal_sem_apagar_o_responsavel(client):
    empresa = make_empresa()
    prof, c_id, cliente_id = _criar_profissional_e_comanda(empresa)

    _login_admin(client, empresa)
    resp = client.post(f'/admin/financeiro/comandas/{c_id}/autosave',
                        data=_form_modal(c_id, prof.id, cliente_id))
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    c = db.session.get(Comanda, c_id)
    assert c.profissional_id == prof.id  # não foi zerado

    # a profissional responsável continua conseguindo abrir/editar/fechar a
    # própria comanda depois do admin ter salvo
    client.get('/admin/logout')
    _login_profissional(client, prof)
    resp2 = client.get(f'/admin/financeiro/comandas/{c_id}')
    assert resp2.status_code == 200
    resp3 = client.post(f'/admin/financeiro/comandas/{c_id}/fechar', follow_redirects=True)
    assert resp3.status_code == 200
    c = db.session.get(Comanda, c_id)
    assert c.status == 'fechada'


def test_api_pag_add_do_modal_sem_apagar_o_responsavel(client):
    """Registrar pagamento no modal chama _salvarCmdItens() (autosave) antes
    de dar POST em /api/comanda/<id>/pag-add — mesmo caminho, mesmo risco."""
    empresa = make_empresa()
    prof, c_id, cliente_id = _criar_profissional_e_comanda(empresa)

    _login_admin(client, empresa)
    client.post(f'/admin/financeiro/comandas/{c_id}/autosave', data=_form_modal(c_id, prof.id, cliente_id))
    resp = client.post(f'/admin/api/comanda/{c_id}/pag-add', json={
        'forma_pagamento': 'dinheiro', 'valor': 50,
    })
    assert resp.get_json()['ok'] is True

    c = db.session.get(Comanda, c_id)
    assert c.profissional_id == prof.id
    assert len(c.pagamentos) == 1  # o pagamento registrou normalmente

    client.get('/admin/logout')
    _login_profissional(client, prof)
    resp2 = client.get(f'/admin/financeiro/comandas/{c_id}')
    assert resp2.status_code == 200


def test_agenda_html_guarda_profissional_id_e_unidade_id_do_modal(client):
    """Trava o bug de voltar: o JS precisa reenviar o profissional_id/
    unidade_id atuais no autosave, nunca string vazia fixa — o campo
    "Responsável" do modal é readonly, não há de onde outro valor viria."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    resp = client.get('/admin/agenda')
    body = resp.data.decode('utf-8')
    assert "fd.append('profissional_id', _cmdProfissionalId || '')" in body
    assert "fd.append('unidade_id', _cmdUnidadeId || '')" in body
    assert "_cmdProfissionalId = data.profissional_id || null;" in body
