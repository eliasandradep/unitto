from flask import Blueprint

meta_webhook_bp = Blueprint('meta_webhook', __name__, url_prefix='/integrations/meta')

from . import routes  # noqa: F401, E402
