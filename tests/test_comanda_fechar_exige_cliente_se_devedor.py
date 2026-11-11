"""Uma comanda fechada com saldo devedor só rastreia a dívida de forma
confiável quando está vinculada a um cliente cadastrado (o valor vira
"saldo devedor" no cadastro do cliente). Sem esse vínculo, a dívida ficava
solta — registrada só em Contas a Receber, sem dono — dificultando cobrar
depois. Agora o fechamento (pelo botão dedicado ou pelo campo "Status" do
formulário) é bloqueado nesse caso, pedindo para vincular um cliente antes."""
from datetime import date

from models import db, User, Cliente, Comanda
from tests.conftest import make_empresa


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _form_base(hoje, status='aberta', cliente_id=''):
    return {
        'data': hoje.isoformat(),
        'status': status,
        'nome_cliente': 'Cliente Avulso',
        'observacoes': '',
        'cliente_id': cliente_id,
        'unidade_id': '',
        'profissional_id': '',
        'desconto': '0',
        'item_descricao': ['Corte'],
        'item_valor': ['80,00'],
        'item_quantidade': ['1'],
        'item_servico_id': [''],
        'item_produto_id': [''],
        'item_venda_pacote_item_id': [''],
        'item_profissional_id': [''],
        'item_comissao_valor': [''],
        'item_comissao_tipo': ['%'],
    }


def test_botao_fechar_bloqueia_saldo_devedor_sem_cliente_vinculado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()

    client.post('/admin/financeiro/comandas/nova', data=_form_base(hoje), follow_redirects=True)
    c = Comanda.query.filter_by(empresa_id=empresa.id).first()
    assert c.saldo == 80
    assert c.cliente_id is None

    resp = client.post(f'/admin/financeiro/comandas/{c.id}/fechar', follow_redirects=True)
    assert 'não está vinculada a nenhum cliente'.encode('utf-8') in resp.data
    db.session.refresh(c)
    assert c.status == 'aberta'


def test_botao_fechar_permite_saldo_devedor_com_cliente_vinculado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()
    cliente = Cliente(nome='Maria', telefone='11999990000', empresa_id=empresa.id, saldo=0)
    db.session.add(cliente)
    db.session.commit()

    client.post('/admin/financeiro/comandas/nova', data=_form_base(hoje, cliente_id=str(cliente.id)),
                follow_redirects=True)
    c = Comanda.query.filter_by(empresa_id=empresa.id).first()
    assert c.cliente_id == cliente.id

    client.post(f'/admin/financeiro/comandas/{c.id}/fechar')
    db.session.refresh(c)
    assert c.status == 'fechada'
    db.session.refresh(cliente)
    assert cliente.saldo == -80  # dívida registrada no cadastro do cliente


def test_salvar_com_status_fechada_no_formulario_tambem_bloqueia_sem_cliente(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    hoje = date.today()

    client.post('/admin/financeiro/comandas/nova', data=_form_base(hoje), follow_redirects=True)
    c = Comanda.query.filter_by(empresa_id=empresa.id).first()

    resp = client.post(f'/admin/financeiro/comandas/{c.id}', data=_form_base(hoje, status='fechada'),
                        follow_redirects=True)
    assert 'não está vinculada a nenhum cliente'.encode('utf-8') in resp.data
    db.session.refresh(c)
    assert c.status == 'aberta'
