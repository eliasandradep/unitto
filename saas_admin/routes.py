from flask import render_template, redirect, url_for, request, flash
from datetime import date

from . import saas_bp
from models import db, Empresa, User


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
