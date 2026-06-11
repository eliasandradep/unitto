from flask import Blueprint, g, request

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

from .tenant import set_tenant_context


@admin_bp.before_request
def _set_tenant():
    set_tenant_context()


# Endpoints que não precisam de assinatura ativa
_SKIP_SUBSCRIPTION_CHECK = frozenset({
    'admin.login', 'admin.logout', 'admin.setup',
    'admin.boas_vindas',
})


@admin_bp.before_request
def _check_assinatura():
    """Redireciona para /billing/renovar se o trial/assinatura estiver vencido."""
    from flask_login import current_user
    from flask import redirect, url_for

    if not current_user.is_authenticated:
        return

    # saas_admin não tem empresa, pula
    if current_user.role == 'saas_admin':
        return

    if request.endpoint in _SKIP_SUBSCRIPTION_CHECK:
        return

    empresa = g.get('empresa')
    if not empresa:
        return

    if empresa.is_ativa():
        return  # trial válido ou plano pago ativo

    # Verifica se existe assinatura paga ativa
    try:
        from models import Assinatura
        assin = Assinatura.query.filter_by(empresa_id=empresa.id, status='ativa').first()
        if assin:
            return
    except Exception:
        return

    return redirect(url_for('billing.renovar'))


@admin_bp.context_processor
def _inject_empresa():
    """Disponibiliza 'empresa', 'setup_pendente' e 'theme_css' por tenant."""
    from .tenant import get_setting
    from themes import get_theme_css

    empresa = g.get('empresa')

    # Tema isolado por tenant — sobrescreve o global injetado por inject_globals
    try:
        theme_key = get_setting('active_theme', 'default')
        theme_css = get_theme_css(theme_key)
    except Exception:
        theme_css = ''

    setup_pendente = False
    if empresa:
        try:
            from models import Profissional, Expediente, Servico
            eid = empresa.id
            setup_pendente = not all([
                Profissional.query.filter_by(empresa_id=eid, ativo=True).count() > 0,
                Expediente.query.filter_by(empresa_id=eid).count() > 0,
                Servico.query.filter_by(empresa_id=eid, ativo=True).count() > 0,
            ])
        except Exception:
            pass

    return {'empresa': empresa, 'setup_pendente': setup_pendente, 'theme_css': theme_css}


from . import routes  # noqa: F401, E402
