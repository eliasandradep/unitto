import json
import os
from collections import defaultdict
from flask import render_template, redirect, url_for, request, flash, jsonify, g, current_app, abort
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

from . import admin_bp
from .tenant import tq, get_setting, save_setting
from .auth import require_role
from models import (db, User, Lead, Setting, PageView, ROLES,
                    Cliente, AnamneseCapilar, AnamneseCorporal,
                    Categoria, Unidade, Profissional, Servico,
                    Agendamento, BloqueioAgenda, ComissaoProfissional,
                    Expediente, ExpedienteDia, Comanda, ComandaItem, PagamentoComanda,
                    Pacote, PacoteItem, VendaPacote, VendaPacoteItem,
                    EscalaProfissionalUnidade, RecebimentoCliente,
                    ContaPagar, ContaReceber, FormaPagamento,
                    LEAD_STATUSES, LEAD_SOURCES, PERFIL_ACESSO, FORMA_PAGAMENTO, DIAS_SEMANA)
from themes import THEMES


# ── Auth ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/')
def index():
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'saas_admin':
            return redirect(url_for('saas_admin.dashboard'))
        return redirect(url_for('admin.dashboard'))

    if not User.query.first():
        return redirect(url_for('admin.setup'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter(db.func.lower(User.username) == username.lower()).first()
        if user and user.check_password(password):
            login_user(user)
            if user.role == 'saas_admin':
                return redirect(url_for('saas_admin.dashboard'))
            return redirect(url_for('admin.dashboard'))
        flash('Usuário ou senha incorretos.', 'error')

    return render_template('admin/login.html')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


@admin_bp.route('/esqueci-senha', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        import secrets
        from datetime import timedelta
        from models import PasswordResetToken
        from .mail import send_email

        email = request.form.get('email', '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user:
            token = secrets.token_urlsafe(32)
            db.session.add(PasswordResetToken(
                user_id=user.id, token=token,
                expires_at=datetime.utcnow() + timedelta(hours=1),
            ))
            db.session.commit()
            link = url_for('admin.reset_password', token=token, _external=True)
            try:
                send_email(
                    user.email,
                    'Redefinição de senha — Unitto',
                    f'Olá, {user.name}.\n\n'
                    f'Recebemos uma solicitação para redefinir sua senha no Unitto.\n'
                    f'Clique no link abaixo para criar uma nova senha (válido por 1 hora):\n\n'
                    f'{link}\n\n'
                    f'Se você não solicitou isso, ignore este e-mail.',
                )
            except Exception:
                current_app.logger.exception('Falha ao enviar e-mail de reset de senha')

        flash('Se o e-mail informado estiver cadastrado, enviamos um link de redefinição de senha.', 'success')
        return redirect(url_for('admin.login'))

    return render_template('admin/forgot_password.html')


@admin_bp.route('/resetar-senha/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    from models import PasswordResetToken
    reset = PasswordResetToken.query.filter_by(token=token).first()
    if not reset or not reset.is_valid():
        flash('Link de redefinição inválido ou expirado. Solicite um novo.', 'error')
        return redirect(url_for('admin.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        if len(password) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'error')
        elif password != password_confirm:
            flash('As senhas não coincidem.', 'error')
        else:
            reset.user.set_password(password)
            reset.used = True
            db.session.commit()
            flash('Senha redefinida com sucesso. Faça login com a nova senha.', 'success')
            return redirect(url_for('admin.login'))

    return render_template('admin/reset_password.html', token=token)


@admin_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.first():
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
        else:
            user = User(name=name, username=username, email=email, phone=phone)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Conta criada com sucesso!', 'success')
            return redirect(url_for('admin.dashboard'))

    return render_template('admin/setup.html')


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    total  = tq(Lead).count()
    by_status = {s: tq(Lead).filter_by(status=s).count() for s, _ in LEAD_STATUSES}
    recent = tq(Lead).order_by(Lead.created_at.desc()).limit(8).all()

    theme_key  = get_setting('active_theme', 'default')
    theme_name = THEMES.get(theme_key, THEMES['default'])['name']

    return render_template('admin/dashboard.html',
        total=total,
        by_status=by_status,
        recent=recent,
        statuses=LEAD_STATUSES,
        theme_name=theme_name,
        theme_key=theme_key,
    )


# ── Leads ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/leads')
@login_required
def leads():
    status_filter = request.args.get('status', '')
    source_filter = request.args.get('source', '')
    q             = request.args.get('q', '').strip()

    query = tq(Lead)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if source_filter:
        query = query.filter_by(source=source_filter)
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(Lead.name.ilike(like), Lead.phone.ilike(like), Lead.email.ilike(like))
        )

    all_leads = query.order_by(Lead.created_at.desc()).all()

    return render_template('admin/leads.html',
        leads=all_leads,
        statuses=LEAD_STATUSES,
        sources=LEAD_SOURCES,
        status_filter=status_filter,
        source_filter=source_filter,
        q=q,
    )


@admin_bp.route('/leads/new', methods=['GET', 'POST'])
@login_required
def lead_new():
    if request.method == 'POST':
        lead = Lead(
            name    = request.form.get('name', '').strip() or None,
            phone   = request.form.get('phone', '').strip(),
            email   = request.form.get('email', '').strip() or None,
            source  = request.form.get('source', 'manual'),
            service = request.form.get('service', '').strip() or None,
            message = request.form.get('message', '').strip() or None,
            status  = request.form.get('status', 'novo'),
            unit    = request.form.get('unit', '').strip() or None,
        )
        if not lead.phone:
            flash('Telefone é obrigatório.', 'error')
        else:
            db.session.add(lead)
            db.session.commit()
            flash('Lead criado com sucesso.', 'success')
            return redirect(url_for('admin.lead_detail', lead_id=lead.id))

    return render_template('admin/lead_form.html',
        lead=None, statuses=LEAD_STATUSES, sources=LEAD_SOURCES)


@admin_bp.route('/leads/<int:lead_id>', methods=['GET', 'POST'])
@login_required
def lead_detail(lead_id):
    lead = db.get_or_404(Lead, lead_id)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_status':
            lead.status     = request.form.get('status', lead.status)
            lead.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Status atualizado.', 'success')

        elif action == 'add_note':
            note = request.form.get('note', '').strip()
            if note:
                ts = datetime.now().strftime('%d/%m/%Y %H:%M')
                existing = lead.notes or ''
                lead.notes = f"[{ts}] {note}\n{existing}".strip()
                lead.updated_at = datetime.utcnow()
                db.session.commit()
                flash('Anotação adicionada.', 'success')

        elif action == 'update_info':
            lead.name    = request.form.get('name', '').strip() or lead.name
            lead.email   = request.form.get('email', '').strip() or lead.email
            lead.service = request.form.get('service', '').strip() or lead.service
            lead.unit    = request.form.get('unit', '').strip() or lead.unit
            lead.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Informações atualizadas.', 'success')

        return redirect(url_for('admin.lead_detail', lead_id=lead.id))

    digits = ''.join(ch for ch in (lead.phone or '') if ch.isdigit())
    cliente_vinculado = None
    if len(digits) >= 8:
        cliente_vinculado = tq(Cliente).filter(
            Cliente.telefone.like(f'%{digits[-8:]}')
        ).first()

    return render_template('admin/lead_detail.html',
        lead=lead, statuses=LEAD_STATUSES, cliente_vinculado=cliente_vinculado)


@admin_bp.route('/leads/<int:lead_id>/converter', methods=['POST'])
@login_required
def lead_convert(lead_id):
    lead = db.get_or_404(Lead, lead_id)

    digits = ''.join(ch for ch in (lead.phone or '') if ch.isdigit())
    existing = None
    if len(digits) >= 8:
        existing = tq(Cliente).filter(
            Cliente.telefone.like(f'%{digits[-8:]}')
        ).first()

    ts  = datetime.now().strftime('%d/%m/%Y %H:%M')
    note_prefix = lead.notes or ''

    if existing:
        lead.status     = 'convertido'
        lead.updated_at = datetime.utcnow()
        lead.notes      = f"[{ts}] Vinculado ao cliente #{existing.id} — {existing.nome}\n{note_prefix}".strip()
        db.session.commit()
        flash(f'Telefone já possui cadastro: {existing.nome}. Lead marcado como convertido e vinculado.', 'success')
        return redirect(url_for('admin.cliente_detalhe', cliente_id=existing.id))

    c = Cliente(
        nome             = lead.name or 'Sem nome',
        telefone         = lead.phone,
        email            = lead.email or None,
        como_conheceu    = lead.source_label() or None,
        descricao        = lead.message or None,
    )
    db.session.add(c)

    lead.status     = 'convertido'
    lead.updated_at = datetime.utcnow()
    lead.notes      = f"[{ts}] Convertido em cliente\n{note_prefix}".strip()
    db.session.flush()

    db.session.commit()
    flash('Lead convertido em cliente com sucesso!', 'success')
    return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id))


@admin_bp.route('/leads/<int:lead_id>/delete', methods=['POST'])
@login_required
def lead_delete(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    db.session.delete(lead)
    db.session.commit()
    flash('Lead removido.', 'success')
    return redirect(url_for('admin.leads'))


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
def user_new():
    if not current_user.has_role('empresa_admin', 'saas_admin'):
        abort(403)

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        phone    = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        requested_role = request.form.get('role', 'empresa_admin')
        if requested_role == 'saas_admin' and current_user.role != 'saas_admin':
            flash('Você não tem permissão para atribuir o papel SaaS Admin.', 'error')
            return render_template('admin/user_form.html', user=None, roles=ROLES)

        error = _validate_user(name, username, email, password, confirm)
        if error:
            flash(error, 'error')
        elif User.query.filter_by(username=username).first():
            flash('Nome de usuário já em uso.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('E-mail já cadastrado.', 'error')
        else:
            user = User(name=name, username=username, email=email, phone=phone)
            user.role = requested_role
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Usuário criado com sucesso.', 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=None, roles=ROLES)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def user_edit(user_id):
    user = db.get_or_404(User, user_id)

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        phone    = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        dup_u = User.query.filter(User.username == username, User.id != user_id).first()
        dup_e = User.query.filter(User.email == email,    User.id != user_id).first()

        if not all([name, username, email]):
            flash('Nome, usuário e e-mail são obrigatórios.', 'error')
        elif dup_u:
            flash('Nome de usuário já em uso.', 'error')
        elif dup_e:
            flash('E-mail já cadastrado.', 'error')
        else:
            requested_role = request.form.get('role', user.role)
            if requested_role == 'saas_admin' and current_user.role != 'saas_admin':
                flash('Você não tem permissão para atribuir o papel SaaS Admin.', 'error')
                return render_template('admin/user_form.html', user=user, roles=ROLES)

            user.name     = name
            user.username = username
            user.email    = email
            user.phone    = phone
            if current_user.has_role('empresa_admin', 'saas_admin'):
                user.role = requested_role
            if password:
                if password != confirm:
                    flash('As senhas não coincidem.', 'error')
                    return render_template('admin/user_form.html', user=user)
                if len(password) < 6:
                    flash('Senha deve ter pelo menos 6 caracteres.', 'error')
                    return render_template('admin/user_form.html', user=user, roles=ROLES)
                user.set_password(password)
            db.session.commit()
            flash('Usuário atualizado.', 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=user, roles=ROLES)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def user_delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('Você não pode remover sua própria conta.', 'error')
    else:
        db.session.delete(user)
        db.session.commit()
        flash('Usuário removido.', 'success')
    return redirect(url_for('admin.users'))


def _validate_user(name, username, email, password, confirm):
    if not all([name, username, email, password]):
        return 'Preencha todos os campos obrigatórios.'
    if password != confirm:
        return 'As senhas não coincidem.'
    if len(password) < 6:
        return 'A senha deve ter pelo menos 6 caracteres.'
    return None


# ── Metrics ───────────────────────────────────────────────────────────────────

@admin_bp.route('/metrics')
@login_required
def metrics():
    today  = datetime.utcnow().date()
    since  = datetime.utcnow() - timedelta(days=29)

    views_30d_list = PageView.query.filter(PageView.created_at >= since).all()
    views_30d  = len(views_30d_list)
    unique_30d = len(set(pv.ip_hash for pv in views_30d_list))

    views_total  = PageView.query.count()
    unique_total = db.session.query(db.func.count(db.distinct(PageView.ip_hash))).scalar() or 0

    leads_total    = tq(Lead).count()
    leads_30d_list = tq(Lead).filter(Lead.created_at >= since).all()
    leads_30d      = len(leads_30d_list)
    conversion     = round(leads_30d / unique_30d * 100, 1) if unique_30d else 0

    # Daily chart
    views_by_day = defaultdict(int)
    for pv in views_30d_list:
        views_by_day[pv.created_at.date()] += 1
    leads_by_day = defaultdict(int)
    for lead in leads_30d_list:
        leads_by_day[lead.created_at.date()] += 1

    daily_labels, daily_views, daily_leads = [], [], []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        daily_labels.append(day.strftime('%d/%m'))
        daily_views.append(views_by_day.get(day, 0))
        daily_leads.append(leads_by_day.get(day, 0))

    # Devices
    device_counts = defaultdict(int)
    for pv in views_30d_list:
        device_counts[pv.device or 'desktop'] += 1

    # Traffic sources
    ref_counts = defaultdict(int)
    for pv in views_30d_list:
        if pv.referrer:
            ref_counts[pv.referrer] += 1
    top_refs = sorted(ref_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # Peak hours
    hour_counts = [0] * 24
    for pv in views_30d_list:
        hour_counts[pv.created_at.hour] += 1

    # Lead breakdowns
    sources_dict  = dict(LEAD_SOURCES)
    statuses_dict = dict(LEAD_STATUSES)

    _eid_m = g.get('empresa_id')
    _el = (Lead.empresa_id == _eid_m,) if _eid_m else ()
    lead_src = db.session.query(Lead.source, db.func.count()).filter(*_el).group_by(Lead.source).all()
    lead_sts = db.session.query(Lead.status, db.func.count()).filter(*_el).group_by(Lead.status).all()
    lead_svc = (db.session.query(Lead.service, db.func.count())
                .filter(Lead.service.isnot(None), Lead.service != '', *_el)
                .group_by(Lead.service)
                .order_by(db.func.count().desc()).all())

    SERVICE_LABELS = {
        'mechas': 'Mechas / Balayage', 'correcao': 'Correção de Cor',
        'coloracao': 'Coloração Global', 'reconstrucao': 'Reconstrução Capilar',
        'corte': 'Corte Feminino', 'outro': 'Outro',
    }

    return render_template('admin/metrics.html',
        views_30d=views_30d, unique_30d=unique_30d,
        views_total=views_total, unique_total=unique_total,
        leads_total=leads_total, leads_30d=leads_30d, conversion=conversion,
        daily_labels=json.dumps(daily_labels),
        daily_views=json.dumps(daily_views),
        daily_leads=json.dumps(daily_leads),
        device_labels=json.dumps([{'mobile':'Mobile','tablet':'Tablet','desktop':'Desktop'}.get(k,k) for k in device_counts]),
        device_data=json.dumps(list(device_counts.values())),
        top_refs=top_refs,
        hour_counts=json.dumps(hour_counts),
        lead_src_labels=json.dumps([sources_dict.get(s, s) for s, _ in lead_src]),
        lead_src_data=json.dumps([c for _, c in lead_src]),
        lead_sts_labels=json.dumps([statuses_dict.get(s, s) for s, _ in lead_sts]),
        lead_sts_data=json.dumps([c for _, c in lead_sts]),
        lead_svc=[(SERVICE_LABELS.get(s, s), c) for s, c in lead_svc],
    )


_DEFAULT_BIRTHDAY_MSG = (
    'Olá {nome}! 🎂 Feliz aniversário! '
    'O Studio Renata Rosa deseja a você um dia repleto de alegria e realizações. '
    'Com carinho, Renata Rosa. 💛'
)


def _get_setting(key, default=''):
    return get_setting(key, default)


def _save_setting(key, value):
    save_setting(key, value)


# ── Configurações ─────────────────────────────────────────────────────────────

_LOGO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}


@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    empresa = g.get('empresa')

    if request.method == 'POST':
        section = request.form.get('section', '')

        if section == 'empresa' and empresa:
            nome = request.form.get('nome', '').strip()
            if nome:
                empresa.nome = nome

            logo_file = request.files.get('logo')
            if logo_file and logo_file.filename:
                if empresa.plano not in ('trial', 'free'):
                    ext = os.path.splitext(secure_filename(logo_file.filename))[1].lower()
                    if ext in _LOGO_EXTS:
                        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'logos')
                        os.makedirs(upload_dir, exist_ok=True)
                        filename = f"{empresa.slug}{ext}"
                        logo_file.save(os.path.join(upload_dir, filename))
                        empresa.logo_url = f'uploads/logos/{filename}'
                    else:
                        flash('Formato não suportado. Use JPG, PNG, WebP, GIF ou SVG.', 'error')
                        return redirect(url_for('admin.configuracoes'))
                else:
                    flash('Upload de logomarca disponível apenas nos planos pagos.', 'error')
                    return redirect(url_for('admin.configuracoes'))

            db.session.commit()
            flash('Dados da empresa atualizados.', 'success')

        elif section == 'aniversario':
            msg = request.form.get('birthday_message', '').strip()
            if msg:
                _save_setting('birthday_message', msg[:200])
            flash('Configurações salvas com sucesso.', 'success')

        elif section == 'unidades':
            action = request.form.get('action')
            uid    = request.form.get('id', '')

            if action == 'save':
                nome     = request.form.get('nome', '').strip()
                cidade   = request.form.get('cidade', '').strip() or None
                estado   = request.form.get('estado', '').strip() or None
                telefone = request.form.get('telefone', '').strip() or None
                if not nome:
                    flash('Nome da unidade é obrigatório.', 'error')
                else:
                    u = db.get_or_404(Unidade, int(uid)) if uid else Unidade()
                    if not uid:
                        db.session.add(u)
                    u.nome     = nome
                    u.cidade   = cidade
                    u.estado   = estado
                    u.telefone = telefone
                    db.session.commit()
                    flash('Unidade salva com sucesso.', 'success')

            elif action == 'toggle' and uid:
                u = db.get_or_404(Unidade, int(uid))
                u.ativo = not u.ativo
                db.session.commit()

            elif action == 'delete' and uid:
                u = db.get_or_404(Unidade, int(uid))
                db.session.delete(u)
                db.session.commit()
                flash('Unidade excluída.', 'success')

        return redirect(url_for('admin.configuracoes'))

    birthday_message  = _get_setting('birthday_message', _DEFAULT_BIRTHDAY_MSG)
    todas_unidades    = tq(Unidade).order_by(Unidade.nome).all()
    logo_habilitado   = empresa and empresa.plano not in ('trial', 'free')

    return render_template('admin/configuracoes.html',
        birthday_message=birthday_message,
        unidades=todas_unidades,
        logo_habilitado=logo_habilitado,
    )


# ── Themes ────────────────────────────────────────────────────────────────────

@admin_bp.route('/themes')
@login_required
def themes():
    active = get_setting('active_theme', 'default')
    return render_template('admin/themes.html', themes=THEMES, active=active)


@admin_bp.route('/themes/set', methods=['POST'])
@login_required
def theme_set():
    key = request.form.get('theme', 'default')
    if key not in THEMES:
        key = 'default'
    save_setting('active_theme', key)
    flash(f'Tema "{THEMES[key]["name"]}" ativado.', 'success')
    return redirect(url_for('admin.themes'))


# ── Serviços ──────────────────────────────────────────────────────────────────

@admin_bp.route('/servicos')
@login_required
def servicos():
    q      = request.args.get('q', '').strip()
    cat_id = request.args.get('categoria', '')
    query  = tq(Servico)
    if q:
        query = query.filter(Servico.nome.ilike(f'%{q}%'))
    if cat_id:
        try: query = query.filter_by(categoria_id=int(cat_id))
        except ValueError: pass
    all_servicos = query.order_by(Servico.nome).all()
    cats         = tq(Categoria).filter_by(ativo=True).order_by(Categoria.nome).all()
    return render_template('admin/servicos.html',
        servicos=all_servicos, categorias=cats, q=q, cat_id=cat_id)


@admin_bp.route('/servicos/importar-csv', methods=['GET', 'POST'])
@login_required
def servicos_importar_csv():
    import io, csv as csv_mod, re, unicodedata
    from decimal import Decimal, InvalidOperation

    if request.method == 'GET':
        return render_template('admin/servicos_importar.html')

    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        flash('Selecione um arquivo CSV.', 'error')
        return render_template('admin/servicos_importar.html')

    modo_duplicata = request.form.get('modo_duplicata', 'pular')

    try:
        raw = arquivo.read()
        try:
            texto = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto = raw.decode('latin-1')

        sample = texto[:2048]
        delimitador = ';' if sample.count(';') >= sample.count(',') else ','
        reader = csv_mod.DictReader(io.StringIO(texto), delimiter=delimitador)
        headers = reader.fieldnames or []

        def _norm(s):
            s = s.strip().strip('"').lower()
            s = unicodedata.normalize('NFD', s)
            return ''.join(c for c in s if unicodedata.category(c) != 'Mn')

        norm_map = {_norm(h): h for h in headers}

        def get_col(row, *keys):
            for k in keys:
                orig = norm_map.get(_norm(k))
                if orig:
                    val = (row.get(orig) or '').strip().strip('"')
                    if val:
                        return val
            return ''

        def parse_decimal(s):
            s = s.strip().replace('.', '').replace(',', '.')
            try:
                return Decimal(s)
            except InvalidOperation:
                return Decimal('0')

        def parse_tempo(s):
            s = s.strip().lower()
            h = m = 0
            mh = re.search(r'(\d+)\s*h', s)
            mm = re.search(r'h\s*(\d+)$', s) or re.search(r'(\d+)\s*min', s)
            if mh:
                h = int(mh.group(1))
            if mm:
                m = int(mm.group(1))
            return max(0, h), min(59, max(0, m))

        # Cache de categorias para evitar queries repetidas
        cat_cache = {}

        def get_or_create_cat(nome_cat):
            if not nome_cat:
                return None
            key = nome_cat.strip().lower()
            if key in cat_cache:
                return cat_cache[key]
            cat = tq(Categoria).filter(Categoria.nome.ilike(nome_cat.strip())).first()
            if not cat:
                cat = Categoria(nome=nome_cat.strip(), ativo=True)
                db.session.add(cat)
                db.session.flush()
            cat_cache[key] = cat.id
            return cat.id

        criados = atualizados = pulados = 0
        erros = []

        for i, row in enumerate(reader, start=2):
            nome = get_col(row, 'Nome', 'name', 'servico', 'serviço', 'descricao', 'descrição')
            if not nome:
                erros.append(f'Linha {i}: nome vazio (ignorada).')
                continue

            existente = tq(Servico).filter(Servico.nome.ilike(nome)).first()

            if existente and modo_duplicata == 'pular':
                pulados += 1
                continue

            s = existente or Servico()

            cat_id   = get_or_create_cat(get_col(row, 'Categoria', 'category', 'cat'))
            preco    = get_col(row, 'Preço', 'Preco', 'price', 'valor')
            comissao = get_col(row, 'Comissão', 'Comissao', 'comission')
            tempo    = get_col(row, 'Tempo', 'Duração', 'Duracao', 'duration', 'time')
            h, m     = parse_tempo(tempo) if tempo else (1, 0)

            s.nome            = nome[:100]
            s.categoria_id    = cat_id
            s.preco           = parse_decimal(preco) if preco else None
            s.comissao_valor  = parse_decimal(comissao) if comissao else None
            s.comissao_tipo   = '%'
            s.duracao_horas   = h
            s.duracao_minutos = m
            s.ativo           = True

            if not existente:
                db.session.add(s)
                criados += 1
            else:
                atualizados += 1

        db.session.commit()

        resumo = f'{criados} criado(s), {atualizados} atualizado(s), {pulados} pulado(s).'
        flash(f'Importação concluída: {resumo}', 'success')
        for e in erros[:10]:
            flash(e, 'warning')
        if len(erros) > 10:
            flash(f'... e mais {len(erros) - 10} linha(s) com erro omitida(s).', 'warning')

        return redirect(url_for('admin.servicos'))

    except Exception as exc:
        db.session.rollback()
        flash(f'Erro ao processar o arquivo: {exc}', 'error')
        return render_template('admin/servicos_importar.html')


@admin_bp.route('/servicos/novo', methods=['GET', 'POST'])
@login_required
def servico_novo():
    if request.method == 'POST':
        s = _build_servico(Servico())
        if s:
            db.session.add(s)
            db.session.commit()
            flash('Serviço cadastrado com sucesso.', 'success')
            return redirect(url_for('admin.servico_detalhe', servico_id=s.id))
    cats  = tq(Categoria).filter_by(ativo=True).order_by(Categoria.nome).all()
    profs = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    return render_template('admin/servico_form.html', s=None, categorias=cats, profissionais=profs)


@admin_bp.route('/servicos/<int:servico_id>', methods=['GET', 'POST'])
@login_required
def servico_detalhe(servico_id):
    s = db.get_or_404(Servico, servico_id)
    if request.method == 'POST':
        if request.form.get('action') == 'excluir':
            db.session.delete(s)
            db.session.commit()
            flash('Serviço excluído.', 'success')
            return redirect(url_for('admin.servicos'))
        if _build_servico(s):
            db.session.commit()
            flash('Serviço atualizado com sucesso.', 'success')
            return redirect(url_for('admin.servico_detalhe', servico_id=s.id))
    cats  = tq(Categoria).filter_by(ativo=True).order_by(Categoria.nome).all()
    profs = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    return render_template('admin/servico_form.html', s=s, categorias=cats, profissionais=profs)


def _build_servico(s):
    nome = request.form.get('nome', '').strip()
    if not nome:
        flash('Nome do serviço é obrigatório.', 'error')
        return None

    def _float(field):
        try: return float(request.form.get(field, '').replace(',', '.')) or None
        except (ValueError, AttributeError): return None

    def _int(field, default=0):
        try: return int(request.form.get(field, default))
        except (ValueError, TypeError): return default

    s.nome              = nome
    s.descricao         = request.form.get('descricao', '').strip() or None
    s.imagem_url        = request.form.get('imagem_url', '').strip() or None
    s.preco             = _float('preco')
    s.duracao_horas     = _int('duracao_horas', 1)
    s.duracao_minutos   = _int('duracao_minutos', 0)
    s.comissao_valor    = _float('comissao_valor')
    s.comissao_tipo     = request.form.get('comissao_tipo', '%')
    s.recorrencia_dias  = _int('recorrencia_dias', 0)
    cat_id = request.form.get('categoria_id', '')
    s.categoria_id      = int(cat_id) if cat_id else None
    s.agendamento_online  = bool(request.form.get('agendamento_online'))
    s.exibir_preco_online = bool(request.form.get('exibir_preco_online'))
    s.agendamentos_simult = bool(request.form.get('agendamentos_simult'))
    s.restricao_horario   = request.form.get('restricao_horario', 'sempre')
    s.ativo               = not bool(request.form.get('inativo'))
    s.updated_at          = datetime.utcnow()

    ids = [int(x) for x in request.form.getlist('profissionais_adicionais') if x.isdigit()]
    s.profissionais_adicionais = tq(Profissional).filter(Profissional.id.in_(ids)).all() if ids else []
    return s


# ── Categorias ────────────────────────────────────────────────────────────────

@admin_bp.route('/categorias', methods=['GET', 'POST'])
@login_required
def categorias():
    if request.method == 'POST':
        action  = request.form.get('action')
        cat_id  = request.form.get('id', '')
        nome    = request.form.get('nome', '').strip()
        descr   = request.form.get('descricao', '').strip() or None

        if action == 'save':
            if not nome:
                flash('Nome é obrigatório.', 'error')
            elif cat_id:
                c = db.get_or_404(Categoria, int(cat_id))
                c.nome, c.descricao = nome, descr
                db.session.commit()
                flash('Categoria atualizada.', 'success')
            else:
                db.session.add(Categoria(nome=nome, descricao=descr))
                db.session.commit()
                flash('Categoria criada.', 'success')

        elif action == 'delete' and cat_id:
            c = db.get_or_404(Categoria, int(cat_id))
            if c.servicos or c.profissionais:
                flash('Categoria está em uso e não pode ser excluída.', 'error')
            else:
                db.session.delete(c)
                db.session.commit()
                flash('Categoria excluída.', 'success')

        elif action == 'toggle' and cat_id:
            c = db.get_or_404(Categoria, int(cat_id))
            c.ativo = not c.ativo
            db.session.commit()

        return redirect(url_for('admin.categorias'))

    all_cats = tq(Categoria).order_by(Categoria.nome).all()
    return render_template('admin/categorias.html', categorias=all_cats)


# ── Profissionais ─────────────────────────────────────────────────────────────

@admin_bp.route('/profissionais', methods=['GET', 'POST'])
@login_required
def profissionais():
    if request.method == 'POST':
        action  = request.form.get('action')
        prof_id = request.form.get('id', '')

        if action == 'delete' and prof_id:
            try:
                p = db.get_or_404(Profissional, int(prof_id))
                n_ag = len(p.agendamentos)
                if n_ag:
                    flash(f'Não é possível excluir: profissional possui {n_ag} agendamento(s). '
                          'Marque-o como inativo em vez de excluir.', 'error')
                else:
                    for com in list(p.comissoes_custom):
                        db.session.delete(com)
                    for bl in list(p.bloqueios):
                        db.session.delete(bl)
                    for c in list(p.comandas):
                        c.profissional_id = None
                    db.session.flush()
                    db.session.delete(p)
                    db.session.commit()
                    flash('Profissional excluído.', 'success')
            except Exception as exc:
                db.session.rollback()
                flash(f'Não foi possível excluir: {exc}', 'error')

        elif action == 'toggle' and prof_id:
            try:
                p = db.get_or_404(Profissional, int(prof_id))
                p.ativo = not p.ativo
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                flash(f'Erro: {exc}', 'error')

        return redirect(url_for('admin.profissionais'))

    try:
        all_profs = tq(Profissional).order_by(Profissional.nome).all()
    except Exception as exc:
        flash(f'Erro ao carregar profissionais: {exc}', 'error')
        all_profs = []
    return render_template('admin/profissionais.html', profissionais=all_profs)


def _save_profissional(p):
    nome = request.form.get('nome', '').strip()
    if not nome:
        flash('Nome é obrigatório.', 'error')
        return False
    cat_ids = request.form.getlist('categorias')
    cats    = [db.session.get(Categoria, int(cid)) for cid in cat_ids if cid]
    cats    = [c for c in cats if c]
    p.nome              = nome
    p.cargo             = request.form.get('cargo', '').strip()    or None
    p.email             = request.form.get('email', '').strip()    or None
    p.telefone          = request.form.get('telefone', '').strip() or None
    p.obs               = request.form.get('obs', '').strip()      or None
    p.perfil_acesso     = request.form.get('perfil_acesso', 'profissional')
    p.agendamento_online  = bool(request.form.get('agendamento_online'))
    p.agendamentos_simult = bool(request.form.get('agendamentos_simult'))
    p.ativo             = not bool(request.form.get('inativo'))
    p.categorias        = cats
    uid = request.form.get('unidade_id', '')
    p.unidade_id = int(uid) if uid else None
    eid = request.form.get('expediente_id', '')
    p.expediente_id = int(eid) if eid else None
    return True


def _prof_form_ctx():
    return dict(
        cats      = tq(Categoria).filter_by(ativo=True).order_by(Categoria.nome).all(),
        servicos  = tq(Servico).filter_by(ativo=True).order_by(Servico.nome).all(),
        unidades  = tq(Unidade).filter_by(ativo=True).order_by(Unidade.nome).all(),
        expedientes_list = tq(Expediente).order_by(Expediente.nome).all(),
        perfis    = PERFIL_ACESSO,
    )


@admin_bp.route('/profissionais/novo', methods=['GET', 'POST'])
@login_required
def profissional_novo():
    if request.method == 'POST':
        p = Profissional()
        if _save_profissional(p):
            try:
                db.session.add(p)
                db.session.commit()
                flash('Profissional cadastrado com sucesso.', 'success')
                return redirect(url_for('admin.profissional_detalhe', prof_id=p.id))
            except Exception as exc:
                db.session.rollback()
                flash(f'Erro ao salvar: {exc}', 'error')
    ctx = _prof_form_ctx()
    svcs_data = [{'id': s.id, 'nome': s.nome} for s in ctx['servicos']]
    return render_template('admin/profissional_form.html',
        p=None, categorias=ctx['cats'], perfis=PERFIL_ACESSO,
        unidades=ctx['unidades'], expedientes_list=ctx['expedientes_list'],
        comissoes_data=[], servicos_data=svcs_data)


@admin_bp.route('/profissionais/<int:prof_id>', methods=['GET', 'POST'])
@login_required
def profissional_detalhe(prof_id):
    try:
        p = db.get_or_404(Profissional, prof_id)
    except Exception as exc:
        flash(f'Erro ao carregar profissional: {exc}', 'error')
        return redirect(url_for('admin.profissionais'))
    if request.method == 'POST':
        if _save_profissional(p):
            try:
                db.session.commit()
                flash('Profissional atualizado.', 'success')
                return redirect(url_for('admin.profissional_detalhe', prof_id=p.id))
            except Exception as exc:
                db.session.rollback()
                flash(f'Erro ao salvar: {exc}', 'error')
    try:
        ctx = _prof_form_ctx()
    except Exception as exc:
        flash(f'Erro ao carregar formulário: {exc}', 'error')
        return redirect(url_for('admin.profissionais'))
    comissoes_data = [{
        'id':           c.id,
        'servico_id':   c.servico_id,
        'servico_nome': c.servico.nome if c.servico else '(serviço removido)',
        'valor':        float(c.comissao_valor),
        'tipo':         c.comissao_tipo,
    } for c in p.comissoes_custom]
    svcs_data = [{'id': s.id, 'nome': s.nome} for s in ctx['servicos']]
    return render_template('admin/profissional_form.html',
        p=p, categorias=ctx['cats'], perfis=PERFIL_ACESSO,
        unidades=ctx['unidades'], expedientes_list=ctx['expedientes_list'],
        comissoes_data=comissoes_data, servicos_data=svcs_data)


@admin_bp.route('/profissionais/<int:prof_id>/comissao', methods=['POST'])
@login_required
def profissional_comissao_add(prof_id):
    db.get_or_404(Profissional, prof_id)
    data   = request.get_json(silent=True) or {}
    svc_id = data.get('servico_id')
    valor  = data.get('comissao_valor')
    tipo   = data.get('comissao_tipo', '%')
    if not svc_id or valor is None:
        return jsonify({'ok': False, 'error': 'Dados incompletos.'}), 400
    if ComissaoProfissional.query.filter_by(
            profissional_id=prof_id, servico_id=int(svc_id)).first():
        return jsonify({'ok': False, 'error': 'Comissão já cadastrada para este serviço.'}), 400
    svc = db.session.get(Servico, int(svc_id))
    if not svc:
        return jsonify({'ok': False, 'error': 'Serviço não encontrado.'}), 404
    try:
        valor_f = float(str(valor).replace(',', '.'))
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'Valor inválido.'}), 400
    c = ComissaoProfissional(
        profissional_id=prof_id,
        servico_id=int(svc_id),
        comissao_valor=valor_f,
        comissao_tipo='%' if tipo not in ('%', 'R') else tipo,
    )
    db.session.add(c)
    db.session.commit()
    return jsonify({
        'ok': True, 'id': c.id,
        'servico_id': c.servico_id, 'servico_nome': svc.nome,
        'valor': float(c.comissao_valor), 'tipo': c.comissao_tipo,
    })


@admin_bp.route('/profissionais/<int:prof_id>/comissao/<int:com_id>/delete', methods=['POST'])
@login_required
def profissional_comissao_delete(prof_id, com_id):
    c = ComissaoProfissional.query.filter_by(id=com_id, profissional_id=prof_id).first_or_404()
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})


# ── Escalas por unidade ────────────────────────────────────────────────────────

@admin_bp.route('/profissionais/<int:prof_id>/escala-data', methods=['GET'])
@login_required
def profissional_escala_data(prof_id):
    """Retorna a escala ativa do profissional em uma data específica (query param ?data=YYYY-MM-DD)."""
    db.get_or_404(Profissional, prof_id)
    from datetime import date as _date
    data_str = request.args.get('data', '')
    try:
        data = _date.fromisoformat(data_str)
    except ValueError:
        return jsonify({'escala': None})
    escala = EscalaProfissionalUnidade.query.filter(
        EscalaProfissionalUnidade.profissional_id == prof_id,
        EscalaProfissionalUnidade.data_inicio <= data,
        EscalaProfissionalUnidade.data_fim    >= data,
    ).first()
    if not escala:
        return jsonify({'escala': None})
    return jsonify({'escala': {
        'unidade_id':   escala.unidade_id,
        'unidade_nome': escala.unidade.label(),
        'data_inicio':  escala.data_inicio.strftime('%d/%m/%Y'),
        'data_fim':     escala.data_fim.strftime('%d/%m/%Y'),
    }})


@admin_bp.route('/profissionais/<int:prof_id>/escalas', methods=['GET'])
@login_required
def profissional_escalas(prof_id):
    db.get_or_404(Profissional, prof_id)
    escalas = EscalaProfissionalUnidade.query.filter_by(
        profissional_id=prof_id
    ).order_by(EscalaProfissionalUnidade.data_inicio).all()
    return jsonify([{
        'id':          e.id,
        'unidade_id':  e.unidade_id,
        'unidade_nome': e.unidade.label(),
        'data_inicio': e.data_inicio.isoformat(),
        'data_fim':    e.data_fim.isoformat(),
    } for e in escalas])


@admin_bp.route('/profissionais/<int:prof_id>/escalas', methods=['POST'])
@login_required
def profissional_escala_add(prof_id):
    db.get_or_404(Profissional, prof_id)
    data       = request.get_json(silent=True) or {}
    unidade_id = data.get('unidade_id')
    di_str     = data.get('data_inicio', '').strip()
    df_str     = data.get('data_fim', '').strip()
    if not unidade_id or not di_str or not df_str:
        return jsonify({'ok': False, 'error': 'Dados incompletos.'}), 400
    unidade = db.session.get(Unidade, int(unidade_id))
    if not unidade:
        return jsonify({'ok': False, 'error': 'Unidade não encontrada.'}), 404
    from datetime import date as _date
    try:
        di = _date.fromisoformat(di_str)
        df = _date.fromisoformat(df_str)
    except ValueError:
        return jsonify({'ok': False, 'error': 'Datas inválidas.'}), 400
    if df < di:
        return jsonify({'ok': False, 'error': 'Data fim deve ser igual ou posterior à data início.'}), 400
    e = EscalaProfissionalUnidade(
        profissional_id=prof_id,
        unidade_id=int(unidade_id),
        data_inicio=di,
        data_fim=df,
    )
    db.session.add(e)
    db.session.commit()
    return jsonify({
        'ok': True, 'id': e.id,
        'unidade_id': e.unidade_id, 'unidade_nome': unidade.label(),
        'data_inicio': e.data_inicio.isoformat(), 'data_fim': e.data_fim.isoformat(),
    })


@admin_bp.route('/profissionais/<int:prof_id>/escalas/<int:escala_id>/delete', methods=['POST'])
@login_required
def profissional_escala_delete(prof_id, escala_id):
    e = EscalaProfissionalUnidade.query.filter_by(
        id=escala_id, profissional_id=prof_id
    ).first_or_404()
    db.session.delete(e)
    db.session.commit()
    return jsonify({'ok': True})


# ── Unidades — redirecionado para Configurações da Empresa ───────────────────

@admin_bp.route('/unidades', methods=['GET', 'POST'])
@login_required
def unidades():
    return redirect(url_for('admin.configuracoes'))


# ── Expedientes ───────────────────────────────────────────────────────────────

def _save_expediente_dias(e):
    from datetime import time as _time
    from models import ExpedienteDia
    e.dias.clear()
    db.session.flush()  # garante DELETE antes dos INSERTs (evita violação de uq_expdia)
    for dia in range(7):
        if not request.form.get(f'dia_{dia}_ativo'):
            continue
        hi = request.form.get(f'dia_{dia}_hi', '').strip()
        hf = request.form.get(f'dia_{dia}_hf', '').strip()
        if not hi or not hf:
            continue
        try:
            hi_t = _time(*map(int, hi.split(':')))
            hf_t = _time(*map(int, hf.split(':')))
        except Exception:
            continue
        almoco_ativo = request.form.get(f'dia_{dia}_almoco')
        ai_t = af_t = None
        if almoco_ativo:
            ai = request.form.get(f'dia_{dia}_ai', '').strip()
            af = request.form.get(f'dia_{dia}_af', '').strip()
            try:
                ai_t = _time(*map(int, ai.split(':'))) if ai else None
                af_t = _time(*map(int, af.split(':'))) if af else None
            except Exception:
                pass
        e.dias.append(ExpedienteDia(
            dia_semana=dia, hora_inicio=hi_t, hora_fim=hf_t,
            almoco_inicio=ai_t, almoco_fim=af_t,
        ))


@admin_bp.route('/expedientes')
@login_required
def expedientes():
    from models import DIAS_SEMANA_ABREV
    all_exps = tq(Expediente).order_by(Expediente.nome).all()
    return render_template('admin/expedientes.html',
        expedientes=all_exps, dias_abrev=DIAS_SEMANA_ABREV)


@admin_bp.route('/expedientes/novo', methods=['GET', 'POST'])
@login_required
def expediente_novo():
    if request.method == 'POST':
        try:
            nome = request.form.get('nome', '').strip() or 'Expediente'
            e = Expediente(nome=nome)
            db.session.add(e)
            db.session.flush()
            _save_expediente_dias(e)
            db.session.commit()
            flash('Expediente criado com sucesso.', 'success')
            return redirect(url_for('admin.expedientes'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Erro ao criar expediente: {exc}', 'error')
    return render_template('admin/expediente_form.html', e=None, dias=DIAS_SEMANA, dias_map={})


@admin_bp.route('/expedientes/<int:exp_id>', methods=['GET', 'POST'])
@login_required
def expediente_detalhe(exp_id):
    from models import DIAS_SEMANA_ABREV
    try:
        e = db.get_or_404(Expediente, exp_id)
    except Exception as exc:
        flash(f'Erro ao carregar expediente: {exc}', 'error')
        return redirect(url_for('admin.expedientes'))
    if request.method == 'POST':
        try:
            nome = request.form.get('nome', '').strip()
            if nome:
                e.nome = nome
            _save_expediente_dias(e)
            db.session.commit()
            flash('Expediente atualizado.', 'success')
            return redirect(url_for('admin.expedientes'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Erro ao salvar expediente: {exc}', 'error')
    try:
        dias_map = {d.dia_semana: d for d in e.dias}
    except Exception as exc:
        flash(f'Erro ao carregar dias do expediente: {exc}', 'error')
        dias_map = {}
    return render_template('admin/expediente_form.html',
        e=e, dias=DIAS_SEMANA, dias_map=dias_map, dias_abrev=DIAS_SEMANA_ABREV)


@admin_bp.route('/expedientes/<int:exp_id>/excluir', methods=['POST'])
@login_required
def expediente_excluir(exp_id):
    try:
        e = db.get_or_404(Expediente, exp_id)
        for p in e.profissionais_vinculados:
            p.expediente_id = None
        db.session.delete(e)
        db.session.commit()
        flash('Expediente excluído.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Erro ao excluir expediente: {exc}', 'error')
    return redirect(url_for('admin.expedientes'))


# ── Bloqueios de Agenda ───────────────────────────────────────────────────────

def _build_bloqueio(b):
    from datetime import date, time as _time
    prof_id     = request.form.get('profissional_id', '').strip()
    data_ini    = request.form.get('data_inicio', '').strip()
    data_fim    = request.form.get('data_fim', '').strip()
    dia_inteiro = bool(request.form.get('dia_inteiro'))
    motivo      = request.form.get('motivo', '').strip() or None

    if not data_ini or not data_fim:
        flash('Data de início e fim são obrigatórias.', 'error')
        return False

    try:
        b.data_inicio = date.fromisoformat(data_ini)
        b.data_fim    = date.fromisoformat(data_fim)
    except ValueError:
        flash('Data inválida.', 'error')
        return False

    if b.data_fim < b.data_inicio:
        flash('Data fim não pode ser anterior à data início.', 'error')
        return False

    b.profissional_id = int(prof_id) if prof_id else None
    b.dia_inteiro     = dia_inteiro
    b.motivo          = motivo

    if dia_inteiro:
        b.hora_inicio = None
        b.hora_fim    = None
    else:
        hi = request.form.get('hora_inicio', '').strip()
        hf = request.form.get('hora_fim', '').strip()
        if not hi or not hf:
            flash('Informe hora início e fim.', 'error')
            return False
        try:
            hi_h, hi_m = map(int, hi.split(':'))
            hf_h, hf_m = map(int, hf.split(':'))
            b.hora_inicio = _time(hi_h, hi_m)
            b.hora_fim    = _time(hf_h, hf_m)
        except Exception:
            flash('Hora inválida.', 'error')
            return False

    return True


@admin_bp.route('/agenda/bloqueios', methods=['GET', 'POST'])
@login_required
def agenda_bloqueios():
    from datetime import date, timedelta

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'bulk_delete':
            ids = request.form.getlist('ids')
            if ids:
                tq(BloqueioAgenda).filter(BloqueioAgenda.id.in_(
                    [int(i) for i in ids if i.isdigit()]
                )).delete(synchronize_session=False)
                db.session.commit()
                flash(f'{len(ids)} bloqueio(s) removido(s).', 'success')
            return redirect(url_for('admin.agenda_bloqueios'))

        b = BloqueioAgenda()
        if _build_bloqueio(b):
            db.session.add(b)
            db.session.commit()
            flash('Bloqueio criado com sucesso.', 'success')
        return redirect(url_for('admin.agenda_bloqueios'))

    # Filtros
    resp_q  = request.args.get('responsavel', '').strip()
    dt_ini  = request.args.get('dt_ini', '')
    dt_fim  = request.args.get('dt_fim', '')

    q = tq(BloqueioAgenda)
    if resp_q:
        q = q.join(BloqueioAgenda.profissional).filter(
            Profissional.nome.ilike(f'%{resp_q}%')
        )
    if dt_ini:
        try:
            q = q.filter(BloqueioAgenda.data_fim >= date.fromisoformat(dt_ini))
        except ValueError:
            pass
    if dt_fim:
        try:
            q = q.filter(BloqueioAgenda.data_inicio <= date.fromisoformat(dt_fim))
        except ValueError:
            pass

    bloqueios = q.order_by(BloqueioAgenda.data_inicio.desc(), BloqueioAgenda.hora_inicio).all()
    profissionais = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()

    hoje  = date.today()
    d_ini = dt_ini or hoje.isoformat()
    d_fim = dt_fim or (hoje + timedelta(days=365)).isoformat()

    return render_template('admin/agenda_bloqueios.html',
        bloqueios=bloqueios, profissionais=profissionais,
        resp_q=resp_q, dt_ini=d_ini, dt_fim=d_fim)


@admin_bp.route('/agenda/bloqueios/<int:bl_id>/editar', methods=['POST'])
@login_required
def agenda_bloqueio_editar(bl_id):
    b = db.get_or_404(BloqueioAgenda, bl_id)
    if _build_bloqueio(b):
        db.session.commit()
        flash('Bloqueio atualizado.', 'success')
    return redirect(url_for('admin.agenda_bloqueios'))


@admin_bp.route('/agenda/bloqueios/<int:bl_id>/excluir', methods=['POST'])
@login_required
def agenda_bloqueio_excluir(bl_id):
    b = db.get_or_404(BloqueioAgenda, bl_id)
    db.session.delete(b)
    db.session.commit()
    flash('Bloqueio removido.', 'success')
    return redirect(url_for('admin.agenda_bloqueios'))


# ── Agenda — Listagem ────────────────────────────────────────────────────────

@admin_bp.route('/agenda/listagem', methods=['GET', 'POST'])
@login_required
def agenda_listagem():
    from datetime import date, timedelta

    if request.method == 'POST':
        ids = request.form.getlist('ids')
        if ids:
            tq(Agendamento).filter(Agendamento.id.in_(
                [int(i) for i in ids if i.isdigit()]
            )).delete(synchronize_session=False)
            db.session.commit()
            flash(f'{len(ids)} agendamento(s) removido(s).', 'success')
        return redirect(url_for('admin.agenda_listagem',
                                responsavel=request.form.get('responsavel',''),
                                dt_ini=request.form.get('dt_ini',''),
                                dt_fim=request.form.get('dt_fim','')))

    resp_q = request.args.get('responsavel', '').strip()
    dt_ini = request.args.get('dt_ini', '')
    dt_fim = request.args.get('dt_fim', '')

    q = tq(Agendamento).join(Agendamento.profissional)

    if resp_q:
        q = q.filter(Profissional.nome.ilike(f'%{resp_q}%'))
    if dt_ini:
        try:
            q = q.filter(Agendamento.data >= date.fromisoformat(dt_ini))
        except ValueError:
            pass
    if dt_fim:
        try:
            q = q.filter(Agendamento.data <= date.fromisoformat(dt_fim))
        except ValueError:
            pass

    agendamentos = q.order_by(Agendamento.data.desc(), Agendamento.hora_inicio).all()
    profissionais = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    servicos      = tq(Servico).filter_by(ativo=True).order_by(Servico.nome).all()

    hoje  = date.today()
    d_ini = dt_ini or hoje.isoformat()
    d_fim = dt_fim or (hoje + timedelta(days=365)).isoformat()

    return render_template('admin/agenda_listagem.html',
        agendamentos=agendamentos, profissionais=profissionais, servicos=servicos,
        resp_q=resp_q, dt_ini=d_ini, dt_fim=d_fim)


# ── Agenda ───────────────────────────────────────────────────────────────────

@admin_bp.route('/agenda')
@login_required
def agenda():
    from datetime import date
    data_str = request.args.get('data', date.today().isoformat())
    try:
        data_sel = date.fromisoformat(data_str)
    except ValueError:
        data_sel = date.today()
    profissionais_ativos = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    servicos_ativos      = tq(Servico).filter_by(ativo=True).order_by(Servico.nome).all()
    unidades_ativas      = tq(Unidade).filter_by(ativo=True).order_by(Unidade.nome).all()
    return render_template('admin/agenda.html',
        data_sel=data_sel,
        profissionais=profissionais_ativos,
        servicos=servicos_ativos,
        unidades=unidades_ativas,
        formas=FORMA_PAGAMENTO,
    )


def _build_expedientes_para_data(data_sel):
    """Retorna lista de blocos de indisponibilidade para cada profissional com expediente."""
    dow = data_sel.isoweekday() % 7  # 0=dom..6=sáb
    profs = tq(Profissional).filter(
        Profissional.ativo == True,
        Profissional.expediente_id.isnot(None),
    ).all()
    result = []
    for prof in profs:
        dia = ExpedienteDia.query.filter_by(
            expediente_id=prof.expediente_id, dia_semana=dow
        ).first()
        if dia:
            result.append({
                'profissional_id': prof.id,
                'hora_inicio':  dia.hora_inicio.strftime('%H:%M'),
                'hora_fim':     dia.hora_fim.strftime('%H:%M'),
                'almoco_inicio': dia.almoco_inicio.strftime('%H:%M') if dia.almoco_inicio else None,
                'almoco_fim':    dia.almoco_fim.strftime('%H:%M')    if dia.almoco_fim    else None,
                'dia_todo': False,
            })
        else:
            # Tem expediente mas não trabalha neste dia
            result.append({'profissional_id': prof.id, 'dia_todo': True,
                           'hora_inicio': None, 'hora_fim': None,
                           'almoco_inicio': None, 'almoco_fim': None})
    return result


@admin_bp.route('/agenda/dados')
@login_required
def agenda_dados():
    from datetime import date
    data_str = request.args.get('data', date.today().isoformat())
    try:
        data_sel = date.fromisoformat(data_str)
    except ValueError:
        data_sel = date.today()
    ags = tq(Agendamento).filter_by(data=data_sel).order_by(Agendamento.hora_inicio).all()
    bls = tq(BloqueioAgenda).filter(
        BloqueioAgenda.data_inicio <= data_sel,
        BloqueioAgenda.data_fim    >= data_sel,
    ).all()
    return jsonify({
        'events': [{
            'id':              a.id,
            'nome_cliente':    a.nome_cliente,
            'cliente_id':      a.cliente_id,
            'telefone':        a.telefone or '',
            'profissional_id': a.profissional_id,
            'servico_id':      a.servico_id,
            'servico_nome':    (', '.join(i.descricao for i in a.comanda.itens)
                               if a.comanda and a.comanda.itens
                               else ', '.join(s.nome for s in a.servicos_lista)
                               if a.servicos_lista
                               else (a.servico.nome if a.servico else '')),
            'servicos': [{'id': s.id, 'nome': s.nome,
                          'preco': float(s.preco or 0),
                          'dur': (s.duracao_horas or 1) * 60 + (s.duracao_minutos or 0)}
                         for s in a.servicos_lista],
            'vp_item_id':      a.venda_pacote_item_id,
            'hora_inicio':     a.hora_inicio.strftime('%H:%M'),
            'duracao_min':     a.duracao_min,
            'hora_fim':        a.hora_fim.strftime('%H:%M'),
            'status':          a.status,
            'observacoes':     a.observacoes or '',
            'como_conheceu':   a.como_conheceu or '',
            'lembrete_wa':     a.lembrete_wa,
            'unidade_id':      a.unidade_id,
            'comanda_id':      a.comanda.id     if a.comanda else None,
            'comanda_status':  a.comanda.status if a.comanda else None,
        } for a in ags],
        'bloqueios': [{
            'id':              b.id,
            'profissional_id': b.profissional_id,
            'hora_inicio':     b.hora_inicio.strftime('%H:%M') if b.hora_inicio else None,
            'hora_fim':        b.hora_fim.strftime('%H:%M')    if b.hora_fim    else None,
            'dia_inteiro':     b.dia_inteiro,
            'motivo':          b.motivo or '',
        } for b in bls],
        'expedientes': _build_expedientes_para_data(data_sel),
    })


def _build_agendamento(a):
    from datetime import date, time as _time
    data_str = request.form.get('data', '')
    hora_str = request.form.get('hora_inicio', '')
    prof_id  = request.form.get('profissional_id', '')
    nome     = request.form.get('nome_cliente', '').strip()
    if not all([data_str, hora_str, prof_id, nome]):
        flash('Preencha os campos obrigatórios: data, hora, responsável e nome do cliente.', 'error')
        return None, data_str
    try:
        data_val = date.fromisoformat(data_str)
        h, m     = map(int, hora_str.split(':'))
        hora_val = _time(h, m)
    except Exception:
        flash('Data ou hora inválida.', 'error')
        return None, data_str
    # Suporte a múltiplos serviços (servico_ids[]) com fallback para servico_id legado
    svc_ids_raw = request.form.getlist('servico_ids[]')
    if not svc_ids_raw:
        legacy = request.form.get('servico_id', '').strip()
        svc_ids_raw = [legacy] if legacy else []
    svc_ids = [int(x) for x in svc_ids_raw if x.strip().isdigit()]

    dur_form = request.form.get('duracao_min', '').strip()
    duracao  = 60

    servicos_sel = []
    for sid in svc_ids:
        s = db.session.get(Servico, sid)
        if s:
            servicos_sel.append(s)

    if dur_form:
        try: duracao = max(15, int(dur_form))
        except ValueError: pass
    elif servicos_sel:
        duracao = sum((s.duracao_horas or 1) * 60 + (s.duracao_minutos or 0) for s in servicos_sel)

    a.nome_cliente    = nome
    a.telefone        = request.form.get('telefone', '').strip() or None
    cid = request.form.get('cliente_id', '').strip()
    a.cliente_id      = int(cid) if cid else None
    a.profissional_id = int(prof_id)
    a.servico_id      = servicos_sel[0].id if servicos_sel else None
    a.servicos_lista  = servicos_sel
    a.data            = data_val
    a.hora_inicio     = hora_val
    a.duracao_min     = max(15, duracao)
    a.status          = request.form.get('status', 'agendado')
    a.observacoes     = request.form.get('observacoes', '').strip() or None
    a.como_conheceu   = request.form.get('como_conheceu', '').strip() or None
    a.lembrete_wa     = bool(request.form.get('lembrete_wa'))
    uid = request.form.get('unidade_id', '')
    a.unidade_id = int(uid) if uid else None
    vpid = request.form.get('vp_item_id', '').strip()
    a.venda_pacote_item_id = int(vpid) if vpid and vpid.isdigit() else None
    return a, data_str


def _find_expediente_conflict(profissional_id, data, hora_inicio, duracao_min):
    """Retorna mensagem de erro se o horário está fora do expediente do profissional, ou None."""
    from datetime import timedelta, datetime as _dt
    prof = db.session.get(Profissional, profissional_id)
    if not prof or not prof.expediente_id:
        return None  # sem expediente vinculado = sem restrição
    dow = data.isoweekday() % 7
    dia = ExpedienteDia.query.filter_by(
        expediente_id=prof.expediente_id, dia_semana=dow
    ).first()
    if not dia:
        return 'Profissional não trabalha neste dia'
    ag_ini = _dt.combine(data, hora_inicio)
    ag_fim = ag_ini + timedelta(minutes=duracao_min)
    ex_ini = _dt.combine(data, dia.hora_inicio)
    ex_fim = _dt.combine(data, dia.hora_fim)
    if ag_ini < ex_ini or ag_fim > ex_fim:
        return 'Fora do horário de expediente do profissional'
    if dia.almoco_inicio and dia.almoco_fim:
        al_ini = _dt.combine(data, dia.almoco_inicio)
        al_fim = _dt.combine(data, dia.almoco_fim)
        if ag_ini < al_fim and ag_fim > al_ini:
            return 'Horário de almoço do profissional'
    return None


def _find_escala_conflict(profissional_id, unidade_id, data):
    """Retorna mensagem de erro se o profissional está escalado para outra unidade nesta data, ou None."""
    escalas = EscalaProfissionalUnidade.query.filter(
        EscalaProfissionalUnidade.profissional_id == profissional_id,
        EscalaProfissionalUnidade.data_inicio <= data,
        EscalaProfissionalUnidade.data_fim    >= data,
    ).all()
    for e in escalas:
        if e.unidade_id != unidade_id:
            return (f'Profissional escalado para {e.unidade.nome} de '
                    f'{e.data_inicio.strftime("%d/%m/%Y")} a {e.data_fim.strftime("%d/%m/%Y")}')
    return None


def _find_bloqueio_conflict(profissional_id, data, hora_inicio, duracao_min, exclude_ag_id=None):
    """Retorna o primeiro BloqueioAgenda que conflita com o horário proposto, ou None."""
    from datetime import timedelta, datetime as _dt
    candidates = tq(BloqueioAgenda).filter(
        BloqueioAgenda.data_inicio <= data,
        BloqueioAgenda.data_fim    >= data,
        db.or_(
            BloqueioAgenda.profissional_id == profissional_id,
            BloqueioAgenda.profissional_id.is_(None),
        )
    ).all()
    for bl in candidates:
        if bl.dia_inteiro:
            return bl
        if bl.hora_inicio is None or bl.hora_fim is None:
            continue
        ag_ini = _dt.combine(data, hora_inicio)
        ag_fim = ag_ini + timedelta(minutes=duracao_min)
        bl_ini = _dt.combine(data, bl.hora_inicio)
        bl_fim = _dt.combine(data, bl.hora_fim)
        if ag_ini < bl_fim and ag_fim > bl_ini:
            return bl
    return None


@admin_bp.route('/agenda/novo', methods=['POST'])
@login_required
def agenda_novo():
    a, data_str = _build_agendamento(Agendamento())
    if a is None:
        return redirect(url_for('admin.agenda', data=data_str))
    exp_err = _find_expediente_conflict(a.profissional_id, a.data, a.hora_inicio, a.duracao_min)
    if exp_err:
        flash(f'Não é possível agendar: {exp_err}.', 'error')
        return redirect(url_for('admin.agenda', data=data_str))
    if a.unidade_id:
        escala_err = _find_escala_conflict(a.profissional_id, a.unidade_id, a.data)
        if escala_err:
            flash(f'Não é possível agendar: {escala_err}.', 'error')
            return redirect(url_for('admin.agenda', data=data_str))
    conflict = _find_bloqueio_conflict(a.profissional_id, a.data, a.hora_inicio, a.duracao_min)
    if conflict:
        flash(f'Não é possível agendar: {conflict.motivo or "Horário bloqueado"}.', 'error')
        return redirect(url_for('admin.agenda', data=data_str))
    db.session.add(a)
    db.session.commit()
    flash('Agendamento criado com sucesso.', 'success')
    return redirect(url_for('admin.agenda', data=data_str))


@admin_bp.route('/agenda/<int:ag_id>/editar', methods=['POST'])
@login_required
def agenda_editar(ag_id):
    a_orig = db.get_or_404(Agendamento, ag_id)
    orig_date = a_orig.data.isoformat()
    a, data_str = _build_agendamento(a_orig)
    if a is None:
        return redirect(url_for('admin.agenda', data=orig_date))
    exp_err = _find_expediente_conflict(a.profissional_id, a.data, a.hora_inicio, a.duracao_min)
    if exp_err:
        flash(f'Não é possível agendar: {exp_err}.', 'error')
        return redirect(url_for('admin.agenda', data=data_str))
    if a.unidade_id:
        escala_err = _find_escala_conflict(a.profissional_id, a.unidade_id, a.data)
        if escala_err:
            flash(f'Não é possível agendar: {escala_err}.', 'error')
            return redirect(url_for('admin.agenda', data=data_str))
    conflict = _find_bloqueio_conflict(a.profissional_id, a.data, a.hora_inicio, a.duracao_min)
    if conflict:
        flash(f'Não é possível agendar: {conflict.motivo or "Horário bloqueado"}.', 'error')
        return redirect(url_for('admin.agenda', data=data_str))
    db.session.commit()
    flash('Agendamento atualizado.', 'success')
    return redirect(url_for('admin.agenda', data=data_str))


@admin_bp.route('/agenda/<int:ag_id>/excluir', methods=['POST'])
@login_required
def agenda_excluir(ag_id):
    a = db.get_or_404(Agendamento, ag_id)
    data_str = a.data.isoformat()
    db.session.delete(a)
    db.session.commit()
    flash('Agendamento excluído.', 'success')
    return redirect(url_for('admin.agenda', data=data_str))


@admin_bp.route('/agenda/<int:ag_id>/status', methods=['POST'])
@login_required
def agenda_status(ag_id):
    a = db.get_or_404(Agendamento, ag_id)
    data = request.get_json(silent=True) or {}
    novo = data.get('status') or request.form.get('status', '')
    if novo not in {'agendado', 'confirmado', 'concluido', 'cancelado', 'faltou'}:
        return jsonify({'ok': False}), 400
    a.status = novo
    db.session.commit()
    return jsonify({'ok': True, 'status': a.status})


def _add_servicos_agendamento_comanda(comanda, agendamento):
    """Adiciona itens na comanda para todos os serviços do agendamento."""
    from decimal import Decimal
    servicos = list(agendamento.servicos_lista or [])
    if not servicos and agendamento.servico:
        servicos = [agendamento.servico]

    vp_item_id = agendamento.venda_pacote_item_id
    vpi = db.session.get(VendaPacoteItem, vp_item_id) if vp_item_id else None

    # Fallback: se não há serviço vinculado mas há item de pacote, usa o serviço do pacote
    if not servicos and vpi and vpi.servico:
        servicos = [vpi.servico]

    total_pacote = Decimal('0')  # acumula valor das sessões de pacote para desconto automático

    for i, s in enumerate(servicos):
        # Aplica venda_pacote_item_id apenas no primeiro serviço (o da sessão)
        vp_id = vp_item_id if i == 0 else None

        if vp_id and vpi:
            # Valor real da sessão (base de comissão do profissional)
            # O cliente já pagou via comanda do pacote, o desconto será aplicado abaixo
            valor_sessao = (
                vpi.pacote_item.valor_unitario
                if vpi.pacote_item and vpi.pacote_item.valor_unitario
                else (s.preco or Decimal('0'))
            )
            descricao = f'Sessão de pacote: {s.nome}'
            total_pacote += valor_sessao
        else:
            valor_sessao = s.preco or Decimal('0')
            descricao = s.nome

        db.session.add(ComandaItem(
            comanda_id=comanda.id,
            servico_id=s.id,
            descricao=descricao,
            valor=valor_sessao,
            quantidade=1,
            profissional_id=agendamento.profissional_id,
            comissao_valor=s.comissao_valor,
            comissao_tipo=s.comissao_tipo or '%',
            venda_pacote_item_id=vp_id,
        ))

    # Aplica desconto igual ao valor das sessões de pacote:
    # garante Resta a Pagar = 0 (cliente pagou via comanda do pacote)
    # sem afetar a base de comissão do profissional
    if total_pacote > 0:
        comanda.desconto = (comanda.desconto or Decimal('0')) + total_pacote

    # Incrementa sessão usada se veio de pacote (em agenda_faturar, que não passa pelo comanda_update)
    if vpi:
        if vpi.quantidade_usada < vpi.quantidade_total:
            vpi.quantidade_usada += 1
            if vpi.venda.sessoes_restantes <= 0:
                vpi.venda.status = 'concluido'


@admin_bp.route('/agenda/<int:ag_id>/faturar', methods=['POST'])
@login_required
def agenda_faturar(ag_id):
    from datetime import date
    from sqlalchemy import func
    a = db.get_or_404(Agendamento, ag_id)
    if a.comanda:
        return redirect(url_for('admin.comanda_detalhe', comanda_id=a.comanda.id))
    codigo = _next_codigo()
    c = Comanda(
        codigo=codigo, data=a.data,
        cliente_id=a.cliente_id, nome_cliente=a.nome_cliente,
        agendamento_id=a.id, profissional_id=a.profissional_id,
        unidade_id=a.unidade_id, status='aberta',
    )
    db.session.add(c)
    db.session.flush()
    _add_servicos_agendamento_comanda(c, a)
    a.status = 'concluido'
    db.session.commit()
    return redirect(url_for('admin.comanda_detalhe', comanda_id=c.id))


# ── Financeiro ────────────────────────────────────────────────────────────────

def _next_codigo():
    from sqlalchemy import func
    q = db.session.query(func.max(Comanda.codigo))
    eid = g.get('empresa_id')
    if eid:
        q = q.filter(Comanda.empresa_id == eid)
    return (q.scalar() or 0) + 1


@admin_bp.route('/financeiro')
@login_required
def financeiro():
    from datetime import date, timedelta
    from sqlalchemy import func
    hoje = date.today()
    mes_ini = hoje.replace(day=1)

    # Totais do mês
    # Métricas e recentes consideram apenas comandas fechadas
    _fechada = Comanda.status == 'fechada'
    _eid = g.get('empresa_id')
    _ec = (Comanda.empresa_id == _eid,) if _eid else ()
    _er = (RecebimentoCliente.empresa_id == _eid,) if _eid else ()

    pag_mes = db.session.query(
        func.sum(PagamentoComanda.valor)
    ).join(Comanda).filter(
        _fechada, Comanda.data >= mes_ini, Comanda.data <= hoje, *_ec
    ).scalar() or 0
    rec_mes = db.session.query(
        func.sum(RecebimentoCliente.valor)
    ).filter(
        RecebimentoCliente.data >= mes_ini, RecebimentoCliente.data <= hoje, *_er
    ).scalar() or 0
    fat_mes = float(pag_mes) + float(rec_mes)

    abertas = tq(Comanda).filter_by(status='aberta').count()

    pag_hoje = db.session.query(
        func.sum(PagamentoComanda.valor)
    ).join(Comanda).filter(_fechada, Comanda.data == hoje, *_ec).scalar() or 0
    rec_hoje = db.session.query(
        func.sum(RecebimentoCliente.valor)
    ).filter(RecebimentoCliente.data == hoje, *_er).scalar() or 0
    fat_hoje = float(pag_hoje) + float(rec_hoje)

    # Últimos 14 dias para o gráfico
    dias = [(hoje - timedelta(days=i)) for i in range(13, -1, -1)]
    fat_dias = {}
    rows = db.session.query(
        Comanda.data, func.sum(PagamentoComanda.valor)
    ).join(PagamentoComanda).filter(
        _fechada, Comanda.data >= dias[0], *_ec
    ).group_by(Comanda.data).all()
    for d, v in rows:
        fat_dias[d] = float(v or 0)
    rows_rec = db.session.query(
        RecebimentoCliente.data, func.sum(RecebimentoCliente.valor)
    ).filter(RecebimentoCliente.data >= dias[0], *_er).group_by(RecebimentoCliente.data).all()
    for d, v in rows_rec:
        fat_dias[d] = fat_dias.get(d, 0) + float(v or 0)
    chart_labels = [d.strftime('%d/%m') for d in dias]
    chart_values = [fat_dias.get(d, 0) for d in dias]

    # Por forma de pagamento (mês) — comandas + recebimentos avulsos
    forma_map = dict(FORMA_PAGAMENTO)
    totais_forma: dict = {}
    pf_rows = db.session.query(
        PagamentoComanda.forma_pagamento,
        func.sum(PagamentoComanda.valor).label('total')
    ).join(Comanda).filter(
        _fechada, Comanda.data >= mes_ini, *_ec
    ).group_by(PagamentoComanda.forma_pagamento).all()
    for f, t in pf_rows:
        totais_forma[f] = totais_forma.get(f, 0) + float(t or 0)
    rec_forma_rows = db.session.query(
        RecebimentoCliente.forma_pagamento,
        func.sum(RecebimentoCliente.valor).label('total')
    ).filter(RecebimentoCliente.data >= mes_ini, *_er).group_by(
        RecebimentoCliente.forma_pagamento).all()
    for f, t in rec_forma_rows:
        totais_forma[f] = totais_forma.get(f, 0) + float(t or 0)
    por_forma = [{'forma': forma_map.get(f, f), 'total': t}
                 for f, t in sorted(totais_forma.items(), key=lambda x: -x[1])]

    # Últimas comandas fechadas
    recentes = tq(Comanda).filter(_fechada).order_by(
        Comanda.data.desc(), Comanda.id.desc()).limit(10).all()

    return render_template('admin/financeiro_index.html',
        fat_mes=fat_mes, abertas=abertas, fat_hoje=fat_hoje,
        chart_labels=chart_labels, chart_values=chart_values,
        por_forma=por_forma, recentes=recentes,
    )


@admin_bp.route('/financeiro/comandas', methods=['GET', 'POST'])
@login_required
def financeiro_comandas():
    from datetime import date, timedelta

    if request.method == 'POST':
        ids = request.form.getlist('ids')
        if ids:
            for cid in ids:
                c = db.session.get(Comanda, int(cid))
                if c:
                    db.session.delete(c)
            db.session.commit()
            flash(f'{len(ids)} comanda(s) removida(s).', 'success')
        return redirect(url_for('admin.financeiro_comandas'))

    resp_q   = request.args.get('responsavel', '').strip()
    cliente_q= request.args.get('cliente', '').strip()
    dt_ini   = request.args.get('dt_ini', '')
    dt_fim   = request.args.get('dt_fim', '')
    status_f = request.args.get('status', '')

    q = tq(Comanda)
    if resp_q:
        q = q.join(Comanda.profissional).filter(Profissional.nome.ilike(f'%{resp_q}%'))
    if cliente_q:
        q = q.filter(Comanda.nome_cliente.ilike(f'%{cliente_q}%'))
    if dt_ini:
        try: q = q.filter(Comanda.data >= date.fromisoformat(dt_ini))
        except ValueError: pass
    if dt_fim:
        try: q = q.filter(Comanda.data <= date.fromisoformat(dt_fim))
        except ValueError: pass
    if status_f:
        q = q.filter(Comanda.status == status_f)

    hoje  = date.today()
    d_ini = dt_ini or hoje.isoformat()
    d_fim = dt_fim or (hoje + timedelta(days=30)).isoformat()

    comandas = q.order_by(Comanda.data.desc(), Comanda.id.desc()).all()
    return render_template('admin/financeiro_comandas.html',
        comandas=comandas, resp_q=resp_q, cliente_q=cliente_q,
        dt_ini=d_ini, dt_fim=d_fim, status_f=status_f)


def _fechar_comanda(c, saldo_override=None):
    from decimal import Decimal
    saldo_rest = saldo_override if saldo_override is not None else c.saldo
    if c.cliente_id and saldo_rest != 0:
        cl = c.cliente
        c.saldo_ajustado = saldo_rest
        cl.saldo = (cl.saldo or Decimal('0')) - saldo_rest
    c.status = 'fechada'
    _sync_conta_receber(c)


def _reabrir_comanda(c):
    from decimal import Decimal
    if c.saldo_ajustado is not None and c.cliente_id:
        cl = c.cliente
        cl.saldo = (cl.saldo or Decimal('0')) + c.saldo_ajustado
        c.saldo_ajustado = None
    c.status = 'aberta'


@admin_bp.route('/financeiro/comandas/nova', methods=['GET', 'POST'])
@login_required
def comanda_nova():
    from datetime import date
    if request.method == 'POST':
        c = Comanda(codigo=_next_codigo())
        if _save_comanda(c):
            db.session.add(c)
            db.session.commit()
            flash('Comanda criada.', 'success')
            return redirect(url_for('admin.comanda_detalhe', comanda_id=c.id))
    profs    = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    servicos = tq(Servico).filter_by(ativo=True).order_by(Servico.nome).all()
    unidades = tq(Unidade).filter_by(ativo=True).order_by(Unidade.nome).all()
    clientes = tq(Cliente).order_by(Cliente.nome).all()
    return render_template('admin/comanda_form.html',
        c=None, profs=profs, servicos=servicos, unidades=unidades,
        clientes=clientes, formas=FORMA_PAGAMENTO, hoje=date.today().isoformat())


@admin_bp.route('/financeiro/comandas/<int:comanda_id>', methods=['GET', 'POST'])
@login_required
def comanda_detalhe(comanda_id):
    from datetime import date
    c = db.get_or_404(Comanda, comanda_id)
    if request.method == 'POST':
        if _save_comanda(c):
            db.session.commit()
            flash('Comanda atualizada.', 'success')
            return redirect(url_for('admin.comanda_detalhe', comanda_id=c.id))
    profs    = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    servicos = tq(Servico).filter_by(ativo=True).order_by(Servico.nome).all()
    unidades = tq(Unidade).filter_by(ativo=True).order_by(Unidade.nome).all()
    clientes = tq(Cliente).order_by(Cliente.nome).all()
    return render_template('admin/comanda_form.html',
        c=c, profs=profs, servicos=servicos, unidades=unidades,
        clientes=clientes, formas=FORMA_PAGAMENTO, hoje=date.today().isoformat())


def _sync_conta_receber(c):
    """Creates/updates/cancels ContaReceber based on comanda saldo at closing."""
    from decimal import Decimal
    if c.id is None:
        return
    if c.status == 'fechada':
        saldo_dev = c.saldo
        if saldo_dev > 0:
            cr = tq(ContaReceber).filter_by(comanda_id=c.id, status='pendente').first()
            if cr:
                cr.valor = saldo_dev
                cr.cliente_id = c.cliente_id
            else:
                already_received = tq(ContaReceber).filter_by(
                    comanda_id=c.id, status='recebido').first()
                if not already_received:
                    db.session.add(ContaReceber(
                        descricao=f'Comanda #{c.codigo}' + (f' – {c.nome_cliente}' if c.nome_cliente else ''),
                        valor=saldo_dev,
                        vencimento=c.data,
                        cliente_id=c.cliente_id,
                        comanda_id=c.id,
                    ))
        else:
            for cr in tq(ContaReceber).filter_by(comanda_id=c.id, status='pendente').all():
                cr.status = 'cancelado'
    else:
        for cr in tq(ContaReceber).filter_by(comanda_id=c.id, status='pendente').all():
            cr.status = 'cancelado'


def _save_comanda(c):
    from datetime import date
    data_str = request.form.get('data', '').strip()
    if not data_str:
        flash('Data é obrigatória.', 'error')
        return False
    try:
        c.data = date.fromisoformat(data_str)
    except ValueError:
        flash('Data inválida.', 'error')
        return False
    c.nome_cliente    = request.form.get('nome_cliente', '').strip() or None
    c.observacoes     = request.form.get('observacoes', '').strip() or None
    c.status          = request.form.get('status', 'aberta')
    cid = request.form.get('cliente_id', '')
    uid = request.form.get('unidade_id', '')
    pid = request.form.get('profissional_id', '')
    c.cliente_id      = int(cid) if cid else None
    c.unidade_id      = int(uid) if uid else None
    c.profissional_id = int(pid) if pid else None
    desc = request.form.get('desconto', '0').strip().replace(',', '.')
    try:
        from decimal import Decimal
        c.desconto = Decimal(desc)
    except Exception:
        c.desconto = 0

    # Itens: rebuild completo
    descs   = request.form.getlist('item_descricao')
    valors  = request.form.getlist('item_valor')
    qtds    = request.form.getlist('item_quantidade')
    svcs    = request.form.getlist('item_servico_id')
    vpitems = request.form.getlist('item_venda_pacote_item_id')
    profs_i    = request.form.getlist('item_profissional_id')
    comissoes_v = request.form.getlist('item_comissao_valor')
    comissoes_t = request.form.getlist('item_comissao_tipo')

    # Rastrear quais venda_pacote_item_ids já estavam na comanda (para não decrementar duplicado)
    ids_antes = {i.venda_pacote_item_id for i in c.itens if i.venda_pacote_item_id}
    c.itens.clear()

    ids_depois = set()
    novos_itens = []
    for i, desc_i in enumerate(descs):
        desc_i = desc_i.strip()
        if not desc_i:
            continue
        try:
            from decimal import Decimal as D
            val    = D(valors[i].strip().replace(',', '.')) if i < len(valors) else D('0')
            qtd    = int(qtds[i]) if i < len(qtds) and qtds[i] else 1
            svc_id = int(svcs[i]) if i < len(svcs) and svcs[i] else None
            vp_id  = int(vpitems[i]) if i < len(vpitems) and vpitems[i] else None
            prof_id  = int(profs_i[i]) if i < len(profs_i) and profs_i[i] else None
            com_v_s  = comissoes_v[i].strip().replace(',', '.') if i < len(comissoes_v) else ''
            com_v    = D(com_v_s) if com_v_s else None
            com_t    = comissoes_t[i] if i < len(comissoes_t) and comissoes_t[i] else '%'
        except Exception:
            continue
        if vp_id:
            ids_depois.add(vp_id)
        novos_itens.append(ComandaItem(
            descricao=desc_i, valor=val, quantidade=qtd,
            servico_id=svc_id, venda_pacote_item_id=vp_id, profissional_id=prof_id,
            comissao_valor=com_v, comissao_tipo=com_t))
    c.itens.extend(novos_itens)

    # Decrementar sessões para itens novos de pacote (não existiam antes)
    for vp_id in ids_depois - ids_antes:
        vpi = db.session.get(VendaPacoteItem, vp_id)
        if vpi and vpi.quantidade_usada < vpi.quantidade_total:
            vpi.quantidade_usada += 1
            if vpi.venda.sessoes_restantes <= 0:
                vpi.venda.status = 'concluido'

    # Restaurar sessões para itens de pacote removidos
    for vp_id in ids_antes - ids_depois:
        vpi = db.session.get(VendaPacoteItem, vp_id)
        if vpi and vpi.quantidade_usada > 0:
            vpi.quantidade_usada -= 1
            if vpi.venda.status == 'concluido':
                vpi.venda.status = 'ativo'

    from decimal import Decimal
    if c.status == 'fechada' and c.cliente_id:
        # Transferir saldo (positivo = dívida, negativo = crédito) para o cliente ao fechar
        novo_saldo_aj = c.saldo  # recalculado com novos itens e desconto
        old_saldo_aj  = c.saldo_ajustado if c.saldo_ajustado is not None else Decimal('0')
        delta = novo_saldo_aj - old_saldo_aj
        if delta != 0:
            cl = c.cliente or db.session.get(Cliente, c.cliente_id)
            if cl:
                cl.saldo = (cl.saldo or Decimal('0')) - delta
            c.saldo_ajustado = novo_saldo_aj
    elif c.status == 'aberta' and c.saldo_ajustado is not None and c.cliente_id:
        # Reverter transferência ao reabrir a comanda
        cl = c.cliente or db.session.get(Cliente, c.cliente_id)
        if cl:
            cl.saldo = (cl.saldo or Decimal('0')) + c.saldo_ajustado
        c.saldo_ajustado = None

    _sync_conta_receber(c)
    return True


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/autosave', methods=['POST'])
@login_required
def comanda_autosave(comanda_id):
    """Salva itens e campos da comanda silenciosamente (sem flash, retorna JSON)."""
    c = db.get_or_404(Comanda, comanda_id)
    try:
        if _save_comanda(c):
            db.session.commit()
        return jsonify({'ok': True, 'comanda': _comanda_to_json(c)})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(exc)})


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/pagamento', methods=['POST'])
@login_required
def comanda_pagamento_add(comanda_id):
    from datetime import date
    from decimal import Decimal
    c = db.get_or_404(Comanda, comanda_id)
    forma = request.form.get('forma_pagamento', '').strip()
    valor_s = request.form.get('valor', '').strip().replace(',', '.')
    parcelas = request.form.get('parcelas', '1')
    if not forma or not valor_s:
        flash('Informe forma e valor do pagamento.', 'error')
        return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
    try:
        valor = Decimal(valor_s)
        if valor <= 0:
            flash('Valor deve ser positivo.', 'error')
            return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))

        saldo_antes = c.saldo  # saldo antes deste pagamento

        # Pagamento via saldo do cliente: debitar imediatamente
        if forma == 'saldo_cliente':
            if not c.cliente_id:
                flash('Vincule um cliente à comanda antes de usar saldo.', 'error')
                return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
            saldo_disp = c.cliente.saldo or Decimal('0')
            if saldo_disp <= 0:
                flash('Cliente não possui crédito disponível.', 'error')
                return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
            if valor > saldo_disp:
                flash(f'Valor excede o crédito do cliente (R$ {saldo_disp:.2f}).', 'error')
                return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
            c.cliente.saldo = saldo_disp - valor

        p = PagamentoComanda(
            comanda_id=c.id, forma_pagamento=forma, valor=valor,
            parcelas=int(parcelas) if parcelas.isdigit() else 1,
            data_pagamento=date.today(),
        )
        db.session.add(p)

        # Auto-fechar e transferir saldo residual para conta do cliente
        saldo_restante = saldo_antes - valor
        if saldo_restante <= 0:
            _fechar_comanda(c, saldo_override=saldo_restante)

        db.session.commit()
        flash('Pagamento registrado.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Erro ao registrar pagamento: {exc}', 'error')
    return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/pagamento/<int:pag_id>/excluir', methods=['POST'])
@login_required
def comanda_pagamento_excluir(comanda_id, pag_id):
    from decimal import Decimal
    p = db.get_or_404(PagamentoComanda, pag_id)
    c = db.get_or_404(Comanda, comanda_id)

    # Reverter fechamento (desfaz ajuste de saldo do cliente)
    if c.status == 'fechada':
        _reabrir_comanda(c)

    # Devolver ao saldo do cliente se era pagamento via saldo
    if p.forma_pagamento == 'saldo_cliente' and c.cliente_id:
        c.cliente.saldo = (c.cliente.saldo or Decimal('0')) + p.valor

    db.session.delete(p)
    db.session.commit()
    flash('Pagamento removido.', 'success')
    return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/fechar', methods=['POST'])
@login_required
def comanda_fechar(comanda_id):
    c = db.get_or_404(Comanda, comanda_id)
    _fechar_comanda(c)
    db.session.commit()
    flash('Comanda fechada.', 'success')
    return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/excluir', methods=['POST'])
@login_required
def comanda_excluir(comanda_id):
    if not current_user.has_role('empresa_admin', 'saas_admin'):
        flash('Apenas administradores podem excluir comandas.', 'error')
        return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
    c = db.get_or_404(Comanda, comanda_id)

    # Reverter efeitos no saldo do cliente antes de excluir
    if c.cliente_id:
        from decimal import Decimal
        cl = c.cliente
        if cl:
            # Reverter saldo_ajustado (transferido ao fechar a comanda)
            if c.saldo_ajustado is not None:
                cl.saldo = (cl.saldo or Decimal('0')) + c.saldo_ajustado
            # Reembolsar pagamentos feitos com saldo do cliente
            for p in c.pagamentos:
                if p.forma_pagamento == 'saldo_cliente':
                    cl.saldo = (cl.saldo or Decimal('0')) + p.valor

    # Se a comanda é de venda de pacote, exclui a venda e desvincula as sessões
    venda = getattr(c, 'venda_pacote', None)
    if venda:
        for item in list(venda.itens):
            # Desvincula agendamentos que referenciam esta sessão do pacote
            for ag in list(item.agendamentos_sessao):
                ag.venda_pacote_item_id = None
            # Desvincula comanda_itens que referenciam esta sessão
            for ci in list(item.comanda_usos):
                ci.venda_pacote_item_id = None
        db.session.flush()
        db.session.delete(venda)
        db.session.flush()

    # Desvincula o agendamento antes de excluir (agendamento NÃO é excluído)
    c.agendamento_id = None
    db.session.flush()
    db.session.delete(c)
    db.session.commit()

    if venda:
        flash('Comanda e venda de pacote vinculada excluídas.', 'success')
    else:
        flash('Comanda excluída. O agendamento vinculado foi mantido.', 'success')
    return redirect(url_for('admin.financeiro_comandas'))


# ── Contas a Pagar ────────────────────────────────────────────────────────────

@admin_bp.route('/financeiro/contas-a-pagar', methods=['GET', 'POST'])
@login_required
def contas_pagar():
    from datetime import date as _date
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'nova':
            desc     = request.form.get('descricao', '').strip()
            valor_s  = request.form.get('valor', '').strip().replace(',', '.')
            venc_s   = request.form.get('vencimento', '').strip()
            categ    = request.form.get('categoria', '').strip() or None
            forn     = request.form.get('fornecedor', '').strip() or None
            obs      = request.form.get('observacoes', '').strip() or None
            if not desc or not valor_s or not venc_s:
                flash('Preencha descrição, valor e vencimento.', 'error')
            else:
                try:
                    from decimal import Decimal
                    db.session.add(ContaPagar(
                        descricao=desc, valor=Decimal(valor_s),
                        vencimento=_date.fromisoformat(venc_s),
                        categoria=categ, fornecedor=forn, observacoes=obs,
                    ))
                    db.session.commit()
                    flash('Conta a pagar criada.', 'success')
                except Exception:
                    db.session.rollback()
                    flash('Dados inválidos.', 'error')
        return redirect(url_for('admin.contas_pagar'))

    status_f  = request.args.get('status', '')
    dt_ini_s  = request.args.get('dt_ini', '')
    dt_fim_s  = request.args.get('dt_fim', '')
    q = tq(ContaPagar)
    if status_f:
        q = q.filter_by(status=status_f)
    if dt_ini_s:
        try:
            q = q.filter(ContaPagar.vencimento >= _date.fromisoformat(dt_ini_s))
        except ValueError:
            pass
    if dt_fim_s:
        try:
            q = q.filter(ContaPagar.vencimento <= _date.fromisoformat(dt_fim_s))
        except ValueError:
            pass
    contas = q.order_by(ContaPagar.vencimento.asc()).all()
    total_pendente = sum(cp.valor for cp in contas if cp.status == 'pendente')
    total_pago     = sum(cp.valor for cp in contas if cp.status == 'pago')
    return render_template('admin/contas_pagar.html', contas=contas,
                           status_f=status_f, dt_ini=dt_ini_s, dt_fim=dt_fim_s,
                           formas=FORMA_PAGAMENTO, hoje=_date.today().isoformat(),
                           total_pendente=total_pendente, total_pago=total_pago)


@admin_bp.route('/financeiro/contas-a-pagar/<int:conta_id>/pagar', methods=['POST'])
@login_required
def conta_pagar_baixa(conta_id):
    from datetime import date as _date
    cp = db.get_or_404(ContaPagar, conta_id)
    forma   = request.form.get('forma_pagamento', '').strip()
    data_s  = request.form.get('data_pagamento', _date.today().isoformat()).strip()
    if not forma:
        flash('Selecione a forma de pagamento.', 'error')
        return redirect(url_for('admin.contas_pagar'))
    try:
        cp.data_pagamento  = _date.fromisoformat(data_s)
    except ValueError:
        cp.data_pagamento  = _date.today()
    cp.status          = 'pago'
    cp.forma_pagamento = forma
    db.session.commit()
    flash('Pagamento registrado.', 'success')
    return redirect(url_for('admin.contas_pagar'))


@admin_bp.route('/financeiro/contas-a-pagar/<int:conta_id>/excluir', methods=['POST'])
@login_required
def conta_pagar_excluir(conta_id):
    cp = db.get_or_404(ContaPagar, conta_id)
    db.session.delete(cp)
    db.session.commit()
    flash('Conta excluída.', 'success')
    return redirect(url_for('admin.contas_pagar'))


# ── Contas a Receber ──────────────────────────────────────────────────────────

@admin_bp.route('/financeiro/contas-a-receber', methods=['GET', 'POST'])
@login_required
def contas_receber():
    from datetime import date as _date
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'nova':
            desc      = request.form.get('descricao', '').strip()
            valor_s   = request.form.get('valor', '').strip().replace(',', '.')
            venc_s    = request.form.get('vencimento', '').strip()
            cli_s     = request.form.get('cliente_id', '').strip()
            obs       = request.form.get('observacoes', '').strip() or None
            if not desc or not valor_s or not venc_s:
                flash('Preencha descrição, valor e vencimento.', 'error')
            else:
                try:
                    from decimal import Decimal
                    db.session.add(ContaReceber(
                        descricao=desc, valor=Decimal(valor_s),
                        vencimento=_date.fromisoformat(venc_s),
                        cliente_id=int(cli_s) if cli_s else None,
                        observacoes=obs,
                    ))
                    db.session.commit()
                    flash('Conta a receber criada.', 'success')
                except Exception:
                    db.session.rollback()
                    flash('Dados inválidos.', 'error')
        return redirect(url_for('admin.contas_receber'))

    status_f  = request.args.get('status', '')
    dt_ini_s  = request.args.get('dt_ini', '')
    dt_fim_s  = request.args.get('dt_fim', '')
    q = tq(ContaReceber)
    if status_f:
        q = q.filter_by(status=status_f)
    if dt_ini_s:
        try:
            q = q.filter(ContaReceber.vencimento >= _date.fromisoformat(dt_ini_s))
        except ValueError:
            pass
    if dt_fim_s:
        try:
            q = q.filter(ContaReceber.vencimento <= _date.fromisoformat(dt_fim_s))
        except ValueError:
            pass
    contas = q.order_by(ContaReceber.vencimento.asc()).all()
    total_pendente  = sum(cr.valor for cr in contas if cr.status == 'pendente')
    total_recebido  = sum(cr.valor for cr in contas if cr.status == 'recebido')
    clientes_list   = tq(Cliente).order_by(Cliente.nome).all()
    return render_template('admin/contas_receber.html', contas=contas,
                           status_f=status_f, dt_ini=dt_ini_s, dt_fim=dt_fim_s,
                           formas=FORMA_PAGAMENTO, hoje=_date.today().isoformat(),
                           total_pendente=total_pendente, total_recebido=total_recebido,
                           clientes_list=clientes_list)


@admin_bp.route('/financeiro/contas-a-receber/<int:conta_id>/receber', methods=['POST'])
@login_required
def conta_receber_baixa(conta_id):
    from datetime import date as _date
    from decimal import Decimal
    cr = db.get_or_404(ContaReceber, conta_id)
    forma  = request.form.get('forma_pagamento', '').strip()
    data_s = request.form.get('data_recebimento', _date.today().isoformat()).strip()
    if not forma:
        flash('Selecione a forma de pagamento.', 'error')
        return redirect(url_for('admin.contas_receber'))
    try:
        data_rec = _date.fromisoformat(data_s)
    except ValueError:
        data_rec = _date.today()

    cr.status          = 'recebido'
    cr.forma_pagamento = forma
    cr.data_recebimento = data_rec

    # If linked to a comanda, add payment and reconcile saldo
    if cr.comanda_id:
        comanda = db.session.get(Comanda, cr.comanda_id)
        if comanda:
            db.session.add(PagamentoComanda(
                comanda_id=comanda.id, forma_pagamento=forma,
                valor=cr.valor, parcelas=1, data_pagamento=data_rec,
            ))
            db.session.flush()
            if comanda.status == 'fechada' and comanda.cliente_id:
                old_aj  = comanda.saldo_ajustado if comanda.saldo_ajustado is not None else Decimal('0')
                novo_aj = comanda.saldo
                delta   = novo_aj - old_aj
                if delta != 0:
                    cl = comanda.cliente
                    if cl:
                        cl.saldo = (cl.saldo or Decimal('0')) - delta
                    comanda.saldo_ajustado = novo_aj

    db.session.commit()
    flash('Recebimento registrado com sucesso.', 'success')
    return redirect(url_for('admin.contas_receber'))


@admin_bp.route('/financeiro/contas-a-receber/<int:conta_id>/excluir', methods=['POST'])
@login_required
def conta_receber_excluir(conta_id):
    cr = db.get_or_404(ContaReceber, conta_id)
    db.session.delete(cr)
    db.session.commit()
    flash('Conta excluída.', 'success')
    return redirect(url_for('admin.contas_receber'))


# ── Onboarding / Boas-vindas ──────────────────────────────────────────────────

def _checklist_estado(empresa_id):
    """Retorna dict com o estado de cada item do checklist de configuração."""
    import os
    return {
        'profissionais': Profissional.query.filter_by(empresa_id=empresa_id, ativo=True).count() > 0,
        'expediente':    Expediente.query.filter_by(empresa_id=empresa_id).count() > 0,
        'servicos':      Servico.query.filter_by(empresa_id=empresa_id, ativo=True).count() > 0,
        'whatsapp':      bool(os.getenv('WHATSAPP_PHONE_NUMBER_ID')),
    }


@admin_bp.route('/boas-vindas')
@login_required
def boas_vindas():
    eid = g.get('empresa_id')
    checklist = _checklist_estado(eid) if eid else {}
    total     = len(checklist)
    feitos    = sum(checklist.values())
    return render_template('admin/boas_vindas.html',
                           checklist=checklist, feitos=feitos, total=total)


# ── Formas de Pagamento ────────────────────────────────────────────────────────

@admin_bp.route('/financeiro/formas-pagamento', methods=['GET', 'POST'])
@login_required
def formas_pagamento():
    from decimal import Decimal, InvalidOperation

    if request.method == 'POST':
        action    = request.form.get('action')
        forma_id  = request.form.get('id', '')

        def _dec(field, default='0'):
            try:
                return Decimal(request.form.get(field, default).strip().replace(',', '.') or default)
            except (InvalidOperation, AttributeError):
                return Decimal(default)

        def _int(field, default=0):
            try:
                return int(request.form.get(field, default))
            except (ValueError, TypeError):
                return default

        if action == 'save':
            codigo = request.form.get('codigo', '').strip()
            if not codigo or codigo not in dict(FORMA_PAGAMENTO):
                flash('Selecione uma forma de pagamento válida.', 'error')
                return redirect(url_for('admin.formas_pagamento'))

            dup = tq(FormaPagamento).filter(FormaPagamento.codigo == codigo)
            if forma_id:
                dup = dup.filter(FormaPagamento.id != int(forma_id))
            if dup.first():
                flash('Já existe uma configuração cadastrada para essa forma de pagamento.', 'error')
                return redirect(url_for('admin.formas_pagamento'))

            f = db.get_or_404(FormaPagamento, int(forma_id)) if forma_id else FormaPagamento()
            f.codigo               = codigo
            f.observacao           = request.form.get('observacao', '').strip() or None
            f.taxa_administracao   = _dec('taxa_administracao')
            f.taxa_fixa            = _dec('taxa_fixa')
            f.impostos             = _dec('impostos')
            f.juros_antecipacao    = _dec('juros_antecipacao')
            f.prazo_liberacao      = _int('prazo_liberacao', 0)
            f.permite_parcelamento = bool(request.form.get('permite_parcelamento'))
            f.max_parcelas         = _int('max_parcelas', 1)
            f.liberacao_automatica = bool(request.form.get('liberacao_automatica'))
            f.descontar_taxas      = bool(request.form.get('descontar_taxas'))
            f.controle_caixa       = bool(request.form.get('controle_caixa'))
            f.ativo                = bool(request.form.get('ativo'))
            f.updated_at           = datetime.utcnow()
            if not forma_id:
                db.session.add(f)
            db.session.commit()
            flash('Forma de pagamento salva.', 'success')

        elif action == 'delete' and forma_id:
            f = db.get_or_404(FormaPagamento, int(forma_id))
            db.session.delete(f)
            db.session.commit()
            flash('Forma de pagamento excluída.', 'success')

        elif action == 'toggle' and forma_id:
            f = db.get_or_404(FormaPagamento, int(forma_id))
            f.ativo = not f.ativo
            db.session.commit()

        return redirect(url_for('admin.formas_pagamento'))

    formas = tq(FormaPagamento).all()
    formas.sort(key=lambda f: f.nome)
    return render_template('admin/formas_pagamento.html', formas=formas, opcoes=FORMA_PAGAMENTO)


# ── Comissões ─────────────────────────────────────────────────────────────────

@admin_bp.route('/financeiro/comissoes', methods=['GET', 'POST'])
@login_required
def comissoes():
    from datetime import date as _date, timedelta
    import calendar as _cal
    from decimal import Decimal

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action in ('pagar', 'pagar_um'):
            ids  = request.form.getlist('item_ids') if action == 'pagar' else [request.form.get('item_id')]
            forma = request.form.get('forma_pagamento', 'dinheiro')
            data_s = request.form.get('data_pagamento', _date.today().isoformat())
            try:
                data_pag = _date.fromisoformat(data_s)
            except ValueError:
                data_pag = _date.today()
            for id_s in ids:
                if not id_s:
                    continue
                try:
                    item = db.session.get(ComandaItem, int(id_s))
                    if item:
                        item.comissao_paga      = True
                        item.comissao_data_pag  = data_pag
                        item.comissao_forma_pag = forma
                except Exception:
                    pass
            db.session.commit()
            flash('Comissões registradas como pagas.', 'success')
        return redirect(url_for('admin.comissoes',
                                periodo=request.args.get('periodo', 'mes'),
                                profissional_id=request.args.get('profissional_id', ''),
                                status=request.args.get('status', '')))

    # ── Filtros ──
    hoje      = _date.today()
    periodo   = request.args.get('periodo', 'mes')
    dt_ini_s  = request.args.get('dt_ini', '')
    dt_fim_s  = request.args.get('dt_fim', '')
    prof_id_s = request.args.get('profissional_id', '')
    status_f  = request.args.get('status', '')

    if periodo == 'hoje':
        dt_ini = dt_fim = hoje
    elif periodo == 'semana':
        dt_ini = hoje - timedelta(days=hoje.weekday())
        dt_fim = dt_ini + timedelta(days=6)
    elif periodo == 'custom':
        try:
            dt_ini = _date.fromisoformat(dt_ini_s) if dt_ini_s else hoje.replace(day=1)
        except ValueError:
            dt_ini = hoje.replace(day=1)
        try:
            dt_fim = _date.fromisoformat(dt_fim_s) if dt_fim_s else hoje
        except ValueError:
            dt_fim = hoje
    else:  # mes
        dt_ini = hoje.replace(day=1)
        dt_fim = hoje.replace(day=_cal.monthrange(hoje.year, hoje.month)[1])

    _eid_c = g.get('empresa_id')
    q = (tq(ComandaItem)
         .join(Comanda, Comanda.id == ComandaItem.comanda_id)
         .filter(
             Comanda.status == 'fechada',
             Comanda.data >= dt_ini,
             Comanda.data <= dt_fim,
             ComandaItem.comissao_valor.isnot(None),
             ComandaItem.comissao_valor != 0,
             *((Comanda.empresa_id == _eid_c,) if _eid_c else ()),
         ))

    if prof_id_s:
        try:
            q = q.filter(ComandaItem.profissional_id == int(prof_id_s))
        except ValueError:
            pass

    if status_f == 'pendente':
        q = q.filter(db.or_(ComandaItem.comissao_paga.is_(None),
                             ComandaItem.comissao_paga == False))
    elif status_f == 'pago':
        q = q.filter(ComandaItem.comissao_paga == True)

    items = q.order_by(Comanda.data.desc()).all()

    total_com      = sum(i.comissao_calculada for i in items) or Decimal('0')
    total_pago_com = sum(i.comissao_calculada for i in items if i.comissao_paga) or Decimal('0')
    total_pend     = total_com - total_pago_com

    profs = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()

    return render_template('admin/comissoes.html',
        items=items, profs=profs, formas=FORMA_PAGAMENTO,
        periodo=periodo, dt_ini=dt_ini.isoformat(), dt_fim=dt_fim.isoformat(),
        dt_ini_s=dt_ini_s, dt_fim_s=dt_fim_s,
        prof_id=prof_id_s, status_f=status_f,
        hoje=hoje.isoformat(),
        total_com=total_com, total_pago_com=total_pago_com, total_pend=total_pend)


@admin_bp.route('/relatorios/comissoes')
@login_required
def relatorio_comissoes():
    from datetime import date as _date
    import calendar as _cal
    from decimal import Decimal

    hoje = _date.today()
    dt_ini_s     = request.args.get('dt_ini', '')
    dt_fim_s     = request.args.get('dt_fim', '')
    unidade_id_s = request.args.get('unidade_id', '')
    prof_id_s    = request.args.get('profissional_id', '')

    try:
        dt_ini = _date.fromisoformat(dt_ini_s) if dt_ini_s else hoje.replace(day=1)
    except ValueError:
        dt_ini = hoje.replace(day=1)
    try:
        dt_fim = _date.fromisoformat(dt_fim_s) if dt_fim_s else hoje.replace(day=_cal.monthrange(hoje.year, hoje.month)[1])
    except ValueError:
        dt_fim = hoje.replace(day=_cal.monthrange(hoje.year, hoje.month)[1])

    unidade_id = int(unidade_id_s) if unidade_id_s.isdigit() else None
    prof_id    = int(prof_id_s) if (prof_id_s.isdigit() and unidade_id) else None

    _eid_c = g.get('empresa_id')

    def _base_query():
        return (tq(ComandaItem)
                .join(Comanda, Comanda.id == ComandaItem.comanda_id)
                .filter(
                    Comanda.status == 'fechada',
                    Comanda.data >= dt_ini,
                    Comanda.data <= dt_fim,
                    ComandaItem.comissao_valor.isnot(None),
                    ComandaItem.comissao_valor != 0,
                    *((Comanda.empresa_id == _eid_c,) if _eid_c else ()),
                ))

    q = _base_query()
    if unidade_id:
        q = q.filter(Comanda.unidade_id == unidade_id)
    if prof_id:
        q = q.filter(ComandaItem.profissional_id == prof_id)
    items = q.all()

    profissionais_disponiveis = []
    if unidade_id:
        profissionais_disponiveis = (tq(Profissional)
                                     .filter_by(unidade_id=unidade_id, ativo=True)
                                     .order_by(Profissional.nome).all())

    unidades = tq(Unidade).filter_by(ativo=True).order_by(Unidade.nome).all()

    # ── Agregação: unidade -> profissional -> serviço ──
    def _novo_leaf():
        return {'nome': '', 'quantidade': 0, 'valor_total_servico': Decimal('0'),
                'valor_total_comissao': Decimal('0'), 'comissao_paga': Decimal('0'),
                'comissao_pendente': Decimal('0'), 'tipos': set()}

    grupos = defaultdict(lambda: defaultdict(lambda: defaultdict(_novo_leaf)))
    unidade_nomes = {}
    profissional_nomes = {}

    for item in items:
        u_id = item.comanda.unidade_id
        p_id = item.profissional_id
        s_key = item.servico_id if item.servico_id else ('desc', item.descricao)
        nome_servico = item.servico.nome if item.servico else item.descricao

        unidade_nomes.setdefault(u_id, item.comanda.unidade.label() if item.comanda.unidade else 'Sem unidade')
        profissional_nomes.setdefault(p_id, item.profissional.nome if item.profissional else 'Sem profissional')

        leaf = grupos[u_id][p_id][s_key]
        leaf['nome'] = nome_servico
        leaf['quantidade'] += item.quantidade or 1
        leaf['valor_total_servico'] += (item.valor or 0) * (item.quantidade or 1)
        comissao = item.comissao_calculada
        leaf['valor_total_comissao'] += comissao
        if item.comissao_paga:
            leaf['comissao_paga'] += comissao
        else:
            leaf['comissao_pendente'] += comissao
        leaf['tipos'].add((item.comissao_tipo, item.comissao_valor))

    def _pct_label(tipos, valor_total_servico, valor_total_comissao):
        tipos_grupo = {t for t, _ in tipos}
        if tipos_grupo == {'R'}:
            return 'R$ fixo'
        if tipos_grupo == {'%'}:
            if len(tipos) == 1:
                (_, v), = tipos
                return f"{v:.2f}".replace('.', ',') + '%'
            if valor_total_servico:
                pct = (valor_total_comissao / valor_total_servico) * 100
                return f"{pct:.2f}".replace('.', ',') + '%'
            return '—'
        return 'misto'

    def _somar(filhos):
        out = {'valor_total_servico': Decimal('0'), 'valor_total_comissao': Decimal('0'),
               'comissao_paga': Decimal('0'), 'comissao_pendente': Decimal('0')}
        for f in filhos:
            out['valor_total_servico']  += f['valor_total_servico']
            out['valor_total_comissao'] += f['valor_total_comissao']
            out['comissao_paga']        += f['comissao_paga']
            out['comissao_pendente']    += f['comissao_pendente']
        return out

    relatorio = []
    for u_id in sorted(grupos.keys(), key=lambda k: unidade_nomes[k].lower()):
        profissionais = []
        for p_id in sorted(grupos[u_id].keys(), key=lambda k: profissional_nomes[k].lower()):
            servicos = []
            for s_key in sorted(grupos[u_id][p_id].keys(), key=lambda k: grupos[u_id][p_id][k]['nome'].lower()):
                s = grupos[u_id][p_id][s_key]
                servicos.append({
                    'nome': s['nome'],
                    'valor_unitario': (s['valor_total_servico'] / s['quantidade']) if s['quantidade'] else Decimal('0'),
                    'pct_label': _pct_label(s['tipos'], s['valor_total_servico'], s['valor_total_comissao']),
                    'valor_total_servico': s['valor_total_servico'],
                    'valor_total_comissao': s['valor_total_comissao'],
                    'comissao_paga': s['comissao_paga'],
                    'comissao_pendente': s['comissao_pendente'],
                })
            subtotal_prof = _somar(servicos)
            profissionais.append({'id': p_id, 'nome': profissional_nomes[p_id],
                                  'servicos': servicos, 'subtotal': subtotal_prof})
        subtotal_unidade = _somar([p['subtotal'] for p in profissionais])
        relatorio.append({'id': u_id, 'nome': unidade_nomes[u_id],
                          'profissionais': profissionais, 'subtotal': subtotal_unidade})

    total_geral = _somar([u['subtotal'] for u in relatorio])

    return render_template('admin/relatorio_comissoes.html',
        relatorio=relatorio, total_geral=total_geral,
        unidades=unidades, profissionais_disponiveis=profissionais_disponiveis,
        unidade_id=unidade_id, prof_id=prof_id,
        dt_ini=dt_ini.isoformat(), dt_fim=dt_fim.isoformat())


# ── API JSON — modal de comanda na agenda ─────────────────────────────────────

def _comanda_to_json(c):
    return {
        'id': c.id,
        'codigo': c.codigo,
        'data': c.data.isoformat(),
        'nome_cliente': c.nome_cliente or '',
        'cliente_id': c.cliente_id,
        'cliente_saldo': float(c.cliente.saldo or 0) if c.cliente else 0,
        'cliente_nome': c.cliente.nome if c.cliente else '',
        'profissional_id': c.profissional_id,
        'profissional_nome': c.profissional.nome if c.profissional else '',
        'desconto': float(c.desconto or 0),
        'observacoes': c.observacoes or '',
        'status': c.status,
        'valor_total': float(c.valor_total),
        'valor_pago': float(c.valor_pago),
        'saldo': float(c.saldo),
        'saldo_ajustado': float(c.saldo_ajustado) if c.saldo_ajustado is not None else None,
        'itens': [
            {'id': i.id, 'descricao': i.descricao, 'valor': float(i.valor),
             'quantidade': i.quantidade, 'servico_id': i.servico_id,
             'venda_pacote_item_id': i.venda_pacote_item_id,
             'profissional_id': i.profissional_id or '',
             'profissional_nome': i.profissional.nome if i.profissional else '',
             'comissao_valor': float(i.comissao_valor) if i.comissao_valor is not None else None,
             'comissao_tipo': i.comissao_tipo or '%'}
            for i in c.itens
        ],
        'pagamentos': [
            {'id': p.id, 'forma_pagamento': p.forma_pagamento,
             'forma_label': dict(FORMA_PAGAMENTO).get(p.forma_pagamento, p.forma_pagamento),
             'valor': float(p.valor), 'parcelas': p.parcelas or 1,
             'data_pagamento': p.data_pagamento.isoformat() if p.data_pagamento else None}
            for p in c.pagamentos
        ],
    }


@admin_bp.route('/api/ag/<int:ag_id>/comanda', methods=['POST'])
@login_required
def api_ag_comanda(ag_id):
    from decimal import Decimal
    a = db.get_or_404(Agendamento, ag_id)
    if a.comanda:
        return jsonify(_comanda_to_json(a.comanda))
    # Tenta auto-vincular cliente pelo telefone quando agendamento não tem cliente_id
    cliente_id = a.cliente_id
    if not cliente_id and a.telefone:
        digits = ''.join(ch for ch in a.telefone if ch.isdigit())
        if len(digits) >= 8:
            cl_match = tq(Cliente).filter(
                Cliente.telefone.like(f'%{digits[-8:]}')
            ).first()
            if cl_match:
                cliente_id = cl_match.id
                a.cliente_id = cl_match.id  # salva no agendamento também
    c = Comanda(
        codigo=_next_codigo(), data=a.data,
        cliente_id=cliente_id, nome_cliente=a.nome_cliente,
        agendamento_id=a.id, profissional_id=a.profissional_id,
        unidade_id=a.unidade_id, status='aberta',
    )
    db.session.add(c)
    db.session.flush()
    _add_servicos_agendamento_comanda(c, a)
    db.session.commit()
    return jsonify(_comanda_to_json(c))


@admin_bp.route('/api/comanda/<int:comanda_id>/pag-add', methods=['POST'])
@login_required
def api_comanda_pag_add(comanda_id):
    from datetime import date as _date
    from decimal import Decimal
    c = db.get_or_404(Comanda, comanda_id)
    pl = request.get_json(silent=True) or {}
    forma = pl.get('forma_pagamento', '').strip()
    try:
        valor = Decimal(str(pl.get('valor', '0')).replace(',', '.'))
    except Exception:
        return jsonify({'ok': False, 'error': 'Valor inválido.'})
    if not forma:
        return jsonify({'ok': False, 'error': 'Selecione a forma de pagamento.'})
    if valor <= 0:
        return jsonify({'ok': False, 'error': 'Valor deve ser positivo.'})
    saldo_antes = c.saldo
    if forma == 'saldo_cliente':
        if not c.cliente_id:
            return jsonify({'ok': False, 'error': 'Vincule um cliente à comanda antes de usar saldo.'})
        saldo_disp = c.cliente.saldo or Decimal('0')
        if saldo_disp <= 0:
            return jsonify({'ok': False, 'error': 'Cliente não possui crédito disponível.'})
        if valor > saldo_disp:
            return jsonify({'ok': False, 'error': f'Valor excede o crédito do cliente (R$ {saldo_disp:.2f}).'})
        c.cliente.saldo = saldo_disp - valor
    p = PagamentoComanda(
        comanda_id=c.id, forma_pagamento=forma, valor=valor,
        parcelas=int(pl.get('parcelas', 1) or 1), data_pagamento=_date.today(),
    )
    db.session.add(p)
    # Não fecha automaticamente: o fechamento (e transferência de saldo/crédito ao cliente)
    # ocorre apenas quando o usuário salva explicitamente com status "fechada".
    db.session.commit()
    return jsonify({'ok': True, 'comanda': _comanda_to_json(c)})


@admin_bp.route('/api/comanda/<int:comanda_id>/pag-del/<int:pag_id>', methods=['POST'])
@login_required
def api_comanda_pag_del(comanda_id, pag_id):
    from decimal import Decimal
    c = db.get_or_404(Comanda, comanda_id)
    p = db.get_or_404(PagamentoComanda, pag_id)
    if p.comanda_id != comanda_id:
        return jsonify({'ok': False, 'error': 'Pagamento não pertence a esta comanda.'}), 400
    if c.status == 'fechada':
        _reabrir_comanda(c)
    if p.forma_pagamento == 'saldo_cliente' and c.cliente_id:
        c.cliente.saldo = (c.cliente.saldo or Decimal('0')) + p.valor
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True, 'comanda': _comanda_to_json(c)})


@admin_bp.route('/api/categorias/<int:cat_id>/profissionais')
@login_required
def api_cat_profissionais(cat_id):
    profs = tq(Profissional).filter_by(categoria_id=cat_id, ativo=True).order_by(Profissional.nome).all()
    return jsonify([{'id': p.id, 'nome': p.nome} for p in profs])


# ── Pacotes ───────────────────────────────────────────────────────────────────

@admin_bp.route('/servicos/pacotes')
@login_required
def pacotes():
    todos = tq(Pacote).order_by(Pacote.nome).all()
    servicos = tq(Servico).filter_by(ativo=True).order_by(Servico.nome).all()
    return render_template('admin/pacotes.html', pacotes=todos, servicos=servicos)


@admin_bp.route('/api/pacotes', methods=['POST'])
@login_required
def api_pacote_criar():
    from decimal import Decimal, InvalidOperation
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    if not nome:
        return jsonify({'ok': False, 'erro': 'Nome obrigatório'}), 400

    pacote = Pacote(nome=nome, descricao=(data.get('descricao') or '').strip() or None)
    itens = data.get('itens') or []
    if not itens:
        return jsonify({'ok': False, 'erro': 'Adicione pelo menos um serviço'}), 400

    for it in itens:
        try:
            svc_id = int(it['servico_id'])
            qtd    = max(1, int(it.get('quantidade', 1)))
            val    = Decimal(str(it.get('valor_unitario', 0)).replace(',', '.'))
        except (KeyError, ValueError, InvalidOperation):
            return jsonify({'ok': False, 'erro': 'Dados de item inválidos'}), 400
        svc = db.session.get(Servico, svc_id)
        if not svc:
            return jsonify({'ok': False, 'erro': f'Serviço {svc_id} não encontrado'}), 400
        pacote.itens.append(PacoteItem(servico_id=svc_id, quantidade=qtd, valor_unitario=val))

    db.session.add(pacote)
    db.session.commit()
    return jsonify({'ok': True, 'id': pacote.id, 'valor_total': float(pacote.valor_total)})


@admin_bp.route('/api/pacotes/<int:pacote_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_pacote_detalhe(pacote_id):
    from decimal import Decimal, InvalidOperation
    p = db.get_or_404(Pacote, pacote_id)

    if request.method == 'GET':
        return jsonify({
            'id': p.id, 'nome': p.nome, 'descricao': p.descricao or '',
            'ativo': p.ativo,
            'valor_total': float(p.valor_total),
            'itens': [{'id': i.id, 'servico_id': i.servico_id,
                       'servico_nome': i.servico.nome,
                       'quantidade': i.quantidade,
                       'valor_unitario': float(i.valor_unitario)} for i in p.itens],
        })

    if request.method == 'DELETE':
        if p.vendas:
            return jsonify({'ok': False, 'erro': 'Pacote possui vendas e não pode ser excluído'}), 400
        db.session.delete(p)
        db.session.commit()
        return jsonify({'ok': True})

    # PUT — atualizar
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    if not nome:
        return jsonify({'ok': False, 'erro': 'Nome obrigatório'}), 400
    p.nome     = nome
    p.descricao = (data.get('descricao') or '').strip() or None
    p.ativo    = bool(data.get('ativo', True))

    itens = data.get('itens') or []
    if not itens:
        return jsonify({'ok': False, 'erro': 'Adicione pelo menos um serviço'}), 400

    p.itens.clear()
    for it in itens:
        try:
            svc_id = int(it['servico_id'])
            qtd    = max(1, int(it.get('quantidade', 1)))
            val    = Decimal(str(it.get('valor_unitario', 0)).replace(',', '.'))
        except (KeyError, ValueError, InvalidOperation):
            return jsonify({'ok': False, 'erro': 'Dados de item inválidos'}), 400
        p.itens.append(PacoteItem(servico_id=svc_id, quantidade=qtd, valor_unitario=val))

    db.session.commit()
    return jsonify({'ok': True, 'valor_total': float(p.valor_total)})


@admin_bp.route('/api/servicos/<int:servico_id>/preco')
@login_required
def api_servico_preco(servico_id):
    s = db.get_or_404(Servico, servico_id)
    return jsonify({'preco': float(s.preco) if s.preco else 0})


# ── Vendas de Pacote ─────────────────────────────────────────────────────────

@admin_bp.route('/financeiro/vendas-pacote')
@login_required
def vendas_pacote():
    q     = request.args.get('q', '').strip()
    query = tq(VendaPacote)
    if q:
        like  = f'%{q}%'
        query = query.join(VendaPacote.cliente, isouter=True).filter(
            db.or_(VendaPacote.nome_cliente.ilike(like), Cliente.nome.ilike(like),
                   VendaPacote.nome_pacote.ilike(like)))
    vendas = query.order_by(VendaPacote.data_venda.desc()).all()
    return render_template('admin/vendas_pacote.html', vendas=vendas, q=q)


@admin_bp.route('/financeiro/vendas-pacote/nova', methods=['GET', 'POST'])
@login_required
def venda_pacote_nova():
    from datetime import date
    from decimal import Decimal

    pacotes_obj = tq(Pacote).filter_by(ativo=True).order_by(Pacote.nome).all()
    profs       = tq(Profissional).filter_by(ativo=True).order_by(Profissional.nome).all()
    unidades    = tq(Unidade).filter_by(ativo=True).order_by(Unidade.nome).all()
    hoje        = date.today()

    # Serializar pacotes para JSON seguro no template
    pacotes_json = {
        p.id: {
            'nome':        p.nome,
            'valor_total': float(p.valor_total),
            'itens': [{
                'id':            it.id,
                'servico_id':    it.servico_id,
                'servico_nome':  it.servico.nome,
                'quantidade':    it.quantidade,
                'valor_unitario': float(it.valor_unitario),
            } for it in p.itens],
        }
        for p in pacotes_obj
    }

    if request.method == 'POST':
        pacote_id  = request.form.get('pacote_id', '')
        cliente_id = request.form.get('cliente_id', '')
        nome_cli   = request.form.get('nome_cliente', '').strip()
        data_str   = request.form.get('data_venda', '').strip()
        prof_id    = request.form.get('profissional_id', '')
        unid_id    = request.form.get('unidade_id', '')

        if not pacote_id:
            flash('Selecione um pacote.', 'error')
            return render_template('admin/venda_pacote_form.html',
                                   pacotes=pacotes_obj, pacotes_json=pacotes_json,
                                   profs=profs, unidades=unidades, hoje=hoje.isoformat(),
                                   formas=FORMA_PAGAMENTO)

        pacote = db.get_or_404(Pacote, int(pacote_id))
        try:
            data_venda = date.fromisoformat(data_str) if data_str else hoje
        except ValueError:
            data_venda = hoje

        # Ler valor customizado do pacote (pode ser ajustado na venda)
        valor_venda_str = request.form.get('valor_total', '').strip().replace(',', '.')
        try:
            valor_venda = Decimal(valor_venda_str) if valor_venda_str else pacote.valor_total
        except Exception:
            valor_venda = pacote.valor_total

        # Criar comanda para o pagamento do pacote
        comanda = Comanda(
            codigo       = _next_codigo(),
            data         = data_venda,
            nome_cliente = nome_cli or None,
            cliente_id   = int(cliente_id) if cliente_id else None,
            profissional_id = int(prof_id) if prof_id else None,
            unidade_id   = int(unid_id) if unid_id else None,
            observacoes  = f'Venda de pacote: {pacote.nome}',
            status       = 'aberta',
        )
        comanda.itens.append(ComandaItem(
            descricao  = f'Pacote: {pacote.nome}',
            valor      = valor_venda,
            quantidade = 1,
        ))
        db.session.add(comanda)
        db.session.flush()

        # Criar VendaPacote
        venda = VendaPacote(
            pacote_id    = pacote.id,
            cliente_id   = int(cliente_id) if cliente_id else None,
            nome_cliente = nome_cli or None,
            comanda_id   = comanda.id,
            data_venda   = data_venda,
            nome_pacote  = pacote.nome,
            valor_total  = valor_venda,
            status       = 'ativo',
        )

        # Ler quantidades customizadas por item do formulário
        for item in pacote.itens:
            qtd_key = f'qtd_item_{item.id}'
            try:
                qtd = max(1, int(request.form.get(qtd_key, item.quantidade)))
            except ValueError:
                qtd = item.quantidade
            venda.itens.append(VendaPacoteItem(
                pacote_item_id   = item.id,
                servico_id       = item.servico_id,
                descricao        = item.servico.nome,
                quantidade_total = qtd,
                quantidade_usada = 0,
            ))

        db.session.add(venda)

        # Registrar pagamentos informados no formulário
        formas_vals   = request.form.getlist('pagamento_forma[]')
        valores_vals  = request.form.getlist('pagamento_valor[]')
        parcelas_vals = request.form.getlist('pagamento_parcelas[]')
        total_pago = Decimal('0')
        for forma, valor_str, parc_str in zip(formas_vals, valores_vals, parcelas_vals):
            forma = forma.strip()
            if not forma:
                continue
            try:
                v = Decimal(valor_str.replace(',', '.'))
            except Exception:
                continue
            if v <= 0:
                continue
            try:
                parc = max(1, int(parc_str))
            except (ValueError, TypeError):
                parc = 1
            comanda.pagamentos.append(PagamentoComanda(
                forma_pagamento = forma,
                valor           = v,
                parcelas        = parc,
                data_pagamento  = data_venda,
            ))
            total_pago += v

        # Validação servidor: pelo menos um pagamento obrigatório
        if total_pago <= 0:
            flash('Informe ao menos uma forma de pagamento antes de registrar a venda.', 'error')
            return render_template('admin/venda_pacote_form.html',
                                   pacotes=pacotes_obj, pacotes_json=pacotes_json,
                                   profs=profs, unidades=unidades, hoje=hoje.isoformat(),
                                   formas=FORMA_PAGAMENTO)

        # Fecha a comanda e aplica diferença no saldo da cliente
        # (excesso → crédito; déficit → dívida), replicando o comportamento de _fechar_comanda
        _fechar_comanda(comanda)

        db.session.commit()

        saldo_diff = valor_venda - total_pago
        if saldo_diff > 0:
            flash(f'Pacote "{pacote.nome}" vendido! Saldo devedor de R$ {saldo_diff:.2f} registrado para a cliente.', 'success')
        elif saldo_diff < 0:
            flash(f'Pacote "{pacote.nome}" vendido! Crédito de R$ {abs(saldo_diff):.2f} adicionado à carteira da cliente.', 'success')
        else:
            flash(f'Pacote "{pacote.nome}" vendido e pago integralmente!', 'success')
        return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda.id))

    return render_template('admin/venda_pacote_form.html',
                           pacotes=pacotes_obj, pacotes_json=pacotes_json,
                           profs=profs, unidades=unidades, hoje=hoje.isoformat(),
                           formas=FORMA_PAGAMENTO)


@admin_bp.route('/financeiro/vendas-pacote/<int:venda_id>')
@login_required
def venda_pacote_detalhe(venda_id):
    v = db.get_or_404(VendaPacote, venda_id)
    return render_template('admin/venda_pacote_detalhe.html', v=v)


@admin_bp.route('/financeiro/vendas-pacote/<int:venda_id>/itens/<int:item_id>/usar', methods=['POST'])
@login_required
def venda_pacote_usar_sessao(venda_id, item_id):
    venda = db.get_or_404(VendaPacote, venda_id)
    item  = db.get_or_404(VendaPacoteItem, item_id)
    if item.venda_pacote_id != venda_id:
        return jsonify({'ok': False, 'erro': 'Item não pertence à venda'}), 400
    qtd = int(request.form.get('quantidade', 1))
    if item.quantidade_usada + qtd > item.quantidade_total:
        flash('Quantidade excede as sessões disponíveis.', 'error')
        return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))
    item.quantidade_usada += qtd
    # Atualizar status da venda se todas sessões foram usadas
    if venda.sessoes_restantes - qtd <= 0:
        venda.status = 'concluido'
    db.session.commit()
    flash('Sessão registrada com sucesso.', 'success')
    return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))


@admin_bp.route('/financeiro/vendas-pacote/<int:venda_id>/cancelar', methods=['POST'])
@login_required
def venda_pacote_cancelar(venda_id):
    v = db.get_or_404(VendaPacote, venda_id)
    v.status = 'cancelado'
    db.session.commit()
    flash('Venda de pacote cancelada.', 'success')
    return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))


@admin_bp.route('/api/clientes/busca')
@login_required
def api_clientes_busca():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    clientes = (tq(Cliente)
                .filter(Cliente.nome.ilike(f'%{q}%'), Cliente.bloqueado == False)
                .order_by(Cliente.nome)
                .limit(10).all())
    return jsonify([{'id': c.id, 'nome': c.nome, 'telefone': c.telefone or ''} for c in clientes])


@admin_bp.route('/api/clientes/<int:cliente_id>/pacotes-ativos')
@login_required
def api_cliente_pacotes_ativos(cliente_id):
    vendas = tq(VendaPacote).filter_by(cliente_id=cliente_id, status='ativo').all()
    result = []
    for v in vendas:
        for item in v.itens:
            # Sessões já agendadas (não canceladas/faltou) mas ainda não concluídas via comanda
            agendadas = (tq(Agendamento)
                .filter_by(venda_pacote_item_id=item.id)
                .filter(Agendamento.status.in_(['agendado', 'confirmado']))
                .count())
            disponivel = item.quantidade_restante - agendadas
            if disponivel <= 0:
                continue
            dur_min = 60
            if item.servico:
                dur_min = (item.servico.duracao_horas or 1) * 60 + (item.servico.duracao_minutos or 0)
            result.append({
                'venda_pacote_item_id': item.id,
                'servico_id':          item.servico_id,
                'pacote_nome':         v.nome_pacote,
                'total':               item.quantidade_total,
                'usadas':              item.quantidade_usada,
                'agendadas':           agendadas,
                'disponivel':          disponivel,
                'dur_min':             dur_min,
            })
    return jsonify(result)


# ── Clientes ──────────────────────────────────────────────────────────────────

_CLIENTES_PER_PAGE_OPTIONS = [50, 100, 150, 200, 300, 500, 1000, 5000]
_CLIENTES_SORT_COLS = {
    'nome':       Cliente.nome,
    'telefone':   Cliente.telefone,
    'aniversario':Cliente.aniversario,
    'cidade':     Cliente.cidade,
    'created_at': Cliente.created_at,
}

@admin_bp.route('/clientes')
@login_required
def clientes():
    q         = request.args.get('q', '').strip()
    q_field   = request.args.get('q_field', 'todos')
    bloqueado = request.args.get('bloqueado', '')
    sort      = request.args.get('sort', 'nome')
    order     = request.args.get('order', 'asc')
    try:
        per_page = int(request.args.get('per_page', 50))
    except (ValueError, TypeError):
        per_page = 50
    if per_page not in _CLIENTES_PER_PAGE_OPTIONS:
        per_page = 50
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    query = tq(Cliente)
    if q:
        like = f'%{q}%'
        if q_field == 'nome':
            query = query.filter(Cliente.nome.ilike(like))
        elif q_field == 'telefone':
            query = query.filter(Cliente.telefone.ilike(like))
        elif q_field == 'email':
            query = query.filter(Cliente.email.ilike(like))
        elif q_field == 'cidade':
            query = query.filter(Cliente.cidade.ilike(like))
        else:
            query = query.filter(db.or_(
                Cliente.nome.ilike(like),
                Cliente.telefone.ilike(like),
                Cliente.email.ilike(like),
                Cliente.cidade.ilike(like),
            ))
    if bloqueado == '1':
        query = query.filter_by(bloqueado=True)
    elif bloqueado == '0':
        query = query.filter_by(bloqueado=False)

    sort_col = _CLIENTES_SORT_COLS.get(sort, Cliente.nome)
    sort_col = sort_col.desc() if order == 'desc' else sort_col.asc()

    pagination = query.order_by(sort_col).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('admin/clientes.html',
        clientes=pagination.items,
        pagination=pagination,
        q=q, q_field=q_field,
        bloqueado=bloqueado,
        sort=sort, order=order,
        per_page=per_page,
        per_page_options=_CLIENTES_PER_PAGE_OPTIONS,
    )


@admin_bp.route('/clientes/excluir-em-lote', methods=['POST'])
@login_required
def clientes_excluir_em_lote():
    ids_raw = request.form.get('ids', '')
    ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
    if ids:
        tq(Cliente).filter(Cliente.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f'{len(ids)} cliente(s) excluído(s).', 'success')
    return redirect(url_for('admin.clientes'))


_MESES = {
    1:'Janeiro', 2:'Fevereiro', 3:'Março',    4:'Abril',
    5:'Maio',    6:'Junho',     7:'Julho',     8:'Agosto',
    9:'Setembro',10:'Outubro',  11:'Novembro', 12:'Dezembro',
}


def _query_aniversariantes(periodo, mes_param):
    from datetime import date, timedelta
    today    = date.today()
    tomorrow = today + timedelta(days=1)
    base = tq(Cliente).filter(Cliente.aniversario.isnot(None), Cliente.bloqueado == False)
    if periodo == 'hoje':
        return base.filter(
            db.extract('month', Cliente.aniversario) == today.month,
            db.extract('day',   Cliente.aniversario) == today.day,
        ).order_by(Cliente.nome).all()
    if periodo == 'amanha':
        return base.filter(
            db.extract('month', Cliente.aniversario) == tomorrow.month,
            db.extract('day',   Cliente.aniversario) == tomorrow.day,
        ).order_by(Cliente.nome).all()
    if periodo == 'outro':
        try:
            m = int(mes_param); assert 1 <= m <= 12
        except Exception:
            m = today.month
        return base.filter(
            db.extract('month', Cliente.aniversario) == m,
        ).order_by(db.extract('day', Cliente.aniversario)).all()
    if periodo == 'todos':
        return base.order_by(
            db.extract('month', Cliente.aniversario),
            db.extract('day',   Cliente.aniversario),
        ).all()
    # default: mes
    return base.filter(
        db.extract('month', Cliente.aniversario) == today.month,
    ).order_by(db.extract('day', Cliente.aniversario)).all()


@admin_bp.route('/clientes/aniversariantes')
@login_required
def aniversariantes():
    from datetime import date
    today     = date.today()
    periodo   = request.args.get('periodo', 'mes')
    mes_param = request.args.get('mes', str(today.month))

    clientes_list = _query_aniversariantes(periodo, mes_param)

    titulo_map = {
        'hoje':   'Aniversariantes de Hoje',
        'amanha': 'Aniversariantes de Amanhã',
        'mes':    f'Aniversariantes de {_MESES[today.month]}',
        'todos':  'Todos os Aniversariantes',
    }
    if periodo == 'outro':
        try:
            m = int(mes_param); assert 1 <= m <= 12
        except Exception:
            m = today.month
        titulo = f'Aniversariantes de {_MESES[m]}'
    else:
        titulo = titulo_map.get(periodo, 'Aniversariantes')

    birthday_msg = _get_setting('birthday_message', _DEFAULT_BIRTHDAY_MSG)
    return render_template('admin/aniversariantes.html',
        clientes=clientes_list, periodo=periodo, mes_param=mes_param,
        titulo=titulo, today=today, meses=_MESES, birthday_msg=birthday_msg,
    )


@admin_bp.route('/clientes/aniversariantes/export.csv')
@login_required
def aniversariantes_export():
    import io, csv
    from datetime import date
    from flask import Response
    today     = date.today()
    periodo   = request.args.get('periodo', 'mes')
    mes_param = request.args.get('mes', str(today.month))
    lista     = _query_aniversariantes(periodo, mes_param)

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(['Nome','Telefone','Nascimento','Sexo','Endereço','Número','Cidade','Estado'])
    for c in lista:
        w.writerow([
            c.nome, c.telefone or '',
            c.aniversario.strftime('%d/%m/%Y') if c.aniversario else '',
            c.sexo or '', c.endereco or '', c.numero or '',
            c.cidade or '', c.estado or '',
        ])
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=aniversariantes.csv'})


_CSV_COL_MAP = {
    'nome':             ['nome', 'name', 'cliente'],
    'telefone':         ['telefone', 'fone', 'celular', 'whatsapp', 'tel'],
    'email':            ['email', 'e-mail'],
    'cpf':              ['cpf'],
    'aniversario':      ['aniversario', 'aniversário', 'nascimento', 'data_nascimento', 'data nascimento', 'data de nascimento', 'birthday'],
    'sexo':             ['sexo', 'genero', 'gênero', 'género'],
    'cep':              ['cep'],
    'endereco':         ['endereco', 'endereço', 'rua', 'logradouro'],
    'numero':           ['numero', 'número', 'num', 'nº'],
    'complemento':      ['complemento', 'compl'],
    'bairro':           ['bairro'],
    'cidade':           ['cidade', 'city'],
    'estado':           ['estado', 'uf'],
    'descricao':        ['descricao', 'descrição', 'obs', 'observacao', 'observação', 'notas', 'descritivo'],
    'telefone_fixo':    ['telefone_fixo', 'fixo', 'tel_fixo'],
    'telefone_celular': ['telefone_celular', 'celular2', 'cel2'],
    'como_conheceu':    ['como_conheceu', 'como conheceu', 'indicacao', 'indicação', 'origem'],
}


def _map_csv_headers(headers):
    """Mapeia cabeçalhos do CSV para campos do modelo, case-insensitive."""
    mapping = {}
    for h in headers:
        h_norm = h.strip().lower()
        for field, aliases in _CSV_COL_MAP.items():
            if h_norm in aliases:
                mapping[h.strip()] = field
                break
    return mapping


# Limites de tamanho por campo (espelha o modelo Cliente)
_FIELD_MAXLEN = {
    'nome': 100, 'telefone': 20, 'email': 120, 'cpf': 14,
    'cep': 9, 'endereco': 150, 'numero': 10, 'complemento': 80,
    'bairro': 80, 'cidade': 80, 'estado': 2,
    'telefone_fixo': 20, 'telefone_celular': 20, 'como_conheceu': 150,
}

def _trunc(value, field):
    if not value:
        return value
    limit = _FIELD_MAXLEN.get(field)
    return value[:limit] if limit and len(value) > limit else value


def _parse_date_flexible(s):
    from datetime import date as _date
    s = s.strip()
    if not s or s in ('--/--/----', '--/--/--') or '-0001' in s:
        return None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year < 1900 or d > _date.today():
                return None
            return d
        except ValueError:
            pass
    return None


def _normalize_sexo(s):
    s = (s or '').strip().lower()
    if s in ('f', 'fem', 'feminino'):
        return 'F'
    if s in ('m', 'masc', 'masculino'):
        return 'M'
    return None


@admin_bp.route('/clientes/template.csv')
@login_required
def clientes_csv_template():
    import io, csv
    from flask import Response
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['Nome', 'Telefone', 'Email', 'CPF', 'Aniversario', 'Sexo',
                'CEP', 'Endereco', 'Numero', 'Complemento', 'Bairro', 'Cidade', 'Estado',
                'Descricao', 'Telefone_fixo', 'Como_conheceu'])
    w.writerow(['Maria Silva', '(35) 99999-0001', 'maria@email.com', '123.456.789-00',
                '15/06/1990', 'F', '37010-000', 'Rua das Flores', '123', 'Apto 2',
                'Centro', 'Varginha', 'MG', '', '', 'Indicação'])
    return Response(
        '﻿' + buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=template_clientes.csv'},
    )


@admin_bp.route('/clientes/importar-csv', methods=['GET', 'POST'])
@login_required
def clientes_importar_csv():
    import io, csv as csv_mod
    if request.method == 'GET':
        return render_template('admin/clientes_importar.html')

    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        flash('Selecione um arquivo CSV.', 'error')
        return render_template('admin/clientes_importar.html')

    modo_duplicata = request.form.get('modo_duplicata', 'pular')  # pular | atualizar

    try:
        raw = arquivo.read()
        try:
            texto = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto = raw.decode('latin-1')

        # Detecta delimitador (ponto-e-vírgula ou vírgula)
        amostra = texto[:2048]
        delimitador = ';' if amostra.count(';') >= amostra.count(',') else ','

        reader = csv_mod.DictReader(io.StringIO(texto), delimiter=delimitador)
        headers = reader.fieldnames or []
        col_map = _map_csv_headers(headers)

        if 'nome' not in col_map.values():
            flash('Coluna "Nome" não encontrada no CSV. Verifique o arquivo.', 'error')
            return render_template('admin/clientes_importar.html')
        if 'telefone' not in col_map.values():
            flash('Coluna "Telefone" não encontrada no CSV. Verifique o arquivo.', 'error')
            return render_template('admin/clientes_importar.html')

        criados = 0
        atualizados = 0
        pulados = 0
        erros = []

        for i, row in enumerate(reader, start=2):
            def get(field):
                for h, f in col_map.items():
                    if f == field:
                        return (row.get(h) or '').strip()
                return ''

            nome = get('nome')
            telefone = get('telefone')

            if not nome or not telefone:
                erros.append(f'Linha {i}: nome e telefone são obrigatórios (ignorada).')
                continue

            existente = tq(Cliente).filter_by(telefone=telefone).first()

            if existente:
                if modo_duplicata == 'pular':
                    pulados += 1
                    continue
                c = existente
            else:
                c = Cliente()

            def tget(field):
                return _trunc(get(field) or None, field)

            c.nome             = _trunc(nome, 'nome')
            c.telefone         = _trunc(telefone, 'telefone')
            c.email            = tget('email') or (c.email if existente else None)
            c.cpf              = tget('cpf') or (c.cpf if existente else None)
            c.aniversario      = _parse_date_flexible(get('aniversario')) or (c.aniversario if existente else None)
            c.sexo             = _normalize_sexo(get('sexo')) or (c.sexo if existente else None)
            c.cep              = tget('cep') or (c.cep if existente else None)
            c.endereco         = tget('endereco') or (c.endereco if existente else None)
            c.numero           = tget('numero') or (c.numero if existente else None)
            c.complemento      = tget('complemento') or (c.complemento if existente else None)
            c.bairro           = tget('bairro') or (c.bairro if existente else None)
            c.cidade           = tget('cidade') or (c.cidade if existente else None)
            c.estado           = tget('estado') or (c.estado if existente else None)
            c.descricao        = get('descricao') or (c.descricao if existente else None)
            c.telefone_fixo    = tget('telefone_fixo') or (c.telefone_fixo if existente else None)
            c.telefone_celular = tget('telefone_celular') or (c.telefone_celular if existente else None)
            c.como_conheceu    = tget('como_conheceu') or (c.como_conheceu if existente else None)
            c.updated_at       = datetime.utcnow()

            if existente:
                atualizados += 1
            else:
                db.session.add(c)
                criados += 1

        db.session.commit()

        resumo = f'{criados} criado(s), {atualizados} atualizado(s), {pulados} pulado(s).'
        flash(f'Importação concluída: {resumo}', 'success')
        if erros:
            for e in erros[:10]:
                flash(e, 'warning')
            if len(erros) > 10:
                flash(f'... e mais {len(erros) - 10} erro(s) omitido(s).', 'warning')

        return redirect(url_for('admin.clientes'))

    except Exception as exc:
        db.session.rollback()
        flash(f'Erro ao processar o arquivo: {exc}', 'error')
        return render_template('admin/clientes_importar.html')


@admin_bp.route('/clientes/novo', methods=['GET', 'POST'])
@login_required
def cliente_novo():
    if request.method == 'POST':
        c = _build_cliente(Cliente())
        if c:
            db.session.add(c)
            db.session.commit()
            flash('Cliente cadastrado com sucesso.', 'success')
            return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id))
    return render_template('admin/cliente_form.html', c=None, leads_rel=[])


@admin_bp.route('/clientes/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
def cliente_detalhe(cliente_id):
    c = db.get_or_404(Cliente, cliente_id)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'excluir':
            db.session.delete(c)
            db.session.commit()
            flash('Cliente excluído.', 'success')
            return redirect(url_for('admin.clientes'))
        updated = _build_cliente(c)
        if updated:
            db.session.commit()
            flash('Cliente atualizado com sucesso.', 'success')
            return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id))

    digits = ''.join(ch for ch in (c.telefone or '') if ch.isdigit())
    if len(digits) >= 8:
        leads_rel = (tq(Lead)
                     .filter(Lead.phone.like(f'%{digits[-8:]}'))
                     .order_by(Lead.created_at.desc()).limit(10).all())
    else:
        leads_rel = []

    # Auto-backfill: link agendamentos/comandas that match by phone but have no cliente_id
    from decimal import Decimal
    _bf_changed = False
    if len(digits) >= 8:
        phone_tail = digits[-8:]
        unlinked_ags = (tq(Agendamento)
                        .filter(
                            Agendamento.cliente_id.is_(None),
                            Agendamento.telefone.like(f'%{phone_tail}')
                        ).all())
        for ag in unlinked_ags:
            ag.cliente_id = c.id
            _bf_changed = True
            cmd = ag.comanda
            if cmd and cmd.cliente_id is None:
                cmd.cliente_id = c.id
                if cmd.status == 'fechada' and cmd.saldo_ajustado is None:
                    novo_aj = cmd.saldo
                    if novo_aj != 0:
                        c.saldo = (c.saldo or Decimal('0')) - novo_aj
                        cmd.saldo_ajustado = novo_aj
    # Fix comandas whose agendamento is already linked to this client but comanda.cliente_id is null
    for ag in c.agendamentos:
        cmd = ag.comanda
        if cmd and cmd.cliente_id is None:
            cmd.cliente_id = c.id
            _bf_changed = True
            if cmd.status == 'fechada' and cmd.saldo_ajustado is None:
                novo_aj = cmd.saldo
                if novo_aj != 0:
                    c.saldo = (c.saldo or Decimal('0')) - novo_aj
                    cmd.saldo_ajustado = novo_aj
    if _bf_changed:
        db.session.commit()

    vendas_ativas = tq(VendaPacote).filter_by(cliente_id=c.id, status='ativo').all()

    comandas_hist = (tq(Comanda)
                     .filter_by(cliente_id=c.id)
                     .order_by(Comanda.data.desc())
                     .limit(30).all())
    total_gasto = sum(
        (cmd.valor_total - (cmd.desconto or Decimal('0')))
        for cmd in comandas_hist if cmd.status == 'fechada'
    ) or Decimal('0')

    recebimentos = (tq(RecebimentoCliente)
                    .filter_by(cliente_id=c.id)
                    .order_by(RecebimentoCliente.data.desc())
                    .all())

    agendamentos_cli = (tq(Agendamento)
                        .filter_by(cliente_id=c.id)
                        .order_by(Agendamento.data.desc())
                        .all())

    visitas  = sum(1 for cmd in comandas_hist if cmd.status == 'fechada')
    msgs_wa  = [a for a in agendamentos_cli if a.lembrete_enviado]

    from datetime import date as _date
    return render_template('admin/cliente_form.html', c=c, leads_rel=leads_rel,
                           anamnese=c.anamnese_capilar,
                           anamnese_corporal=c.anamnese_corporal,
                           vendas_pacote=vendas_ativas,
                           comandas_hist=comandas_hist,
                           total_gasto=total_gasto,
                           recebimentos=recebimentos,
                           formas=FORMA_PAGAMENTO,
                           hoje=_date.today().isoformat(),
                           agendamentos_cli=agendamentos_cli,
                           visitas=visitas,
                           msgs_wa=msgs_wa)


@admin_bp.route('/clientes/<int:cliente_id>/receber-saldo', methods=['POST'])
@login_required
def cliente_receber_saldo(cliente_id):
    from datetime import date
    from decimal import Decimal
    c = db.get_or_404(Cliente, cliente_id)
    valor_str = request.form.get('valor', '').strip().replace(',', '.')
    forma     = request.form.get('forma_pagamento', '').strip()
    data_str  = request.form.get('data', date.today().isoformat()).strip()
    obs       = request.form.get('observacao', '').strip() or None
    try:
        valor    = Decimal(valor_str)
        data_rec = date.fromisoformat(data_str)
    except Exception:
        flash('Dados inválidos.', 'error')
        return redirect(url_for('admin.cliente_detalhe', cliente_id=cliente_id) + '#saldo')
    if valor <= 0:
        flash('O valor deve ser positivo.', 'error')
        return redirect(url_for('admin.cliente_detalhe', cliente_id=cliente_id) + '#saldo')
    if not forma:
        flash('Selecione a forma de pagamento.', 'error')
        return redirect(url_for('admin.cliente_detalhe', cliente_id=cliente_id) + '#saldo')
    c.saldo = (c.saldo or Decimal('0')) + valor
    db.session.add(RecebimentoCliente(
        cliente_id=cliente_id, valor=valor,
        forma_pagamento=forma, data=data_rec, observacao=obs
    ))
    db.session.commit()
    flash(f'Recebimento de R$ {float(valor):.2f} registrado com sucesso.'.replace('.', ','), 'success')
    return redirect(url_for('admin.cliente_detalhe', cliente_id=cliente_id) + '#saldo')


@admin_bp.route('/clientes/<int:cliente_id>/anamnese', methods=['POST'])
@login_required
def cliente_anamnese(cliente_id):
    c = db.get_or_404(Cliente, cliente_id)
    ana = c.anamnese_capilar or AnamneseCapilar(cliente_id=cliente_id)

    def csv(field):
        return ','.join(request.form.getlist(field)) or None

    ana.tipo                   = request.form.get('tipo')               or None
    ana.caracteristica         = request.form.get('caracteristica')     or None
    ana.pigmentacao            = request.form.get('pigmentacao')        or None
    ana.tipo_cabelo            = request.form.get('tipo_cabelo')        or None
    ana.comprimento            = request.form.get('comprimento', '').strip()  or None
    ana.elasticidade           = request.form.get('elasticidade', '').strip() or None
    ana.porosidade             = request.form.get('porosidade', '').strip()   or None
    ana.volume                 = request.form.get('volume', '').strip()       or None
    ana.espessura_fio          = request.form.get('espessura_fio', '').strip()or None
    ana.resistencia            = request.form.get('resistencia', '').strip()  or None
    ana.condicao               = csv('condicao')
    ana.obs_condicao           = request.form.get('obs_condicao', '').strip() or None
    ana.patologia              = csv('patologia')
    ana.obs_patologia          = request.form.get('obs_patologia', '').strip()or None
    ana.tempo_surgiu           = request.form.get('tempo_surgiu', '').strip() or None
    ana.toma_medicamento       = request.form.get('toma_medicamento', '').strip() or None
    ana.procurou_medico        = request.form.get('procurou_medico')    or None
    ana.diagnostico            = request.form.get('diagnostico', '').strip()  or None
    ana.antecedentes_alergicos = csv('antecedentes_alergicos')
    ana.obs_antecedentes       = request.form.get('obs_antecedentes', '').strip() or None
    ana.tratamentos_atuais     = csv('tratamentos_atuais')
    ana.medicamentos_3meses    = request.form.get('medicamentos_3meses', '').strip() or None
    ana.updated_at             = datetime.utcnow()

    db.session.add(ana)
    db.session.commit()
    flash('Anamnese capilar salva com sucesso.', 'success')
    return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id) + '#tab-anamnese')


@admin_bp.route('/clientes/<int:cliente_id>/anamnese-corporal', methods=['POST'])
@login_required
def cliente_anamnese_corporal(cliente_id):
    c = db.get_or_404(Cliente, cliente_id)
    anc = c.anamnese_corporal or AnamneseCorporal(cliente_id=cliente_id)

    def csv(field):
        return ','.join(request.form.getlist(field)) or None

    anc.motivo_visita                 = request.form.get('motivo_visita', '').strip()              or None
    anc.tratamentos_anteriores        = request.form.get('tratamentos_anteriores')                  or None
    anc.quais_tratamentos_anteriores  = request.form.get('quais_tratamentos_anteriores', '').strip()or None
    anc.resultados_tratamentos        = request.form.get('resultados_tratamentos', '').strip()       or None
    anc.antecedentes_pessoais         = csv('antecedentes_pessoais')
    anc.antecedentes_familiares       = csv('antecedentes_familiares')
    anc.antecedentes_alergicos        = request.form.get('antecedentes_alergicos')                  or None
    anc.quais_antecedentes_alergicos  = request.form.get('quais_antecedentes_alergicos', '').strip()or None
    anc.antecedentes_cirurgicos       = request.form.get('antecedentes_cirurgicos')                 or None
    anc.quais_antecedentes_cirurgicos = request.form.get('quais_antecedentes_cirurgicos', '').strip()or None
    anc.atividade_fisica              = request.form.get('atividade_fisica')                        or None
    anc.frequencia_atividade          = request.form.get('frequencia_atividade', '').strip()        or None
    anc.horas_sono                    = request.form.get('horas_sono', '').strip()                  or None
    anc.toma_alcool                   = request.form.get('toma_alcool')                             or None
    anc.fuma                          = request.form.get('fuma')                                    or None
    anc.preenchimento                 = request.form.get('preenchimento')                           or None
    anc.toma_sol                      = request.form.get('toma_sol')                                or None
    anc.roupas_apertadas              = request.form.get('roupas_apertadas')                        or None
    anc.tipo_alimentacao              = csv('tipo_alimentacao')
    anc.muito_apetite                 = request.form.get('muito_apetite')                           or None
    anc.intestino_preso               = request.form.get('intestino_preso')                         or None
    anc.consumo_agua                  = request.form.get('consumo_agua')                            or None
    anc.urina                         = request.form.get('urina')                                   or None
    anc.posicao_dia                   = request.form.get('posicao_dia', '').strip()                 or None
    anc.usa_diu                       = request.form.get('usa_diu')                                 or None
    anc.gravidez                      = request.form.get('gravidez')                                or None
    anc.menopausa                     = request.form.get('menopausa')                               or None
    anc.num_gestacoes                 = request.form.get('num_gestacoes', '').strip()               or None
    anc.menstruacao_regular           = request.form.get('menstruacao_regular')                     or None
    anc.uso_medicamentos              = request.form.get('uso_medicamentos')                        or None
    anc.quais_remedios                = request.form.get('quais_remedios', '').strip()              or None
    anc.updated_at                    = datetime.utcnow()

    db.session.add(anc)
    db.session.commit()
    flash('Anamnese corporal salva com sucesso.', 'success')
    return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id) + '#tab-anamnese-corporal')


def _build_cliente(c):
    from datetime import date as _date
    nome     = request.form.get('nome', '').strip()
    telefone = request.form.get('telefone', '').strip()
    if not nome or not telefone:
        flash('Nome e telefone são obrigatórios.', 'error')
        return None

    aniversario = None
    aniv_str = request.form.get('aniversario', '').strip()
    if aniv_str:
        try:
            parts = aniv_str.split('-')
            aniversario = _date(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            pass

    c.nome             = nome
    c.telefone         = telefone
    c.email            = request.form.get('email', '').strip()            or None
    c.cpf              = request.form.get('cpf', '').strip()              or None
    c.aniversario      = aniversario
    c.sexo             = request.form.get('sexo', '')                     or None
    c.bloqueado        = bool(request.form.get('bloqueado'))
    c.cep              = request.form.get('cep', '').strip()              or None
    c.endereco         = request.form.get('endereco', '').strip()         or None
    c.numero           = request.form.get('numero', '').strip()           or None
    c.complemento      = request.form.get('complemento', '').strip()      or None
    c.bairro           = request.form.get('bairro', '').strip()           or None
    c.cidade           = request.form.get('cidade', '').strip()           or None
    c.estado           = request.form.get('estado', '')                   or None
    c.descricao        = request.form.get('descricao', '').strip()        or None
    c.telefone_fixo    = request.form.get('telefone_fixo', '').strip()    or None
    c.telefone_celular = request.form.get('telefone_celular', '').strip() or None
    c.como_conheceu    = request.form.get('como_conheceu', '').strip()    or None
    c.updated_at       = datetime.utcnow()
    return c
