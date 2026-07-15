import os
from datetime import datetime
from flask import render_template, redirect, url_for, request, flash, jsonify, g
from flask_login import login_required, current_user

from . import billing_bp
from models import db, Plano, Assinatura, Empresa

try:
    import stripe
    STRIPE_OK = True
except ImportError:
    STRIPE_OK = False


def _stripe_api_key():
    if STRIPE_OK:
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')


# ── Tabela de planos (pública) ────────────────────────────────────────────────

@billing_bp.route('/planos')
def planos():
    todos = Plano.query.filter_by(ativo=True).order_by(Plano.ordem).all()
    assinatura = None
    if current_user.is_authenticated and g.get('empresa'):
        assinatura = Assinatura.query.filter_by(empresa_id=g.empresa.id).first()
    return render_template('billing/planos.html', planos=todos, assinatura=assinatura)


# ── Painel do assinante ───────────────────────────────────────────────────────

@billing_bp.route('/gerenciar')
@login_required
def gerenciar():
    empresa = g.get('empresa') or current_user.empresa
    assinatura = Assinatura.query.filter_by(empresa_id=empresa.id).first()
    todos = Plano.query.filter_by(ativo=True).order_by(Plano.ordem).all()
    return render_template('billing/gerenciar.html',
                           assinatura=assinatura, planos=todos, empresa=empresa)


@billing_bp.route('/portal', methods=['POST'])
@login_required
def portal():
    """Redireciona para o Stripe Customer Portal."""
    if not STRIPE_OK:
        flash('Integração Stripe não configurada.', 'error')
        return redirect(url_for('billing.gerenciar'))

    _stripe_api_key()
    empresa = g.get('empresa') or current_user.empresa
    assinatura = Assinatura.query.filter_by(empresa_id=empresa.id).first()

    if not assinatura or not assinatura.stripe_customer_id:
        flash('Nenhuma assinatura Stripe encontrada.', 'error')
        return redirect(url_for('billing.gerenciar'))

    try:
        session = stripe.billing_portal.Session.create(
            customer=assinatura.stripe_customer_id,
            return_url=url_for('billing.gerenciar', _external=True),
        )
        return redirect(session.url)
    except Exception as e:
        flash(f'Erro ao abrir portal Stripe: {e}', 'error')
        return redirect(url_for('billing.gerenciar'))


# ── Checkout ──────────────────────────────────────────────────────────────────

@billing_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    if not STRIPE_OK or not os.getenv('STRIPE_SECRET_KEY'):
        flash('Integração Stripe não configurada. Entre em contato para assinar.', 'error')
        return redirect(url_for('billing.planos'))

    _stripe_api_key()
    plano_id = request.form.get('plano_id', type=int)

    plano = db.get_or_404(Plano, plano_id)
    periodo  = plano.tipo or 'mensal'
    price_id = plano.stripe_price_id

    if not price_id:
        flash('Este plano ainda não está disponível para pagamento online.', 'error')
        return redirect(url_for('billing.planos'))

    empresa = g.get('empresa') or current_user.empresa
    assinatura = Assinatura.query.filter_by(empresa_id=empresa.id).first()
    customer_id = assinatura.stripe_customer_id if assinatura else None

    try:
        if not customer_id:
            customer = stripe.Customer.create(
                email=empresa.email or current_user.email,
                name=empresa.nome,
                metadata={'empresa_id': str(empresa.id)},
            )
            customer_id = customer.id

        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url=url_for('billing.checkout_sucesso', _external=True)
                        + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('billing.gerenciar', _external=True),
            metadata={
                'empresa_id': str(empresa.id),
                'plano_id':   str(plano_id),
                'periodo':    periodo,
            },
        )
        return redirect(session.url, code=303)
    except Exception as e:
        flash(f'Erro ao criar sessão de pagamento: {e}', 'error')
        return redirect(url_for('billing.planos'))


@billing_bp.route('/checkout/sucesso')
@login_required
def checkout_sucesso():
    flash('Assinatura ativada com sucesso! Bem-vindo(a) ao seu plano.', 'success')
    return redirect(url_for('billing.gerenciar'))


# ── Renovar (trial expirado / assinatura vencida) ────────────────────────────

@billing_bp.route('/renovar')
def renovar():
    todos = Plano.query.filter_by(ativo=True).order_by(Plano.ordem).all()
    empresa = g.get('empresa')
    return render_template('billing/renovar.html', planos=todos, empresa=empresa)


# ── Webhook Stripe ────────────────────────────────────────────────────────────

@billing_bp.route('/webhook', methods=['POST'])
def webhook():
    if not STRIPE_OK:
        return jsonify({'error': 'Stripe not installed'}), 503

    _stripe_api_key()
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except Exception:
        return jsonify({'error': 'Invalid signature'}), 400

    try:
        _handle_event(event)
    except Exception:
        pass  # não bloquear o webhook por falha de processamento

    return jsonify({'received': True})


def _handle_event(event):
    obj  = event['data']['object']
    tipo = event['type']

    if tipo == 'checkout.session.completed':
        meta       = obj.get('metadata', {})
        empresa_id = int(meta.get('empresa_id') or 0)
        plano_id   = int(meta.get('plano_id')   or 0)
        customer_id    = obj.get('customer')
        subscription_id = obj.get('subscription')

        if not empresa_id:
            return

        pl_meta = db.session.get(Plano, plano_id)
        periodo = pl_meta.tipo if pl_meta else 'mensal'

        assin = Assinatura.query.filter_by(empresa_id=empresa_id).first()
        if assin:
            assin.plano_id               = plano_id
            assin.status                 = 'ativa'
            assin.periodo                = periodo
            assin.stripe_customer_id     = customer_id
            assin.stripe_subscription_id = subscription_id
        else:
            db.session.add(Assinatura(
                empresa_id=empresa_id, plano_id=plano_id, status='ativa',
                periodo=periodo, stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
            ))

        emp = db.session.get(Empresa, empresa_id)
        if emp:
            if pl_meta:
                emp.plano = pl_meta.slug
            emp.status = 'ativa'
        db.session.commit()

    elif tipo == 'customer.subscription.updated':
        sub_id = obj.get('id')
        assin  = Assinatura.query.filter_by(stripe_subscription_id=sub_id).first()
        if assin:
            status_map = {
                'active':   'ativa',
                'trialing': 'trial',
                'past_due': 'vencida',
                'canceled': 'cancelada',
                'unpaid':   'vencida',
            }
            assin.status = status_map.get(obj.get('status', ''), assin.status)
            period_end = obj.get('current_period_end')
            if period_end:
                assin.proximo_vencimento = datetime.utcfromtimestamp(period_end).date()
            db.session.commit()

    elif tipo == 'customer.subscription.deleted':
        sub_id = obj.get('id')
        assin  = Assinatura.query.filter_by(stripe_subscription_id=sub_id).first()
        if assin:
            assin.status = 'cancelada'
            emp = db.session.get(Empresa, assin.empresa_id)
            if emp:
                emp.status = 'suspensa'
            db.session.commit()

    elif tipo == 'invoice.payment_failed':
        cust_id = obj.get('customer')
        assin   = Assinatura.query.filter_by(stripe_customer_id=cust_id).first()
        if assin:
            assin.status = 'vencida'
            db.session.commit()
