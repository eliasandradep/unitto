from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user
from datetime import date, datetime, timedelta
from collections import defaultdict
from decimal import Decimal

from . import saas_bp
from models import db, Empresa, User, Assinatura, Plano, PlanoItem, Profissional


@saas_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.filter_by(role='saas_admin').first():
        return redirect(url_for('admin.login'))

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        phone    = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not all([name, username, email, password]):
            flash('Preencha todos os campos obrigatórios.', 'error')
        elif password != confirm:
            flash('As senhas não coincidem.', 'error')
        elif len(password) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'error')
        elif User.query.filter_by(username=username).first():
            flash('Nome de usuário já em uso.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('E-mail já cadastrado.', 'error')
        else:
            user = User(name=name, username=username, email=email, phone=phone, role='saas_admin')
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Conta de superadmin criada com sucesso!', 'success')
            return redirect(url_for('saas_admin.dashboard'))

    return render_template('saas_admin/setup.html')


@saas_bp.route('/')
def dashboard():
    empresas = Empresa.query.order_by(Empresa.created_at.desc()).all()
    stats = {}
    for emp in empresas:
        stats[emp.id] = {
            'users': User.query.filter_by(empresa_id=emp.id).count(),
        }
    return render_template('saas_admin/dashboard.html', empresas=empresas, stats=stats)


@saas_bp.route('/empresas/<int:empresa_id>/toggle-status', methods=['POST'])
def empresa_toggle_status(empresa_id):
    emp = db.get_or_404(Empresa, empresa_id)
    novo = 'suspensa' if emp.status == 'ativa' else 'ativa'
    emp.status = novo
    db.session.commit()
    flash(f'Empresa "{emp.nome}" agora está {novo}.', 'success')
    return redirect(url_for('saas_admin.dashboard'))


@saas_bp.route('/empresas/<int:empresa_id>/edit', methods=['GET', 'POST'])
def empresa_edit(empresa_id):
    emp = db.get_or_404(Empresa, empresa_id)
    if request.method == 'POST':
        emp.nome          = request.form.get('nome', '').strip() or emp.nome
        emp.slug          = request.form.get('slug', '').strip() or emp.slug
        emp.plano         = request.form.get('plano', emp.plano)
        emp.status        = request.form.get('status', emp.status)
        emp.telefone      = request.form.get('telefone', '').strip() or None
        emp.email         = request.form.get('email', '').strip() or None
        trial_s           = request.form.get('trial_ends_at', '').strip()
        emp.trial_ends_at = date.fromisoformat(trial_s) if trial_s else emp.trial_ends_at
        db.session.commit()
        flash('Empresa atualizada.', 'success')
        return redirect(url_for('saas_admin.dashboard'))
    return render_template('saas_admin/empresa_edit.html', emp=emp)


@saas_bp.route('/empresas/nova', methods=['GET', 'POST'])
def empresa_nova():
    if request.method == 'POST':
        nome  = request.form.get('nome', '').strip()
        slug  = request.form.get('slug', '').strip()
        plano = request.form.get('plano', 'trial')
        if not nome or not slug:
            flash('Nome e slug são obrigatórios.', 'error')
        elif Empresa.query.filter_by(slug=slug).first():
            flash('Slug já em uso.', 'error')
        else:
            trial_s = request.form.get('trial_ends_at', '').strip()
            emp = Empresa(
                nome=nome, slug=slug, plano=plano, status='ativa',
                trial_ends_at=date.fromisoformat(trial_s) if trial_s else None,
                telefone=request.form.get('telefone', '').strip() or None,
                email=request.form.get('email', '').strip() or None,
            )
            db.session.add(emp)
            db.session.commit()
            flash(f'Empresa "{nome}" criada.', 'success')
            return redirect(url_for('saas_admin.dashboard'))
    return render_template('saas_admin/empresa_edit.html', emp=None)


@saas_bp.route('/planos')
def planos_lista():
    planos = Plano.query.order_by(Plano.ordem, Plano.id).all()
    assinantes = defaultdict(int)
    for assin in Assinatura.query.filter_by(status='ativa').all():
        assinantes[assin.plano_id] += 1
    return render_template('saas_admin/planos.html', planos=planos, assinantes=assinantes)


def _salvar_itens(plano, textos):
    PlanoItem.query.filter_by(plano_id=plano.id).delete()
    for i, texto in enumerate(t.strip() for t in textos):
        if texto:
            db.session.add(PlanoItem(plano_id=plano.id, texto=texto, ordem=i))


@saas_bp.route('/planos/novo', methods=['GET', 'POST'])
def plano_novo():
    if request.method == 'POST':
        slug = request.form.get('slug', '').strip()
        nome = request.form.get('nome', '').strip()
        if not slug or not nome:
            flash('Nome e slug são obrigatórios.', 'error')
        elif Plano.query.filter_by(slug=slug).first():
            flash('Slug já em uso.', 'error')
        else:
            preco_s = request.form.get('preco', '').strip()
            plano = Plano(
                slug=slug, nome=nome,
                tipo=request.form.get('tipo', 'mensal'),
                preco=Decimal(preco_s) if preco_s else None,
                stripe_price_id=request.form.get('stripe_price_id', '').strip() or None,
                max_profissionais=request.form.get('max_profissionais', type=int) or 1,
                max_wa_mes=request.form.get('max_wa_mes', type=int) or 0,
                max_simultaneos=request.form.get('max_simultaneos', type=int) or 2,
                tem_relatorios='tem_relatorios' in request.form,
                destaque='destaque' in request.form,
                ordem=request.form.get('ordem', type=int) or 0,
                ativo='ativo' in request.form,
            )
            db.session.add(plano)
            db.session.flush()
            _salvar_itens(plano, request.form.getlist('itens[]'))
            db.session.commit()
            flash(f'Plano "{nome}" criado.', 'success')
            return redirect(url_for('saas_admin.planos_lista'))
    return render_template('saas_admin/plano_edit.html', plano=None)


@saas_bp.route('/planos/<int:plano_id>/edit', methods=['GET', 'POST'])
def plano_edit(plano_id):
    plano = db.get_or_404(Plano, plano_id)
    if request.method == 'POST':
        novo_slug = request.form.get('slug', '').strip()
        nome      = request.form.get('nome', '').strip()
        if not novo_slug or not nome:
            flash('Nome e slug são obrigatórios.', 'error')
        elif novo_slug != plano.slug and Plano.query.filter_by(slug=novo_slug).first():
            flash('Slug já em uso.', 'error')
        else:
            preco_s = request.form.get('preco', '').strip()
            plano.slug              = novo_slug
            plano.nome              = nome
            plano.tipo              = request.form.get('tipo', 'mensal')
            plano.preco             = Decimal(preco_s) if preco_s else None
            plano.stripe_price_id   = request.form.get('stripe_price_id', '').strip() or None
            plano.max_profissionais = request.form.get('max_profissionais', type=int) or 1
            plano.max_wa_mes        = request.form.get('max_wa_mes', type=int) or 0
            plano.max_simultaneos   = request.form.get('max_simultaneos', type=int) or 2
            plano.tem_relatorios    = 'tem_relatorios' in request.form
            plano.destaque          = 'destaque' in request.form
            plano.ordem             = request.form.get('ordem', type=int) or 0
            plano.ativo             = 'ativo' in request.form
            _salvar_itens(plano, request.form.getlist('itens[]'))
            db.session.commit()
            flash('Plano atualizado.', 'success')
            return redirect(url_for('saas_admin.planos_lista'))
    return render_template('saas_admin/plano_edit.html', plano=plano)


@saas_bp.route('/planos/<int:plano_id>/toggle-ativo', methods=['POST'])
def plano_toggle_ativo(plano_id):
    plano = db.get_or_404(Plano, plano_id)
    plano.ativo = not plano.ativo
    db.session.commit()
    flash(f'Plano "{plano.nome}" agora está {"ativo" if plano.ativo else "inativo"}.', 'success')
    return redirect(url_for('saas_admin.planos_lista'))


@saas_bp.route('/planos/<int:plano_id>/excluir', methods=['POST'])
def plano_excluir(plano_id):
    plano = db.get_or_404(Plano, plano_id)
    if Assinatura.query.filter_by(plano_id=plano_id).count() > 0:
        flash(f'Plano "{plano.nome}" tem assinaturas vinculadas e não pode ser excluído. Desative-o em vez disso.', 'error')
        return redirect(url_for('saas_admin.planos_lista'))
    PlanoItem.query.filter_by(plano_id=plano_id).delete()
    db.session.delete(plano)
    db.session.commit()
    flash(f'Plano "{plano.nome}" excluído.', 'success')
    return redirect(url_for('saas_admin.planos_lista'))


@saas_bp.route('/metrics')
def metrics():
    today = datetime.utcnow().date()
    since = datetime.utcnow() - timedelta(days=29)

    empresas = Empresa.query.all()
    status_counts = defaultdict(int)
    for emp in empresas:
        status_counts[emp.status or 'ativa'] += 1
    trial_count = sum(1 for emp in empresas if emp.plano == 'trial')

    novas_by_day = defaultdict(int)
    for emp in empresas:
        if emp.created_at and emp.created_at >= since:
            novas_by_day[emp.created_at.date()] += 1
    daily_labels, daily_novas = [], []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        daily_labels.append(day.strftime('%d/%m'))
        daily_novas.append(novas_by_day.get(day, 0))

    # MRR — só considera assinaturas ativas via Stripe (Assinatura + Plano)
    assinaturas_ativas = (Assinatura.query
                          .filter_by(status='ativa')
                          .join(Plano)
                          .all())
    mrr = Decimal('0')
    plano_counts = defaultdict(int)
    for assin in assinaturas_ativas:
        mrr += assin.plano.preco or Decimal('0')
        plano_counts[assin.plano.nome] += 1

    # Trials expirando nos próximos 7 dias
    limite = today + timedelta(days=7)
    trials_expirando = (Empresa.query
                        .filter(Empresa.plano == 'trial',
                                Empresa.trial_ends_at.isnot(None),
                                Empresa.trial_ends_at <= limite)
                        .order_by(Empresa.trial_ends_at)
                        .all())

    # Uso por empresa
    uso_por_empresa = []
    for emp in sorted(empresas, key=lambda e: e.nome.lower()):
        uso_por_empresa.append({
            'empresa': emp,
            'profissionais': Profissional.query.filter_by(empresa_id=emp.id).count(),
            'usuarios': User.query.filter_by(empresa_id=emp.id).count(),
        })

    return render_template(
        'saas_admin/metrics.html',
        total_empresas=len(empresas),
        status_counts=dict(status_counts),
        trial_count=trial_count,
        daily_labels=daily_labels,
        daily_novas=daily_novas,
        mrr=mrr,
        plano_counts=dict(plano_counts),
        trials_expirando=trials_expirando,
        uso_por_empresa=uso_por_empresa,
    )
