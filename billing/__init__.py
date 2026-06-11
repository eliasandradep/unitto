from flask import Blueprint

billing_bp = Blueprint('billing', __name__,
                       url_prefix='/billing',
                       template_folder='../templates/billing')

from admin.tenant import set_tenant_context


@billing_bp.before_request
def _set_tenant():
    set_tenant_context()


@billing_bp.context_processor
def _inject_empresa():
    from flask import g
    return {'empresa': g.get('empresa')}


from . import routes  # noqa: F401, E402
