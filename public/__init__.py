from flask import Blueprint, g, request, abort

public_bp = Blueprint('public', __name__, template_folder='../templates/public')

from slug_utils import is_reserved_slug  # noqa: E402


@public_bp.before_request
def _set_public_tenant():
    from models import Empresa

    slug = (request.view_args or {}).get('slug')
    if not slug or is_reserved_slug(slug):
        abort(404)
    empresa = Empresa.query.filter_by(slug=slug).first()
    if not empresa:
        abort(404)
    g.empresa, g.empresa_id = empresa, empresa.id


from . import routes  # noqa: F401, E402
