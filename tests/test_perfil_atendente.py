"""Perfil 'atendente' passa a ter acesso às telas de catálogo (Serviços,
Categorias, Produtos, Profissionais, Unidades, Expedientes, Pacotes) —
antes bloqueadas por inteiro, só administrador entrava. Exclusão continua
restrita a administrador em todas elas, checada na própria rota."""
from models import db, User, Profissional, Servico, Categoria, CategoriaProduto, Produto, Unidade
from tests.conftest import make_empresa


def _login_atendente(client, empresa):
    prof = Profissional(nome='Atendente Teste', empresa_id=empresa.id, ativo=True,
                         perfil_acesso='atendente')
    db.session.add(prof)
    db.session.flush()
    user = User(name='Atendente', username=f'atendente{empresa.id}', email=f'atendente{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/admin/login', data={'email': user.email, 'password': 'senha123'},
                        follow_redirects=True)
    assert resp.status_code == 200
    return user, prof


def _login_admin(client, empresa):
    user = User(name='Admin', username=f'admin{empresa.id}', email=f'admin{empresa.id}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user


def _login_leitura(client, empresa):
    """Perfil sem acesso a catálogo (ex: 'leitura') — continua bloqueado."""
    prof = Profissional(nome='Leitura Teste', empresa_id=empresa.id, ativo=True, perfil_acesso='leitura')
    db.session.add(prof)
    db.session.flush()
    user = User(name='Leitura', username=f'leitura{empresa.id}', email=f'leitura{empresa.id}@teste.com',
                empresa_id=empresa.id, role='profissional', profissional_id=prof.id)
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    return user, prof


def test_atendente_acessa_telas_de_catalogo(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)

    for url in ('/admin/servicos', '/admin/categorias', '/admin/produtos',
                '/admin/produtos/categorias', '/admin/profissionais',
                '/admin/unidades', '/admin/expedientes', '/admin/servicos/pacotes'):
        resp = client.get(url)
        assert resp.status_code == 200, f'{url} deveria ser 200 pro atendente, veio {resp.status_code}'


def test_perfil_leitura_continua_bloqueado_do_catalogo(client):
    empresa = make_empresa()
    _login_leitura(client, empresa)

    resp = client.get('/admin/servicos')
    assert resp.status_code == 403
    resp2 = client.get('/admin/profissionais')
    assert resp2.status_code == 403


def test_atendente_nao_acessa_cadastro_de_usuarios(client):
    """Usuários é uma tela de gestão de contas de acesso, não de catálogo —
    atendente continua sem acesso, só administrador."""
    empresa = make_empresa()
    _login_atendente(client, empresa)

    for url in ('/admin/users', '/admin/users/new'):
        resp = client.get(url)
        assert resp.status_code == 403, f'{url} deveria ser 403 pro atendente, veio {resp.status_code}'


def test_atendente_pode_criar_e_editar_servico_mas_nao_excluir(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)

    resp = client.post('/admin/servicos/novo', data={'nome': 'Corte Teste', 'duracao_horas': '1'},
                        follow_redirects=True)
    assert resp.status_code == 200
    servico = Servico.query.filter_by(empresa_id=empresa.id, nome='Corte Teste').first()
    assert servico is not None

    resp_edit = client.post(f'/admin/servicos/{servico.id}',
                             data={'nome': 'Corte Editado', 'duracao_horas': '1'}, follow_redirects=True)
    assert resp_edit.status_code == 200
    db.session.refresh(servico)
    assert servico.nome == 'Corte Editado'

    resp_del = client.post(f'/admin/servicos/{servico.id}', data={'action': 'excluir'})
    assert resp_del.status_code == 403
    assert db.session.get(Servico, servico.id) is not None  # continua lá


def test_atendente_nao_exclui_categoria_de_servico(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)
    cat = Categoria(nome='Cabelo', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()

    resp = client.post('/admin/categorias', data={'action': 'delete', 'id': cat.id})
    assert resp.status_code == 403
    assert db.session.get(Categoria, cat.id) is not None


def test_atendente_nao_exclui_produto(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)
    produto = Produto(nome='Shampoo', empresa_id=empresa.id, preco=30)
    db.session.add(produto)
    db.session.commit()

    resp = client.post(f'/admin/produtos/{produto.id}', data={'action': 'excluir'})
    assert resp.status_code == 403
    assert db.session.get(Produto, produto.id) is not None


def test_atendente_nao_exclui_categoria_de_produto(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)
    cat = CategoriaProduto(nome='Cosméticos', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()

    resp = client.post('/admin/produtos/categorias', data={'action': 'delete', 'id': cat.id})
    assert resp.status_code == 403
    assert db.session.get(CategoriaProduto, cat.id) is not None


def test_atendente_nao_exclui_profissional(client):
    empresa = make_empresa()
    _, atendente_prof = _login_atendente(client, empresa)
    outro = Profissional(nome='Outro Profissional', empresa_id=empresa.id, ativo=True)
    db.session.add(outro)
    db.session.commit()

    resp = client.post('/admin/profissionais', data={'action': 'delete', 'id': outro.id})
    assert resp.status_code == 403
    assert db.session.get(Profissional, outro.id) is not None


def test_atendente_pode_desativar_profissional_sem_excluir(client):
    """Toggle (ativar/desativar) não é exclusão — continua permitido."""
    empresa = make_empresa()
    _login_atendente(client, empresa)
    outro = Profissional(nome='Outro Profissional', empresa_id=empresa.id, ativo=True)
    db.session.add(outro)
    db.session.commit()

    resp = client.post('/admin/profissionais', data={'action': 'toggle', 'id': outro.id},
                        follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(outro)
    assert outro.ativo is False


def test_atendente_nao_exclui_unidade(client):
    empresa = make_empresa()
    _login_atendente(client, empresa)
    unidade = Unidade(nome='Centro', empresa_id=empresa.id)
    db.session.add(unidade)
    db.session.commit()

    resp = client.post('/admin/unidades', data={'action': 'delete', 'id': unidade.id})
    assert resp.status_code == 403
    assert db.session.get(Unidade, unidade.id) is not None


def test_admin_ainda_consegue_excluir_normalmente(client):
    """Regressão: administrador continua conseguindo excluir em todas as telas."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    cat = Categoria(nome='Para Excluir', empresa_id=empresa.id)
    db.session.add(cat)
    db.session.commit()
    cat_id = cat.id

    resp = client.post('/admin/categorias', data={'action': 'delete', 'id': cat_id}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(Categoria, cat_id) is None


def test_unidades_tela_propria_fora_de_configuracoes(client):
    """Unidades deixou de redirecionar pra configuracoes — vira tela própria."""
    empresa = make_empresa()
    _login_admin(client, empresa)
    resp = client.get('/admin/unidades', follow_redirects=False)
    assert resp.status_code == 200  # não é mais um redirect
