import os
import uuid
from datetime import datetime, timedelta, date
from flask import render_template, redirect, url_for, request, flash, jsonify, g, make_response
from flask_login import login_required, current_user

from . import billing_bp
from . import infinitepay as ip
from models import db, Plano, Assinatura, Empresa, CobrancaInfinitePay

try:
    import stripe
    STRIPE_OK = True
except ImportError:
    STRIPE_OK = False


def _stripe_api_key():
    if STRIPE_OK:
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')


def _payment_provider():
    return os.getenv('PAYMENT_PROVIDER', 'stripe').strip().lower()


# ── Tabela de planos (pública) ────────────────────────────────────────────────

@billing_bp.route('/planos')
def planos():
    todos = Plano.query.filter_by(ativo=True).order_by(Plano.ordem).all()
    assinatura = None
    if current_user.is_authenticated and g.get('empresa'):
        assinatura = Assinatura.query.filter_by(empresa_id=g.empresa.id).first()
    resp = make_response(render_template('billing/planos.html', planos=todos, assinatura=assinatura))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


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
    plano_id = request.form.get('plano_id', type=int)
    if not plano_id:
        flash('Selecione um plano válido.', 'error')
        return redirect(url_for('billing.planos'))
    plano = db.get_or_404(Plano, plano_id)

    if _payment_provider() == 'infinitepay':
        return _checkout_infinitepay(plano)
    return _checkout_stripe(plano)


def _checkout_infinitepay(plano):
    if not ip.configurado():
        flash('Integração InfinitePay não configurada. Entre em contato para assinar.', 'error')
        return redirect(url_for('billing.planos'))

    empresa = g.get('empresa') or current_user.empresa
    if not empresa:
        flash('Não foi possível identificar sua empresa. Entre em contato com o suporte.', 'error')
        return redirect(url_for('billing.planos'))

    order_nsu = f'unitto-{empresa.id}-{plano.id}-{uuid.uuid4().hex[:10]}'

    try:
        checkout_url, valor_centavos = ip.criar_checkout_link(
            empresa, plano, order_nsu,
            redirect_url=url_for('billing.checkout_sucesso', _external=True),
            webhook_url=url_for('billing.webhook_infinitepay', _external=True),
        )

        db.session.add(CobrancaInfinitePay(
            empresa_id=empresa.id, plano_id=plano.id, order_nsu=order_nsu,
            checkout_url=checkout_url, valor_centavos=valor_centavos, status='pendente',
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao gerar link de pagamento InfinitePay: {e}', 'error')
        return redirect(url_for('billing.planos'))

    return redirect(checkout_url, code=303)


def _checkout_stripe(plano):
    if not STRIPE_OK or not os.getenv('STRIPE_SECRET_KEY'):
        flash('Integração Stripe não configurada. Entre em contato para assinar.', 'error')
        return redirect(url_for('billing.planos'))

    _stripe_api_key()
    plano_id = plano.id
    periodo  = plano.tipo or 'mensal'
    price_id = plano.stripe_price_id

    if not price_id:
        flash('Este plano ainda não está disponível para pagamento online.', 'error')
        return redirect(url_for('billing.planos'))

    empresa = g.get('empresa') or current_user.empresa
    if not empresa:
        flash('Não foi possível identificar sua empresa. Entre em contato com o suporte.', 'error')
        return redirect(url_for('billing.planos'))

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
    # Fallback caso o webhook da InfinitePay não tenha chegado ainda: a própria
    # redirect_url volta com order_nsu/transaction_nsu/slug, então confirmamos
    # o pagamento diretamente com a InfinitePay antes de confiar no webhook.
    order_nsu = request.args.get('order_nsu')
    if order_nsu:
        try:
            cobranca = CobrancaInfinitePay.query.filter_by(order_nsu=order_nsu).first()
            if cobranca and cobranca.status != 'paga':
                resultado = ip.verificar_pagamento(
                    order_nsu,
                    request.args.get('transaction_nsu'),
                    request.args.get('slug'),
                )
                if resultado.get('paid'):
                    cobranca.status          = 'paga'
                    cobranca.transaction_nsu = request.args.get('transaction_nsu')
                    cobranca.invoice_slug    = request.args.get('slug')
                    cobranca.paid_at         = datetime.utcnow()
                    _ativar_assinatura_infinitepay(cobranca)
                    db.session.commit()
        except Exception:
            db.session.rollback()  # webhook continua sendo o caminho principal

    flash('Assinatura ativada com sucesso! Bem-vindo(a) ao seu plano.', 'success')
    return redirect(url_for('billing.gerenciar'))


# ── Renovar (trial expirado / assinatura vencida) ────────────────────────────

@billing_bp.route('/renovar')
def renovar():
    todos = Plano.query.filter_by(ativo=True).order_by(Plano.ordem).all()
    empresa = g.get('empresa')
    resp = make_response(render_template('billing/renovar.html', planos=todos, empresa=empresa))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


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


# ── Webhook InfinitePay ───────────────────────────────────────────────────────

@billing_bp.route('/webhook/infinitepay', methods=['POST'])
def webhook_infinitepay():
    data = request.get_json(silent=True) or {}
    order_nsu = data.get('order_nsu')

    cobranca = CobrancaInfinitePay.query.filter_by(order_nsu=order_nsu).first()
    if not cobranca:
        return jsonify({'success': False, 'message': 'order_nsu não encontrado'}), 200

    if cobranca.status != 'paga':
        cobranca.status          = 'paga'
        cobranca.invoice_slug    = data.get('invoice_slug')
        cobranca.transaction_nsu = data.get('transaction_nsu')
        cobranca.paid_at         = datetime.utcnow()
        _ativar_assinatura_infinitepay(cobranca)
        db.session.commit()

    return jsonify({'success': True, 'message': None}), 200


def _ativar_assinatura_infinitepay(cobranca):
    plano   = cobranca.plano
    empresa = cobranca.empresa
    dias    = 365 if plano.tipo == 'anual' else 30
    vencimento = date.today() + timedelta(days=dias)

    assin = Assinatura.query.filter_by(empresa_id=empresa.id).first()
    if assin:
        assin.plano_id           = plano.id
        assin.status             = 'ativa'
        assin.periodo            = plano.tipo
        assin.provider           = 'infinitepay'
        assin.proximo_vencimento = vencimento
    else:
        db.session.add(Assinatura(
            empresa_id=empresa.id, plano_id=plano.id, status='ativa',
            periodo=plano.tipo, provider='infinitepay',
            proximo_vencimento=vencimento,
        ))

    empresa.plano  = plano.slug
    empresa.status = 'ativa'
