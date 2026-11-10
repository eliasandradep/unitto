"""Bug real relatado: a atendente adicionava serviços na tela da comanda (que
só ficam no formulário até "Salvar comanda" ser enviado) e clicava direto em
"Fechar comanda" — um <form> à parte, sem os campos de item. O fechamento
comitava a comanda exatamente como estava salva no banco, então os itens
nunca entravam e a comanda fechava com total R$ 0,00 e nenhum pagamento.
Corrigido em templates/admin/comanda_form.html fazendo o botão "Fechar
comanda" chamar /autosave (mesmo padrão já usado por "Registrar pagamento")
antes de enviar o fechamento. Estes testes travam o contrato dos dois
endpoints que a correção depende: autosave precisa persistir os itens e
fechar não pode apagá-los nem precisar de pagamento para fechar."""
from datetime import date

from models import db, User, Comanda, ComandaItem, ContaReceber
from tests.conftest import make_empresa, make_booking_setup


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _form_base(hoje):
    return {
        'data': hoje.isoformat(),
        'status': 'aberta',
        'nome_cliente': 'Cliente Teste',
        'observacoes': '',
        'cliente_id': '',
        'unidade_id': '',
        'profissional_id': '',
        'desconto': '0',
    }


def test_fechar_direto_sem_autosave_nao_resgata_itens_da_tela(client):
    """Reproduz o bug: chamar /fechar sem antes salvar os itens via /autosave
    fecha a comanda exatamente como está no banco — vazia."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    hoje = date.today()

    resp = client.post('/admin/financeiro/comandas/nova', data=_form_base(hoje), follow_redirects=True)
    assert resp.status_code == 200
    c = Comanda.query.filter_by(empresa_id=empresa.id).first()
    assert c is not None
    assert c.valor_total == 0

    # A atendente "adicionou" o serviço só na tela (nunca enviado ao servidor)
    # e foi direto em "Fechar comanda".
    client.post(f'/admin/financeiro/comandas/{c.id}/fechar')
    db.session.refresh(c)
    assert c.status == 'fechada'
    assert c.valor_total == 0
    assert ComandaItem.query.filter_by(comanda_id=c.id).count() == 0
    # Sem valor nenhum, nada a receber é gerado — o faturamento do serviço se perde.
    assert ContaReceber.query.filter_by(comanda_id=c.id).count() == 0


def test_autosave_antes_de_fechar_preserva_itens_e_gera_conta_a_receber(client):
    """Fluxo corrigido: o botão "Fechar comanda" dispara /autosave com os
    itens da tela antes de enviar o fechamento."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    servico, prof = make_booking_setup(empresa)
    hoje = date.today()

    resp = client.post('/admin/financeiro/comandas/nova', data=_form_base(hoje), follow_redirects=True)
    c = Comanda.query.filter_by(empresa_id=empresa.id).first()

    form = _form_base(hoje)
    form.update({
        'item_descricao': [servico.nome],
        'item_valor': ['100,00'],
        'item_quantidade': ['1'],
        'item_servico_id': [str(servico.id)],
        'item_produto_id': [''],
        'item_venda_pacote_item_id': [''],
        'item_profissional_id': [str(prof.id)],
        'item_comissao_valor': [''],
        'item_comissao_tipo': ['%'],
    })
    r_autosave = client.post(f'/admin/financeiro/comandas/{c.id}/autosave', data=form)
    assert r_autosave.get_json()['ok'] is True

    db.session.refresh(c)
    assert c.valor_total == 100

    client.post(f'/admin/financeiro/comandas/{c.id}/fechar')
    db.session.refresh(c)
    assert c.status == 'fechada'
    assert ComandaItem.query.filter_by(comanda_id=c.id).count() == 1
    assert c.valor_total == 100
    cr = ContaReceber.query.filter_by(comanda_id=c.id).first()
    assert cr is not None
    assert cr.valor == 100
