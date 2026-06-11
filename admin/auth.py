"""
RBAC decorators — Etapa 5 do plano multi-tenancy.

require_role(*roles): garante que o usuário logado tem um dos papéis listados.
Redireciona para login se não autenticado, aborta 403 se papel insuficiente.
"""

from functools import wraps
from flask import abort, redirect, url_for
from flask_login import current_user


def require_role(*roles):
    """
    Uso:
        @require_role('empresa_admin')
        @require_role('saas_admin')
        @require_role('empresa_admin', 'saas_admin')
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('admin.login'))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator
