"""
Etapa 6 — Onboarding self-service.

Fluxo: /signup → cria Empresa (trial 14 dias) + User (empresa_admin)
       → seed de dados padrão → login automático → /admin/boas-vindas
"""

import re
from datetime import date, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user

signup_bp = Blueprint('signup', __name__)


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[àáâãä]', 'a', s)
    s = re.sub(r'[èéêë]', 'e', s)
    s = re.sub(r'[ìíîï]', 'i', s)
    s = re.sub(r'[òóôõö]', 'o', s)
    s = re.sub(r'[ùúûü]', 'u', s)
    s = re.sub(r'[ç]', 'c', s)
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s]+', '-', s)
    s = re.sub(r'-{2,}', '-', s)
    return s.strip('-')[:60]


def _seed_empresa(db, empresa):
    """Cria dados padrão para uma nova empresa recém-criada."""
    from models import Unidade, Categoria

    db.session.add(Unidade(
        nome=empresa.nome,
        cidade='',
        estado='',
        ativo=True,
        empresa_id=empresa.id,
    ))

    for nome_cat in ['Cabelo', 'Unhas', 'Estética Facial', 'Corporal', 'Relaxamento']:
        db.session.add(Categoria(
            nome=nome_cat,
            ativo=True,
            empresa_id=empresa.id,
        ))

    db.session.commit()


@signup_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    from models import db, Empresa, User

    if request.method == 'GET':
        return render_template('signup.html')

    nome_empresa = request.form.get('nome_empresa', '').strip()
    nome_user    = request.form.get('nome_user', '').strip()
    email        = request.form.get('email', '').strip().lower()
    senha        = request.form.get('senha', '')
    confirma     = request.form.get('confirma', '')
    slug         = request.form.get('slug', '').strip().lower() or _slugify(nome_empresa)

    # Validações
    if not all([nome_empresa, nome_user, email, senha, slug]):
        flash('Preencha todos os campos obrigatórios.', 'error')
        return render_template('signup.html', form=request.form)

    if len(senha) < 6:
        flash('A senha deve ter pelo menos 6 caracteres.', 'error')
        return render_template('signup.html', form=request.form)

    if senha != confirma:
        flash('As senhas não coincidem.', 'error')
        return render_template('signup.html', form=request.form)

    if not re.match(r'^[a-z0-9-]+$', slug):
        flash('Slug inválido: use apenas letras minúsculas, números e hífens.', 'error')
        return render_template('signup.html', form=request.form)

    if Empresa.query.filter_by(slug=slug).first():
        flash('Este slug já está em uso. Escolha outro identificador.', 'error')
        return render_template('signup.html', form=request.form)

    if User.query.filter_by(email=email).first():
        flash('Este e-mail já está cadastrado.', 'error')
        return render_template('signup.html', form=request.form)

    # Criar empresa em trial de 14 dias
    empresa = Empresa(
        nome=nome_empresa,
        slug=slug,
        plano='trial',
        status='ativa',
        trial_ends_at=date.today() + timedelta(days=14),
        email=email,
    )
    db.session.add(empresa)
    db.session.flush()

    # Criar usuário administrador da empresa
    username_base = re.sub(r'[^a-z0-9]', '', email.split('@')[0])[:30] or 'admin'
    username = username_base
    suffix = 1
    while User.query.filter_by(username=username).first():
        username = f'{username_base}{suffix}'
        suffix += 1

    user = User(
        name=nome_user,
        username=username,
        email=email,
        empresa_id=empresa.id,
        role='empresa_admin',
        is_admin=True,
    )
    user.set_password(senha)
    db.session.add(user)
    db.session.flush()

    # Seed de dados padrão
    _seed_empresa(db, empresa)

    db.session.commit()

    login_user(user)
    flash(f'Bem-vindo(a), {nome_user}! Seu painel está pronto.', 'success')
    return redirect(url_for('admin.boas_vindas'))
