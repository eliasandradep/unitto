from flask import Blueprint, abort, redirect, url_for

saas_bp = Blueprint('saas_admin', __name__,
                    url_prefix='/saas-admin',
                    template_folder='../templates/saas_admin')


@saas_bp.before_request
def _require_saas_admin():
    from flask import request
    from flask_login import current_user
    if request.endpoint == 'saas_admin.setup':
        return
    if not current_user.is_authenticated:
        return redirect(url_for('admin.login'))
    if current_user.role != 'saas_admin':
        abort(403)


from . import routes  # noqa: F401, E402
