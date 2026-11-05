"""Foto do profissional: upload, serving via rota dedicada (BLOB no banco,
não disco — filesystem efêmero em produção), remoção, e avatar-fallback
(iniciais + cor determinística) quando não há foto."""
import io
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


def _png_bytes():
    # Conteúdo arbitrário — a rota só valida a extensão do arquivo, não o
    # conteúdo, então não precisa ser um PNG de verdade pros testes.
    return b'\x89PNG\r\n\x1a\nconteudo-fake-de-teste'


def test_avatar_fallback_sem_foto():
    prof = Profissional(id=3, nome='Ana Paula Caselato')
    assert prof.avatar_iniciais() == 'AC'
    assert prof.avatar_cor().startswith('#')

    prof_um_nome = Profissional(id=5, nome='Madonna')
    assert prof_um_nome.avatar_iniciais() == 'M'


def test_foto_serve_404_sem_foto(client):
    empresa = make_empresa()
    prof = Profissional(nome='Sem Foto', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()

    resp = client.get(f'/profissional-foto/{prof.id}')
    assert resp.status_code == 404


def test_upload_e_servir_foto(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Com Foto', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()

    data = {
        'nome': 'Com Foto',
        'foto': (io.BytesIO(_png_bytes()), 'foto.png'),
    }
    resp = client.post(f'/admin/profissionais/{prof.id}', data=data,
                        content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(prof)
    assert prof.foto_data is not None
    assert prof.foto_mime == 'image/png'

    resp_img = client.get(f'/profissional-foto/{prof.id}')
    assert resp_img.status_code == 200
    assert resp_img.data == prof.foto_data
    assert resp_img.mimetype == 'image/png'


def test_remover_foto(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Vai Remover', empresa_id=empresa.id, ativo=True,
                         foto_data=_png_bytes(), foto_mime='image/png')
    db.session.add(prof)
    db.session.commit()

    resp = client.post(f'/admin/profissionais/{prof.id}',
                        data={'nome': 'Vai Remover', 'remover_foto': '1'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(prof)
    assert prof.foto_data is None
    assert prof.foto_mime is None


def test_formato_invalido_de_foto_e_rejeitado(client):
    empresa = make_empresa()
    _login_admin(client, empresa)
    prof = Profissional(nome='Formato Ruim', empresa_id=empresa.id, ativo=True)
    db.session.add(prof)
    db.session.commit()

    data = {
        'nome': 'Formato Ruim',
        'foto': (io.BytesIO(b'conteudo qualquer'), 'arquivo.txt'),
    }
    resp = client.post(f'/admin/profissionais/{prof.id}', data=data,
                        content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert 'não suportado' in resp.get_data(as_text=True).lower()
    db.session.refresh(prof)
    assert prof.foto_data is None
