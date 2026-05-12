import json
from collections import defaultdict
from flask import render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta

from . import admin_bp
from models import (db, Studio, StudioConfig, User, Lead,
                    Cliente, Categoria, Unidade, Profissional, Servico,
                    Agendamento, BloqueioAgenda, ComissaoProfissional,
                    Expediente, ExpedienteDia, Comanda, ComandaItem, PagamentoComanda,
                    Pacote, PacoteItem, VendaPacote, VendaPacoteItem,
                    LEAD_STATUSES, LEAD_SOURCES, PERFIL_ACESSO, FORMA_PAGAMENTO,
                    DIAS_SEMANA, AI_PROVIDERS)
from themes import THEMES, get_theme_css


def sid():
    """Retorna o studio_id do usuário autenticado."""
    return current_user.studio_id


# ── Auth ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/')
def index():
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    if not Studio.query.first():
        return redirect(url_for('admin.setup'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin.dashboard'))
        flash('Usuário ou senha incorretos.', 'error')

    return render_template('admin/login.html')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


@admin_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if Studio.query.first():
        return redirect(url_for('admin.login'))

    if request.method == 'POST':
        studio_nome     = request.form.get('studio_nome', '').strip()
        slug            = request.form.get('slug', '').strip().lower().replace(' ', '-')
        studio_telefone = request.form.get('studio_telefone', '').strip()
        studio_cidade   = request.form.get('studio_cidade', '').strip()
        name            = request.form.get('name', '').strip()
        username        = request.form.get('username', '').strip()
        email           = request.form.get('email', '').strip()
        phone           = request.form.get('phone', '').strip()
        password        = request.form.get('password', '')
        confirm         = request.form.get('confirm', '')

        if not all([studio_nome, slug, name, username, password]):
            flash('Preencha todos os campos obrigatórios.', 'error')
        elif password != confirm:
            flash('As senhas não coincidem.', 'error')
        elif len(password) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'error')
        else:
            studio = Studio(nome=studio_nome, slug=slug)
            db.session.add(studio)
            db.session.flush()

            if studio_telefone:
                db.session.add(StudioConfig(studio_id=studio.id, key='telefone', value=studio_telefone))
            if studio_cidade:
                db.session.add(StudioConfig(studio_id=studio.id, key='cidade', value=studio_cidade))

            user = User(studio_id=studio.id, name=name, username=username,
                        email=email, phone=phone)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Plataforma configurada com sucesso!', 'success')
            return redirect(url_for('admin.dashboard'))

        return render_template('admin/setup.html', form=request.form)

    return render_template('admin/setup.html', form={})


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    total     = Lead.query.filter_by(studio_id=sid()).count()
    by_status = {s: Lead.query.filter_by(studio_id=sid(), status=s).count()
                 for s, _ in LEAD_STATUSES}
    recent    = Lead.query.filter_by(studio_id=sid()).order_by(Lead.created_at.desc()).limit(8).all()

    theme_key  = current_user.studio.get_config('active_theme', 'default')
    theme_name = THEMES.get(theme_key, THEMES['default'])['name']

    return render_template('admin/dashboard.html',
        total=total, by_status=by_status, recent=recent,
        statuses=LEAD_STATUSES, theme_name=theme_name,
        studio=current_user.studio)


# ── Leads ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/leads')
@login_required
def leads():
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    source = request.args.get('source', '')
    query  = Lead.query.filter_by(studio_id=sid())
    if q:
        like  = f'%{q}%'
        query = query.filter(db.or_(Lead.name.ilike(like), Lead.phone.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    if source:
        query = query.filter_by(source=source)
    all_leads = query.order_by(Lead.created_at.desc()).all()
    return render_template('admin/leads.html', leads=all_leads,
        q=q, status=status, source=source,
        statuses=LEAD_STATUSES, sources=LEAD_SOURCES)


@admin_bp.route('/leads/novo', methods=['GET', 'POST'])
@login_required
def lead_novo():
    if request.method == 'POST':
        lead = Lead(
            studio_id = sid(),
            name      = request.form.get('name', '').strip() or None,
            phone     = request.form.get('phone', '').strip(),
            email     = request.form.get('email', '').strip() or None,
            source    = request.form.get('source', 'manual'),
            service   = request.form.get('service', '').strip() or None,
            message   = request.form.get('message', '').strip() or None,
            status    = request.form.get('status', 'novo'),
            notes     = request.form.get('notes', '').strip() or None,
        )
        db.session.add(lead)
        db.session.commit()
        flash('Lead cadastrado.', 'success')
        return redirect(url_for('admin.lead_detail', lead_id=lead.id))
    return render_template('admin/lead_form.html', lead=None,
        statuses=LEAD_STATUSES, sources=LEAD_SOURCES)


@admin_bp.route('/leads/<int:lead_id>', methods=['GET', 'POST'])
@login_required
def lead_detail(lead_id):
    lead = Lead.query.filter_by(id=lead_id, studio_id=sid()).first_or_404()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            db.session.delete(lead)
            db.session.commit()
            flash('Lead excluído.', 'success')
            return redirect(url_for('admin.leads'))
        lead.name    = request.form.get('name', '').strip() or None
        lead.phone   = request.form.get('phone', '').strip()
        lead.email   = request.form.get('email', '').strip() or None
        lead.source  = request.form.get('source', 'manual')
        lead.service = request.form.get('service', '').strip() or None
        lead.message = request.form.get('message', '').strip() or None
        lead.status  = request.form.get('status', lead.status)
        lead.notes   = request.form.get('notes', '').strip() or None
        lead.unit    = request.form.get('unit', '').strip() or None
        db.session.commit()
        flash('Lead atualizado.', 'success')
    return render_template('admin/lead_detail.html', lead=lead,
        statuses=LEAD_STATUSES, sources=LEAD_SOURCES)


# ── Clientes ──────────────────────────────────────────────────────────────────

@admin_bp.route('/clientes')
@login_required
def clientes():
    q         = request.args.get('q', '').strip()
    bloqueado = request.args.get('bloqueado', '')
    query     = Cliente.query.filter_by(studio_id=sid())
    if q:
        like  = f'%{q}%'
        query = query.filter(db.or_(
            Cliente.nome.ilike(like), Cliente.telefone.ilike(like),
            Cliente.email.ilike(like), Cliente.cidade.ilike(like),
        ))
    if bloqueado == '1':
        query = query.filter_by(bloqueado=True)
    elif bloqueado == '0':
        query = query.filter_by(bloqueado=False)
    all_clientes = query.order_by(Cliente.nome).all()
    return render_template('admin/clientes.html',
        clientes=all_clientes, q=q, bloqueado=bloqueado)


@admin_bp.route('/clientes/novo', methods=['GET', 'POST'])
@login_required
def cliente_novo():
    if request.method == 'POST':
        c = Cliente(studio_id=sid())
        _build_cliente(c)
        db.session.add(c)
        db.session.commit()
        flash('Cliente cadastrado com sucesso.', 'success')
        return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id))
    return render_template('admin/cliente_form.html', c=None, leads_rel=[],
                           vendas_pacote=[])


@admin_bp.route('/clientes/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
def cliente_detalhe(cliente_id):
    c = Cliente.query.filter_by(id=cliente_id, studio_id=sid()).first_or_404()
    if request.method == 'POST':
        if request.form.get('action') == 'excluir':
            db.session.delete(c)
            db.session.commit()
            flash('Cliente excluído.', 'success')
            return redirect(url_for('admin.clientes'))
        _build_cliente(c)
        db.session.commit()
        flash('Cliente atualizado.', 'success')
        return redirect(url_for('admin.cliente_detalhe', cliente_id=c.id))

    digits = ''.join(ch for ch in (c.telefone or '') if ch.isdigit())
    leads_rel = (Lead.query.filter_by(studio_id=sid())
                 .filter(Lead.phone.like(f'%{digits[-8:]}'))
                 .order_by(Lead.created_at.desc()).limit(10).all()) if len(digits) >= 8 else []
    vendas_ativas = VendaPacote.query.filter_by(studio_id=sid(), cliente_id=c.id, status='ativo').all()

    return render_template('admin/cliente_form.html', c=c, leads_rel=leads_rel,
                           anamnese=None, anamnese_corporal=None,
                           vendas_pacote=vendas_ativas)


def _build_cliente(c):
    for field in ['nome', 'telefone', 'email', 'cpf', 'sexo', 'cep', 'endereco',
                  'numero', 'complemento', 'bairro', 'cidade', 'estado',
                  'descricao', 'telefone_fixo', 'telefone_celular', 'como_conheceu']:
        setattr(c, field, request.form.get(field, '').strip() or None)
    ani = request.form.get('aniversario', '').strip()
    try:
        from datetime import date
        c.aniversario = date.fromisoformat(ani) if ani else None
    except ValueError:
        c.aniversario = None
    c.bloqueado = bool(request.form.get('bloqueado'))
    c.updated_at = datetime.utcnow()


@admin_bp.route('/aniversariantes')
@login_required
def aniversariantes():
    from datetime import date
    periodo   = request.args.get('periodo', 'mes')
    mes_param = request.args.get('mes', '')
    hoje      = date.today()

    query = Cliente.query.filter_by(studio_id=sid()).filter(Cliente.aniversario.isnot(None))

    if periodo == 'hoje':
        clientes_list = [c for c in query.all()
                         if c.aniversario and c.aniversario.month == hoje.month
                         and c.aniversario.day == hoje.day]
    elif periodo == 'semana':
        clientes_list = [c for c in query.all()
                         if c.aniversario and _dias_para_aniversario(c.aniversario, hoje) < 7]
    else:
        try:
            mes = int(mes_param) if mes_param else hoje.month
        except ValueError:
            mes = hoje.month
        clientes_list = [c for c in query.all()
                         if c.aniversario and c.aniversario.month == mes]

    return render_template('admin/aniversariantes.html',
        clientes=clientes_list, periodo=periodo, mes_param=mes_param,
        hoje=hoje, meses=_MESES)


def _dias_para_aniversario(aniversario, hoje):
    from datetime import date
    try:
        proximo = date(hoje.year, aniversario.month, aniversario.day)
    except ValueError:
        return 999
    if proximo < hoje:
        proximo = date(hoje.year + 1, aniversario.month, aniversario.day)
    return (proximo - hoje).days


_MESES = {
    1:'Janeiro', 2:'Fevereiro', 3:'Março',    4:'Abril',
    5:'Maio',    6:'Junho',     7:'Julho',     8:'Agosto',
    9:'Setembro',10:'Outubro',  11:'Novembro', 12:'Dezembro',
}


# ── Serviços ──────────────────────────────────────────────────────────────────

@admin_bp.route('/servicos')
@login_required
def servicos():
    q      = request.args.get('q', '').strip()
    cat_id = request.args.get('categoria', '')
    query  = Servico.query.filter_by(studio_id=sid())
    if q:
        query = query.filter(Servico.nome.ilike(f'%{q}%'))
    if cat_id:
        try: query = query.filter_by(categoria_id=int(cat_id))
        except ValueError: pass
    all_servicos = query.order_by(Servico.nome).all()
    cats         = Categoria.query.filter_by(studio_id=sid(), ativo=True).order_by(Categoria.nome).all()
    return render_template('admin/servicos.html',
        servicos=all_servicos, categorias=cats, q=q, cat_id=cat_id)


@admin_bp.route('/servicos/novo', methods=['GET', 'POST'])
@login_required
def servico_novo():
    if request.method == 'POST':
        s = _build_servico(Servico(studio_id=sid()))
        if s:
            db.session.add(s)
            db.session.commit()
            flash('Serviço cadastrado com sucesso.', 'success')
            return redirect(url_for('admin.servico_detalhe', servico_id=s.id))
    cats  = Categoria.query.filter_by(studio_id=sid(), ativo=True).order_by(Categoria.nome).all()
    profs = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    return render_template('admin/servico_form.html', s=None, categorias=cats, profissionais=profs)


@admin_bp.route('/servicos/<int:servico_id>', methods=['GET', 'POST'])
@login_required
def servico_detalhe(servico_id):
    s = Servico.query.filter_by(id=servico_id, studio_id=sid()).first_or_404()
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
    cats  = Categoria.query.filter_by(studio_id=sid(), ativo=True).order_by(Categoria.nome).all()
    profs = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
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
    profs_q = Profissional.query.filter(Profissional.id.in_(ids),
                                        Profissional.studio_id == sid())
    s.profissionais_adicionais = profs_q.all() if ids else []
    return s


# ── Categorias ────────────────────────────────────────────────────────────────

@admin_bp.route('/categorias', methods=['GET', 'POST'])
@login_required
def categorias():
    if request.method == 'POST':
        action = request.form.get('action')
        cat_id = request.form.get('id', '')
        nome   = request.form.get('nome', '').strip()
        descr  = request.form.get('descricao', '').strip() or None

        if action == 'save':
            if not nome:
                flash('Nome é obrigatório.', 'error')
            elif cat_id:
                c = Categoria.query.filter_by(id=int(cat_id), studio_id=sid()).first_or_404()
                c.nome, c.descricao = nome, descr
                db.session.commit()
                flash('Categoria atualizada.', 'success')
            else:
                db.session.add(Categoria(studio_id=sid(), nome=nome, descricao=descr))
                db.session.commit()
                flash('Categoria criada.', 'success')
        elif action == 'delete' and cat_id:
            c = Categoria.query.filter_by(id=int(cat_id), studio_id=sid()).first_or_404()
            db.session.delete(c)
            db.session.commit()
            flash('Categoria excluída.', 'success')

    cats = Categoria.query.filter_by(studio_id=sid()).order_by(Categoria.nome).all()
    return render_template('admin/categorias.html', categorias=cats)


# ── Pacotes ───────────────────────────────────────────────────────────────────

@admin_bp.route('/servicos/pacotes')
@login_required
def pacotes():
    todos    = Pacote.query.filter_by(studio_id=sid()).order_by(Pacote.nome).all()
    servicos = Servico.query.filter_by(studio_id=sid(), ativo=True).order_by(Servico.nome).all()
    return render_template('admin/pacotes.html', pacotes=todos, servicos=servicos)


@admin_bp.route('/api/pacotes', methods=['POST'])
@login_required
def api_pacote_criar():
    from decimal import Decimal, InvalidOperation
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    if not nome:
        return jsonify({'ok': False, 'erro': 'Nome obrigatório'}), 400
    pacote = Pacote(studio_id=sid(), nome=nome,
                    descricao=(data.get('descricao') or '').strip() or None)
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
        svc = Servico.query.filter_by(id=svc_id, studio_id=sid()).first()
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
    p = Pacote.query.filter_by(id=pacote_id, studio_id=sid()).first_or_404()
    if request.method == 'GET':
        return jsonify({
            'id': p.id, 'nome': p.nome, 'descricao': p.descricao or '',
            'ativo': p.ativo, 'valor_total': float(p.valor_total),
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
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    if not nome:
        return jsonify({'ok': False, 'erro': 'Nome obrigatório'}), 400
    p.nome      = nome
    p.descricao = (data.get('descricao') or '').strip() or None
    p.ativo     = bool(data.get('ativo', True))
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
    s = Servico.query.filter_by(id=servico_id, studio_id=sid()).first_or_404()
    return jsonify({'preco': float(s.preco) if s.preco else 0})


# ── Profissionais ─────────────────────────────────────────────────────────────

@admin_bp.route('/profissionais')
@login_required
def profissionais():
    q     = request.args.get('q', '').strip()
    query = Profissional.query.filter_by(studio_id=sid())
    if q:
        query = query.filter(Profissional.nome.ilike(f'%{q}%'))
    profs    = query.order_by(Profissional.nome).all()
    unidades = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    return render_template('admin/profissionais.html', profissionais=profs,
                           unidades=unidades, q=q)


@admin_bp.route('/profissionais/novo', methods=['GET', 'POST'])
@login_required
def profissional_novo():
    if request.method == 'POST':
        p = Profissional(studio_id=sid())
        if _build_profissional(p):
            db.session.add(p)
            db.session.commit()
            flash('Profissional cadastrado.', 'success')
            return redirect(url_for('admin.profissional_detalhe', profissional_id=p.id))
    cats     = Categoria.query.filter_by(studio_id=sid(), ativo=True).order_by(Categoria.nome).all()
    unidades = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    exps     = Expediente.query.filter_by(studio_id=sid()).order_by(Expediente.nome).all()
    return render_template('admin/profissional_form.html', p=None,
        categorias=cats, unidades=unidades, expedientes=exps, perfis=PERFIL_ACESSO)


@admin_bp.route('/profissionais/<int:profissional_id>', methods=['GET', 'POST'])
@login_required
def profissional_detalhe(profissional_id):
    p = Profissional.query.filter_by(id=profissional_id, studio_id=sid()).first_or_404()
    if request.method == 'POST':
        if request.form.get('action') == 'excluir':
            db.session.delete(p)
            db.session.commit()
            flash('Profissional excluído.', 'success')
            return redirect(url_for('admin.profissionais'))
        if _build_profissional(p):
            db.session.commit()
            flash('Profissional atualizado.', 'success')
            return redirect(url_for('admin.profissional_detalhe', profissional_id=p.id))
    cats     = Categoria.query.filter_by(studio_id=sid(), ativo=True).order_by(Categoria.nome).all()
    unidades = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    exps     = Expediente.query.filter_by(studio_id=sid()).order_by(Expediente.nome).all()
    return render_template('admin/profissional_form.html', p=p,
        categorias=cats, unidades=unidades, expedientes=exps, perfis=PERFIL_ACESSO)


def _build_profissional(p):
    nome = request.form.get('nome', '').strip()
    if not nome:
        flash('Nome é obrigatório.', 'error')
        return False
    p.nome                = nome
    p.email               = request.form.get('email', '').strip() or None
    p.telefone            = request.form.get('telefone', '').strip() or None
    p.cargo               = request.form.get('cargo', '').strip() or None
    p.obs                 = request.form.get('obs', '').strip() or None
    p.perfil_acesso       = request.form.get('perfil_acesso', 'profissional')
    p.agendamento_online  = bool(request.form.get('agendamento_online'))
    p.agendamentos_simult = bool(request.form.get('agendamentos_simult'))
    p.ativo               = not bool(request.form.get('inativo'))
    uid = request.form.get('unidade_id', '')
    eid = request.form.get('expediente_id', '')
    p.unidade_id    = int(uid) if uid else None
    p.expediente_id = int(eid) if eid else None
    ids = [int(x) for x in request.form.getlist('categorias') if x.isdigit()]
    p.categorias = Categoria.query.filter(Categoria.id.in_(ids),
                                          Categoria.studio_id == sid()).all() if ids else []
    return True


# ── Expedientes ───────────────────────────────────────────────────────────────

@admin_bp.route('/expedientes')
@login_required
def expedientes():
    exps = Expediente.query.filter_by(studio_id=sid()).order_by(Expediente.nome).all()
    return render_template('admin/expedientes.html', expedientes=exps,
                           dias_semana=DIAS_SEMANA)


@admin_bp.route('/expedientes/novo', methods=['GET', 'POST'])
@login_required
def expediente_novo():
    if request.method == 'POST':
        exp = Expediente(studio_id=sid(), nome=request.form.get('nome', '').strip())
        if not exp.nome:
            flash('Nome é obrigatório.', 'error')
        else:
            _build_expediente_dias(exp)
            db.session.add(exp)
            db.session.commit()
            flash('Expediente criado.', 'success')
            return redirect(url_for('admin.expedientes'))
    return render_template('admin/expediente_form.html', exp=None, dias_semana=DIAS_SEMANA)


@admin_bp.route('/expedientes/<int:exp_id>', methods=['GET', 'POST'])
@login_required
def expediente_detalhe(exp_id):
    exp = Expediente.query.filter_by(id=exp_id, studio_id=sid()).first_or_404()
    if request.method == 'POST':
        if request.form.get('action') == 'excluir':
            db.session.delete(exp)
            db.session.commit()
            flash('Expediente excluído.', 'success')
            return redirect(url_for('admin.expedientes'))
        exp.nome = request.form.get('nome', '').strip() or exp.nome
        exp.dias.clear()
        _build_expediente_dias(exp)
        db.session.commit()
        flash('Expediente atualizado.', 'success')
        return redirect(url_for('admin.expediente_detalhe', exp_id=exp.id))
    return render_template('admin/expediente_form.html', exp=exp, dias_semana=DIAS_SEMANA)


def _build_expediente_dias(exp):
    from datetime import time as dtime
    for dia in range(7):
        if request.form.get(f'dia_{dia}'):
            try:
                hi = dtime.fromisoformat(request.form.get(f'hi_{dia}', '09:00'))
                hf = dtime.fromisoformat(request.form.get(f'hf_{dia}', '18:00'))
            except ValueError:
                continue
            ai_s = request.form.get(f'ai_{dia}', '')
            af_s = request.form.get(f'af_{dia}', '')
            ai = dtime.fromisoformat(ai_s) if ai_s else None
            af = dtime.fromisoformat(af_s) if af_s else None
            exp.dias.append(ExpedienteDia(
                dia_semana=dia, hora_inicio=hi, hora_fim=hf,
                almoco_inicio=ai, almoco_fim=af))


# ── Unidades ──────────────────────────────────────────────────────────────────

@admin_bp.route('/unidades', methods=['GET', 'POST'])
@login_required
def unidades():
    if request.method == 'POST':
        action = request.form.get('action')
        uid    = request.form.get('id', '')
        nome   = request.form.get('nome', '').strip()
        if action == 'save':
            if not nome:
                flash('Nome é obrigatório.', 'error')
            elif uid:
                u = Unidade.query.filter_by(id=int(uid), studio_id=sid()).first_or_404()
                u.nome    = nome
                u.cidade  = request.form.get('cidade', '').strip() or None
                u.estado  = request.form.get('estado', '').strip() or None
                u.telefone = request.form.get('telefone', '').strip() or None
                u.ativo   = not bool(request.form.get('inativo'))
                db.session.commit()
                flash('Unidade atualizada.', 'success')
            else:
                db.session.add(Unidade(
                    studio_id=sid(), nome=nome,
                    cidade=request.form.get('cidade', '').strip() or None,
                    estado=request.form.get('estado', '').strip() or None,
                    telefone=request.form.get('telefone', '').strip() or None,
                ))
                db.session.commit()
                flash('Unidade criada.', 'success')
        elif action == 'delete' and uid:
            u = Unidade.query.filter_by(id=int(uid), studio_id=sid()).first_or_404()
            db.session.delete(u)
            db.session.commit()
            flash('Unidade excluída.', 'success')
    uns = Unidade.query.filter_by(studio_id=sid()).order_by(Unidade.nome).all()
    return render_template('admin/unidades.html', unidades=uns)


# ── Agenda ────────────────────────────────────────────────────────────────────

@admin_bp.route('/agenda')
@login_required
def agenda():
    from datetime import date
    data_str = request.args.get('data', date.today().isoformat())
    try:
        data_sel = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        data_sel = datetime.today().date()

    profs    = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    unidades = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    servicos = Servico.query.filter_by(studio_id=sid(), ativo=True).order_by(Servico.nome).all()
    clientes = Cliente.query.filter_by(studio_id=sid()).order_by(Cliente.nome).all()

    agendamentos = (Agendamento.query
                    .filter_by(studio_id=sid(), data=data_sel)
                    .order_by(Agendamento.hora_inicio).all())
    bloqueios    = (BloqueioAgenda.query
                    .filter_by(studio_id=sid())
                    .filter(BloqueioAgenda.data_inicio <= data_sel,
                            BloqueioAgenda.data_fim >= data_sel).all())

    return render_template('admin/agenda.html',
        data_sel=data_sel, profissionais=profs, unidades=unidades,
        servicos=servicos, clientes=clientes,
        agendamentos=agendamentos, bloqueios=bloqueios,
        status_list=AGENDAMENTO_STATUS)


@admin_bp.route('/agenda/listagem')
@login_required
def agenda_listagem():
    from datetime import date
    data_ini_s = request.args.get('data_ini', date.today().isoformat())
    data_fim_s = request.args.get('data_fim', date.today().isoformat())
    status_f   = request.args.get('status', '')
    prof_f     = request.args.get('profissional_id', '')

    try:
        data_ini = datetime.strptime(data_ini_s, '%Y-%m-%d').date()
        data_fim = datetime.strptime(data_fim_s, '%Y-%m-%d').date()
    except ValueError:
        data_ini = data_fim = date.today()

    query = (Agendamento.query
             .filter_by(studio_id=sid())
             .filter(Agendamento.data >= data_ini, Agendamento.data <= data_fim))
    if status_f:
        query = query.filter_by(status=status_f)
    if prof_f:
        try: query = query.filter_by(profissional_id=int(prof_f))
        except ValueError: pass

    agendamentos = query.order_by(Agendamento.data, Agendamento.hora_inicio).all()
    profs        = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()

    return render_template('admin/agenda_listagem.html',
        agendamentos=agendamentos, profissionais=profs,
        data_ini=data_ini_s, data_fim=data_fim_s,
        status_f=status_f, prof_f=prof_f, status_list=AGENDAMENTO_STATUS)


@admin_bp.route('/agenda/bloqueios', methods=['GET', 'POST'])
@login_required
def agenda_bloqueios():
    from datetime import date, time as dtime
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'criar':
            try:
                di = date.fromisoformat(request.form.get('data_inicio', ''))
                df = date.fromisoformat(request.form.get('data_fim', ''))
            except ValueError:
                flash('Datas inválidas.', 'error')
                return redirect(url_for('admin.agenda_bloqueios'))
            dia_inteiro = bool(request.form.get('dia_inteiro'))
            hi_s = request.form.get('hora_inicio', '')
            hf_s = request.form.get('hora_fim', '')
            pid  = request.form.get('profissional_id', '')
            bl = BloqueioAgenda(
                studio_id       = sid(),
                profissional_id = int(pid) if pid else None,
                data_inicio     = di, data_fim = df,
                dia_inteiro     = dia_inteiro,
                hora_inicio     = dtime.fromisoformat(hi_s) if hi_s and not dia_inteiro else None,
                hora_fim        = dtime.fromisoformat(hf_s) if hf_s and not dia_inteiro else None,
                motivo          = request.form.get('motivo', '').strip() or None,
            )
            db.session.add(bl)
            db.session.commit()
            flash('Bloqueio criado.', 'success')
        elif action == 'excluir':
            bl_id = request.form.get('bloqueio_id', '')
            if bl_id:
                bl = BloqueioAgenda.query.filter_by(id=int(bl_id), studio_id=sid()).first()
                if bl:
                    db.session.delete(bl)
                    db.session.commit()
                    flash('Bloqueio removido.', 'success')
        return redirect(url_for('admin.agenda_bloqueios'))

    from datetime import date
    bloqueios = (BloqueioAgenda.query
                 .filter_by(studio_id=sid())
                 .filter(BloqueioAgenda.data_fim >= date.today())
                 .order_by(BloqueioAgenda.data_inicio).all())
    profs = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    return render_template('admin/agenda_bloqueios.html',
        bloqueios=bloqueios, profissionais=profs)


@admin_bp.route('/api/agenda/agendamento', methods=['POST'])
@login_required
def api_agendamento_criar():
    from datetime import date, time as dtime
    data_s  = request.form.get('data', '')
    hora_s  = request.form.get('hora_inicio', '')
    prof_id = request.form.get('profissional_id', '')
    nome    = request.form.get('nome_cliente', '').strip()
    if not all([data_s, hora_s, prof_id, nome]):
        return jsonify({'ok': False, 'erro': 'Campos obrigatórios faltando'}), 400
    try:
        d  = date.fromisoformat(data_s)
        hi = dtime.fromisoformat(hora_s)
    except ValueError:
        return jsonify({'ok': False, 'erro': 'Data/hora inválida'}), 400
    svc_id = request.form.get('servico_id', '')
    dur    = 60
    if svc_id:
        svc = Servico.query.filter_by(id=int(svc_id), studio_id=sid()).first()
        if svc:
            dur = svc.duracao_horas * 60 + svc.duracao_minutos
    cli_id = request.form.get('cliente_id', '')
    uid    = request.form.get('unidade_id', '')
    ag = Agendamento(
        studio_id       = sid(),
        nome_cliente    = nome,
        telefone        = request.form.get('telefone', '').strip() or None,
        cliente_id      = int(cli_id) if cli_id else None,
        profissional_id = int(prof_id),
        servico_id      = int(svc_id) if svc_id else None,
        unidade_id      = int(uid) if uid else None,
        data            = d, hora_inicio = hi,
        duracao_min     = int(request.form.get('duracao_min', dur)),
        status          = 'agendado',
        observacoes     = request.form.get('observacoes', '').strip() or None,
        como_conheceu   = request.form.get('como_conheceu', '').strip() or None,
    )
    db.session.add(ag)
    db.session.commit()
    return jsonify({'ok': True, 'id': ag.id})


@admin_bp.route('/api/agenda/agendamento/<int:ag_id>', methods=['PATCH', 'DELETE'])
@login_required
def api_agendamento_update(ag_id):
    ag = Agendamento.query.filter_by(id=ag_id, studio_id=sid()).first_or_404()
    if request.method == 'DELETE':
        db.session.delete(ag)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json(silent=True) or {}
    if 'status' in data:
        ag.status = data['status']
    if 'observacoes' in data:
        ag.observacoes = data['observacoes']
    db.session.commit()
    return jsonify({'ok': True})


@admin_bp.route('/api/categorias/<int:cat_id>/profissionais')
@login_required
def api_cat_profissionais(cat_id):
    profs = Profissional.query.filter_by(categoria_id=cat_id, studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    return jsonify([{'id': p.id, 'nome': p.nome} for p in profs])


@admin_bp.route('/api/clientes/<int:cliente_id>/pacotes-ativos')
@login_required
def api_cliente_pacotes_ativos(cliente_id):
    vendas = VendaPacote.query.filter_by(studio_id=sid(), cliente_id=cliente_id, status='ativo').all()
    result = []
    for v in vendas:
        for item in v.itens:
            if item.quantidade_restante > 0:
                result.append({
                    'venda_id':             v.id,
                    'venda_pacote_item_id': item.id,
                    'servico_id':           item.servico_id,
                    'servico_nome':         item.descricao,
                    'pacote_nome':          v.nome_pacote,
                    'restantes':            item.quantidade_restante,
                    'total':                item.quantidade_total,
                })
    return jsonify(result)


# ── Financeiro ────────────────────────────────────────────────────────────────

@admin_bp.route('/financeiro')
@login_required
def financeiro():
    from datetime import date
    from decimal import Decimal
    hoje  = date.today()
    mes_i = hoje.replace(day=1)

    comandas_mes = Comanda.query.filter_by(studio_id=sid()).filter(
        Comanda.data >= mes_i, Comanda.data <= hoje).all()
    faturado = sum(c.valor_total - (c.desconto or 0) for c in comandas_mes)
    recebido = sum(c.valor_pago for c in comandas_mes)

    return render_template('admin/financeiro_index.html',
        faturado=faturado, recebido=recebido,
        comandas_abertas=Comanda.query.filter_by(studio_id=sid(), status='aberta').count(),
        mes_i=mes_i, hoje=hoje)


@admin_bp.route('/financeiro/comandas', methods=['GET', 'POST'])
@login_required
def financeiro_comandas():
    from datetime import date
    q         = request.args.get('q', '').strip()
    status_f  = request.args.get('status', '')
    data_ini  = request.args.get('data_ini', '')
    data_fim  = request.args.get('data_fim', '')

    query = Comanda.query.filter_by(studio_id=sid())
    if q:
        like  = f'%{q}%'
        query = query.filter(db.or_(Comanda.nome_cliente.ilike(like),
                                    Comanda.codigo.cast(db.String).ilike(like)))
    if status_f:
        query = query.filter_by(status=status_f)
    if data_ini:
        try: query = query.filter(Comanda.data >= date.fromisoformat(data_ini))
        except ValueError: pass
    if data_fim:
        try: query = query.filter(Comanda.data <= date.fromisoformat(data_fim))
        except ValueError: pass

    comandas = query.order_by(Comanda.data.desc(), Comanda.codigo.desc()).all()
    return render_template('admin/financeiro_comandas.html',
        comandas=comandas, q=q, status_f=status_f,
        data_ini=data_ini, data_fim=data_fim)


def _next_codigo():
    from sqlalchemy import func
    last = db.session.query(func.max(Comanda.codigo)).filter_by(studio_id=sid()).scalar()
    return (last or 0) + 1


@admin_bp.route('/financeiro/comandas/nova', methods=['GET', 'POST'])
@login_required
def comanda_nova():
    from datetime import date
    if request.method == 'POST':
        c = Comanda(studio_id=sid(), codigo=_next_codigo())
        if _save_comanda(c):
            db.session.add(c)
            db.session.commit()
            flash('Comanda criada.', 'success')
            return redirect(url_for('admin.comanda_detalhe', comanda_id=c.id))
    profs    = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(studio_id=sid(), ativo=True).order_by(Servico.nome).all()
    unidades = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    clientes = Cliente.query.filter_by(studio_id=sid()).order_by(Cliente.nome).all()
    return render_template('admin/comanda_form.html',
        c=None, profs=profs, servicos=servicos, unidades=unidades,
        clientes=clientes, formas=FORMA_PAGAMENTO, hoje=date.today().isoformat())


@admin_bp.route('/financeiro/comandas/<int:comanda_id>', methods=['GET', 'POST'])
@login_required
def comanda_detalhe(comanda_id):
    from datetime import date
    c = Comanda.query.filter_by(id=comanda_id, studio_id=sid()).first_or_404()
    if request.method == 'POST':
        if _save_comanda(c):
            db.session.commit()
            flash('Comanda atualizada.', 'success')
            return redirect(url_for('admin.comanda_detalhe', comanda_id=c.id))
    profs    = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(studio_id=sid(), ativo=True).order_by(Servico.nome).all()
    unidades = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    clientes = Cliente.query.filter_by(studio_id=sid()).order_by(Cliente.nome).all()
    return render_template('admin/comanda_form.html',
        c=c, profs=profs, servicos=servicos, unidades=unidades,
        clientes=clientes, formas=FORMA_PAGAMENTO, hoje=date.today().isoformat())


def _save_comanda(c):
    from datetime import date
    from decimal import Decimal as D
    data_str = request.form.get('data', '').strip()
    if not data_str:
        flash('Data é obrigatória.', 'error')
        return False
    try:
        c.data = date.fromisoformat(data_str)
    except ValueError:
        flash('Data inválida.', 'error')
        return False
    c.nome_cliente = request.form.get('nome_cliente', '').strip() or None
    c.observacoes  = request.form.get('observacoes', '').strip() or None
    c.status       = request.form.get('status', 'aberta')
    cid = request.form.get('cliente_id', '')
    uid = request.form.get('unidade_id', '')
    pid = request.form.get('profissional_id', '')
    c.cliente_id      = int(cid) if cid else None
    c.unidade_id      = int(uid) if uid else None
    c.profissional_id = int(pid) if pid else None
    desc = request.form.get('desconto', '0').strip().replace(',', '.')
    try:
        c.desconto = D(desc)
    except Exception:
        c.desconto = 0

    descs   = request.form.getlist('item_descricao')
    valors  = request.form.getlist('item_valor')
    qtds    = request.form.getlist('item_quantidade')
    svcs    = request.form.getlist('item_servico_id')
    vpitems = request.form.getlist('item_venda_pacote_item_id')

    ids_antes = {i.venda_pacote_item_id for i in c.itens if i.venda_pacote_item_id}
    c.itens.clear()

    ids_depois = set()
    novos_itens = []
    for i, desc_i in enumerate(descs):
        desc_i = desc_i.strip()
        if not desc_i:
            continue
        try:
            val    = D(valors[i].strip().replace(',', '.')) if i < len(valors) else D('0')
            qtd    = int(qtds[i]) if i < len(qtds) and qtds[i] else 1
            svc_id = int(svcs[i]) if i < len(svcs) and svcs[i] else None
            vp_id  = int(vpitems[i]) if i < len(vpitems) and vpitems[i] else None
        except Exception:
            continue
        if vp_id:
            ids_depois.add(vp_id)
        novos_itens.append(ComandaItem(
            descricao=desc_i, valor=val, quantidade=qtd,
            servico_id=svc_id, venda_pacote_item_id=vp_id))
    c.itens.extend(novos_itens)

    for vp_id in ids_depois - ids_antes:
        vpi = db.session.get(VendaPacoteItem, vp_id)
        if vpi and vpi.quantidade_usada < vpi.quantidade_total:
            vpi.quantidade_usada += 1
            if vpi.venda.sessoes_restantes <= 0:
                vpi.venda.status = 'concluido'

    for vp_id in ids_antes - ids_depois:
        vpi = db.session.get(VendaPacoteItem, vp_id)
        if vpi and vpi.quantidade_usada > 0:
            vpi.quantidade_usada -= 1
            if vpi.venda.status == 'concluido':
                vpi.venda.status = 'ativo'
    return True


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/pagamento', methods=['POST'])
@login_required
def comanda_pagamento_add(comanda_id):
    from datetime import date
    from decimal import Decimal
    c = Comanda.query.filter_by(id=comanda_id, studio_id=sid()).first_or_404()
    forma    = request.form.get('forma_pagamento', '').strip()
    valor_s  = request.form.get('valor', '').strip().replace(',', '.')
    parcelas = request.form.get('parcelas', '1')
    if not forma or not valor_s:
        flash('Informe forma e valor.', 'error')
        return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
    try:
        valor = Decimal(valor_s)
        if valor <= 0:
            flash('Valor deve ser positivo.', 'error')
            return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
        saldo_antes = c.saldo
        if forma == 'saldo_cliente':
            if not c.cliente_id:
                flash('Vincule um cliente à comanda para usar saldo.', 'error')
                return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
            saldo_disp = c.cliente.saldo or Decimal('0')
            if saldo_disp <= 0:
                flash('Cliente não possui crédito.', 'error')
                return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
            if valor > saldo_disp:
                flash(f'Valor excede o crédito disponível (R$ {saldo_disp:.2f}).', 'error')
                return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))
            c.cliente.saldo = saldo_disp - valor
        p = PagamentoComanda(
            comanda_id=c.id, forma_pagamento=forma, valor=valor,
            parcelas=int(parcelas) if parcelas.isdigit() else 1,
            data_pagamento=date.today(),
        )
        db.session.add(p)
        if saldo_antes - valor <= 0:
            _fechar_comanda(c, saldo_override=saldo_antes - valor)
        db.session.commit()
        flash('Pagamento registrado.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Erro: {exc}', 'error')
    return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/pagamento/<int:pag_id>/excluir', methods=['POST'])
@login_required
def comanda_pagamento_excluir(comanda_id, pag_id):
    from decimal import Decimal
    p = PagamentoComanda.query.get_or_404(pag_id)
    c = Comanda.query.filter_by(id=comanda_id, studio_id=sid()).first_or_404()
    if c.status == 'fechada':
        _reabrir_comanda(c)
    if p.forma_pagamento == 'saldo_cliente' and c.cliente_id:
        c.cliente.saldo = (c.cliente.saldo or Decimal('0')) + p.valor
    db.session.delete(p)
    db.session.commit()
    flash('Pagamento removido.', 'success')
    return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/fechar', methods=['POST'])
@login_required
def comanda_fechar(comanda_id):
    c = Comanda.query.filter_by(id=comanda_id, studio_id=sid()).first_or_404()
    _fechar_comanda(c)
    db.session.commit()
    flash('Comanda fechada.', 'success')
    return redirect(url_for('admin.comanda_detalhe', comanda_id=comanda_id))


@admin_bp.route('/financeiro/comandas/<int:comanda_id>/excluir', methods=['POST'])
@login_required
def comanda_excluir(comanda_id):
    c = Comanda.query.filter_by(id=comanda_id, studio_id=sid()).first_or_404()
    db.session.delete(c)
    db.session.commit()
    flash('Comanda excluída.', 'success')
    return redirect(url_for('admin.financeiro_comandas'))


def _fechar_comanda(c, saldo_override=None):
    from decimal import Decimal
    saldo_rest = saldo_override if saldo_override is not None else c.saldo
    c.status = 'fechada'
    if c.cliente_id and saldo_rest != 0:
        c.saldo_ajustado = saldo_rest
        c.cliente.saldo  = (c.cliente.saldo or Decimal('0')) - saldo_rest


def _reabrir_comanda(c):
    from decimal import Decimal
    if c.saldo_ajustado is not None and c.cliente_id:
        c.cliente.saldo = (c.cliente.saldo or Decimal('0')) + c.saldo_ajustado
        c.saldo_ajustado = None
    c.status = 'aberta'


# ── Vendas de Pacote ─────────────────────────────────────────────────────────

@admin_bp.route('/financeiro/vendas-pacote')
@login_required
def vendas_pacote():
    q     = request.args.get('q', '').strip()
    query = VendaPacote.query.filter_by(studio_id=sid())
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

    pacotes_obj = Pacote.query.filter_by(studio_id=sid(), ativo=True).order_by(Pacote.nome).all()
    clientes    = Cliente.query.filter_by(studio_id=sid()).order_by(Cliente.nome).all()
    profs       = Profissional.query.filter_by(studio_id=sid(), ativo=True).order_by(Profissional.nome).all()
    unidades    = Unidade.query.filter_by(studio_id=sid(), ativo=True).order_by(Unidade.nome).all()
    hoje        = date.today()

    pacotes_json = {
        p.id: {
            'nome': p.nome, 'valor_total': float(p.valor_total),
            'itens': [{'id': it.id, 'servico_id': it.servico_id,
                       'servico_nome': it.servico.nome,
                       'quantidade': it.quantidade,
                       'valor_unitario': float(it.valor_unitario)} for it in p.itens],
        } for p in pacotes_obj
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
        else:
            pacote = Pacote.query.filter_by(id=int(pacote_id), studio_id=sid()).first_or_404()
            try:
                data_venda = date.fromisoformat(data_str) if data_str else hoje
            except ValueError:
                data_venda = hoje
            valor_s = request.form.get('valor_total', '').strip().replace(',', '.')
            try:
                valor_venda = Decimal(valor_s) if valor_s else pacote.valor_total
            except Exception:
                valor_venda = pacote.valor_total

            comanda = Comanda(
                studio_id=sid(), codigo=_next_codigo(), data=data_venda,
                nome_cliente=nome_cli or None,
                cliente_id=int(cliente_id) if cliente_id else None,
                profissional_id=int(prof_id) if prof_id else None,
                unidade_id=int(unid_id) if unid_id else None,
                observacoes=f'Venda de pacote: {pacote.nome}', status='aberta',
            )
            comanda.itens.append(ComandaItem(
                descricao=f'Pacote: {pacote.nome}', valor=valor_venda, quantidade=1))
            db.session.add(comanda)
            db.session.flush()

            venda = VendaPacote(
                studio_id=sid(), pacote_id=pacote.id,
                cliente_id=int(cliente_id) if cliente_id else None,
                nome_cliente=nome_cli or None, comanda_id=comanda.id,
                data_venda=data_venda, nome_pacote=pacote.nome,
                valor_total=valor_venda, status='ativo',
            )
            for item in pacote.itens:
                qtd_key = f'qtd_item_{item.id}'
                try:
                    qtd = max(1, int(request.form.get(qtd_key, item.quantidade)))
                except ValueError:
                    qtd = item.quantidade
                venda.itens.append(VendaPacoteItem(
                    pacote_item_id=item.id, servico_id=item.servico_id,
                    descricao=item.servico.nome,
                    quantidade_total=qtd, quantidade_usada=0,
                ))
            db.session.add(venda)
            db.session.commit()
            flash(f'Pacote "{pacote.nome}" vendido! Comanda #{comanda.codigo} criada.', 'success')
            return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda.id))

    return render_template('admin/venda_pacote_form.html',
                           pacotes=pacotes_obj, pacotes_json=pacotes_json,
                           clientes=clientes, profs=profs,
                           unidades=unidades, hoje=hoje.isoformat())


@admin_bp.route('/financeiro/vendas-pacote/<int:venda_id>')
@login_required
def venda_pacote_detalhe(venda_id):
    v = VendaPacote.query.filter_by(id=venda_id, studio_id=sid()).first_or_404()
    return render_template('admin/venda_pacote_detalhe.html', v=v)


@admin_bp.route('/financeiro/vendas-pacote/<int:venda_id>/itens/<int:item_id>/usar', methods=['POST'])
@login_required
def venda_pacote_usar_sessao(venda_id, item_id):
    venda = VendaPacote.query.filter_by(id=venda_id, studio_id=sid()).first_or_404()
    item  = VendaPacoteItem.query.get_or_404(item_id)
    if item.venda_pacote_id != venda_id:
        flash('Item não pertence à venda.', 'error')
        return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))
    qtd = int(request.form.get('quantidade', 1))
    if item.quantidade_usada + qtd > item.quantidade_total:
        flash('Quantidade excede as sessões disponíveis.', 'error')
        return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))
    item.quantidade_usada += qtd
    if venda.sessoes_restantes <= 0:
        venda.status = 'concluido'
    db.session.commit()
    flash('Sessão registrada.', 'success')
    return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))


@admin_bp.route('/financeiro/vendas-pacote/<int:venda_id>/cancelar', methods=['POST'])
@login_required
def venda_pacote_cancelar(venda_id):
    v = VendaPacote.query.filter_by(id=venda_id, studio_id=sid()).first_or_404()
    v.status = 'cancelado'
    db.session.commit()
    flash('Venda de pacote cancelada.', 'success')
    return redirect(url_for('admin.venda_pacote_detalhe', venda_id=venda_id))


# ── Usuários ──────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios')
@login_required
def users():
    all_users = User.query.filter_by(studio_id=sid()).order_by(User.name).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/usuarios/novo', methods=['GET', 'POST'])
@login_required
def user_new():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        phone    = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        if not all([name, username, email, password]):
            flash('Preencha todos os campos obrigatórios.', 'error')
        elif User.query.filter_by(studio_id=sid(), username=username).first():
            flash('Nome de usuário já existe.', 'error')
        else:
            u = User(studio_id=sid(), name=name, username=username, email=email, phone=phone)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash('Usuário criado.', 'success')
            return redirect(url_for('admin.users'))
    return render_template('admin/user_form.html', u=None)


@admin_bp.route('/usuarios/<int:user_id>', methods=['GET', 'POST'])
@login_required
def user_edit(user_id):
    u = User.query.filter_by(id=user_id, studio_id=sid()).first_or_404()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete' and u.id != current_user.id:
            db.session.delete(u)
            db.session.commit()
            flash('Usuário excluído.', 'success')
            return redirect(url_for('admin.users'))
        u.name  = request.form.get('name', u.name).strip()
        u.email = request.form.get('email', u.email).strip()
        u.phone = request.form.get('phone', '').strip() or None
        pw = request.form.get('password', '')
        if pw:
            u.set_password(pw)
        db.session.commit()
        flash('Usuário atualizado.', 'success')
        return redirect(url_for('admin.users'))
    return render_template('admin/user_form.html', u=u)


@admin_bp.route('/usuarios/<int:user_id>/excluir', methods=['POST'])
@login_required
def user_delete(user_id):
    u = User.query.filter_by(id=user_id, studio_id=sid()).first_or_404()
    if u.id == current_user.id:
        flash('Você não pode excluir a si mesmo.', 'error')
        return redirect(url_for('admin.users'))
    db.session.delete(u)
    db.session.commit()
    flash('Usuário excluído.', 'success')
    return redirect(url_for('admin.users'))


# ── Configurações (tema + IA) ─────────────────────────────────────────────────

@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    studio = current_user.studio

    if request.method == 'POST':
        section = request.form.get('section', '')

        if section == 'tema':
            theme_key = request.form.get('theme_key', 'default')
            _set_config(studio, 'active_theme', theme_key)
            db.session.commit()
            flash('Tema atualizado.', 'success')

        elif section == 'ia':
            provider = request.form.get('ai_provider', '').strip()
            api_key  = request.form.get('ai_api_key', '').strip()
            model    = request.form.get('ai_model', '').strip()
            _set_config(studio, 'ai_provider', provider)
            if api_key and api_key != '••••••••':
                _set_config(studio, 'ai_api_key', api_key)
            _set_config(studio, 'ai_model', model)
            db.session.commit()
            flash('Configurações de IA salvas.', 'success')

        elif section == 'studio':
            nome = request.form.get('studio_nome', '').strip()
            if nome:
                studio.nome = nome
            for cfg_key in ('telefone', 'cidade', 'email', 'birthday_message'):
                form_key = f'studio_{cfg_key}' if cfg_key != 'birthday_message' else 'birthday_message'
                val = request.form.get(form_key, '').strip()
                _set_config(studio, cfg_key, val)
            db.session.commit()
            flash('Dados do studio atualizados.', 'success')

        return redirect(url_for('admin.configuracoes'))

    ai_provider = studio.get_config('ai_provider', '')
    ai_key_set  = bool(studio.get_config('ai_api_key', ''))
    ai_model    = studio.get_config('ai_model', '')
    theme_key   = studio.get_config('active_theme', 'default')

    return render_template('admin/configuracoes.html',
        studio=studio, themes=THEMES, theme_key=theme_key,
        ai_providers=AI_PROVIDERS, ai_provider=ai_provider,
        ai_key_set=ai_key_set, ai_model=ai_model)


def _set_config(studio, key, value):
    cfg = StudioConfig.query.filter_by(studio_id=studio.id, key=key).first()
    if cfg:
        cfg.value = value
    else:
        db.session.add(StudioConfig(studio_id=studio.id, key=key, value=value))


@admin_bp.route('/api/configuracoes/testar-ia', methods=['POST'])
@login_required
def api_testar_ia():
    studio   = current_user.studio
    provider = studio.get_config('ai_provider', '')
    api_key  = studio.get_config('ai_api_key', '')
    model    = studio.get_config('ai_model', '')

    if not api_key:
        return jsonify({'ok': False, 'erro': 'Chave de API não configurada.'})

    try:
        if provider == 'anthropic':
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp   = client.messages.create(
                model=model or 'claude-haiku-4-5-20251001',
                max_tokens=10,
                messages=[{'role': 'user', 'content': 'ping'}],
            )
            return jsonify({'ok': True, 'msg': f'Conexão OK — {resp.model}'})

        elif provider == 'openai':
            import openai
            client = openai.OpenAI(api_key=api_key)
            resp   = client.chat.completions.create(
                model=model or 'gpt-4o-mini',
                max_tokens=5,
                messages=[{'role': 'user', 'content': 'ping'}],
            )
            return jsonify({'ok': True, 'msg': f'Conexão OK — {resp.model}'})

        else:
            return jsonify({'ok': False, 'erro': f'Provider "{provider}" não suportado para teste.'})

    except Exception as e:
        return jsonify({'ok': False, 'erro': str(e)})


# ── Métricas ──────────────────────────────────────────────────────────────────

@admin_bp.route('/metricas')
@login_required
def metrics():
    from datetime import date
    hoje  = date.today()
    mes_i = hoje.replace(day=1)
    total_clientes    = Cliente.query.filter_by(studio_id=sid()).count()
    total_agendamentos = Agendamento.query.filter_by(studio_id=sid()).filter(
        Agendamento.data >= mes_i).count()
    return render_template('admin/metrics.html',
        total_clientes=total_clientes, total_agendamentos=total_agendamentos,
        hoje=hoje)


# ── Temas ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/temas')
@login_required
def themes():
    theme_key = current_user.studio.get_config('active_theme', 'default')
    return render_template('admin/themes.html', themes=THEMES, active=theme_key)


@admin_bp.route('/temas/<key>', methods=['POST'])
@login_required
def theme_set(key):
    if key in THEMES:
        studio = current_user.studio
        _set_config(studio, 'active_theme', key)
        db.session.commit()
        flash(f'Tema "{THEMES[key]["name"]}" aplicado.', 'success')
    return redirect(url_for('admin.themes'))
