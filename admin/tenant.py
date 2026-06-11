"""
Tenant context utilities — Etapa 2 do plano multi-tenancy.

set_tenant_context(): detecta o tenant e popula g.empresa / g.empresa_id.
tenant_required():    decorator que garante tenant antes da view.
tq(model):            query helper que injeta o filtro de tenant
                      (pronto para a Etapa 4, quando empresa_id chegar
                      nas tabelas de negócio).
"""

from functools import wraps
from flask import g, abort, request


# ── Settings por tenant ───────────────────────────────────────────────────────

def get_setting(key: str, default: str = '') -> str:
    """Lê uma setting com fallback: tenant → global (empresa_id=None)."""
    from models import Setting
    eid = g.get('empresa_id')
    s = Setting.query.filter_by(key=key, empresa_id=eid).first()
    if s is None and eid is not None:
        s = Setting.query.filter_by(key=key, empresa_id=None).first()
    return s.value if s else default


def save_setting(key: str, value: str) -> None:
    """Grava uma setting no escopo do tenant atual."""
    from models import db, Setting
    eid = g.get('empresa_id')
    s = Setting.query.filter_by(key=key, empresa_id=eid).first()
    if s:
        s.value = value
    else:
        db.session.add(Setting(key=key, empresa_id=eid, value=value))
    db.session.commit()


def set_tenant_context():
    """
    Popula g.empresa e g.empresa_id com base na request atual.

    Estratégias (em ordem de prioridade):
      1. Subdomínio       → renatarosa.seuapp.com.br
      2. Prefixo de path  → /t/renatarosa/admin/...
      3. Usuário logado   → current_user.empresa_id
      4. Fallback         → única empresa ativa (compatibilidade durante migração)
    """
    from models import Empresa

    g.empresa    = None
    g.empresa_id = None

    # 1. Subdomínio: slug.dominio.tld
    host  = request.host.split(':')[0]
    parts = host.split('.')
    if len(parts) >= 3 and parts[0] not in ('www', 'api', 'mail', 'static'):
        emp = Empresa.query.filter_by(slug=parts[0], status='ativa').first()
        if emp:
            g.empresa    = emp
            g.empresa_id = emp.id
            return

    # 2. Prefixo de path: /t/{slug}/...
    path_parts = request.path.strip('/').split('/')
    if len(path_parts) >= 2 and path_parts[0] == 't':
        emp = Empresa.query.filter_by(slug=path_parts[1], status='ativa').first()
        if emp:
            g.empresa    = emp
            g.empresa_id = emp.id
            return

    # 3. Usuário autenticado: usa a empresa do cadastro
    try:
        from flask_login import current_user
        if current_user.is_authenticated and current_user.empresa_id:
            g.empresa    = current_user.empresa
            g.empresa_id = current_user.empresa_id
            return
    except Exception:
        pass

    # 4. Fallback: primeira empresa ativa (período de migração / instalação única)
    try:
        emp = Empresa.query.filter_by(status='ativa').order_by(Empresa.id).first()
        if emp:
            g.empresa    = emp
            g.empresa_id = emp.id
    except Exception:
        pass


def tenant_required(f):
    """
    Garante que g.empresa está definido antes de executar a view.
    Retorna 404 se nenhum tenant for encontrado.
    Será aplicado nas rotas na Etapa 4.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.get('empresa'):
            abort(404)
        return f(*args, **kwargs)
    return decorated


def register_tenant_auto_fill(app, db):
    """
    Registra event listener que auto-preenche empresa_id em todos os novos
    registros inseridos durante uma request admin, sem precisar alterar cada
    chamada de construtor individualmente.
    """
    from sqlalchemy import event

    @event.listens_for(db.session, 'before_flush')
    def _auto_empresa_id(session, flush_context, instances):
        try:
            from flask import g
            eid = g.get('empresa_id')
        except RuntimeError:
            return
        if eid is None:
            return
        for obj in session.new:
            try:
                mapper_cols = {c.key for c in obj.__mapper__.column_attrs}
                if 'empresa_id' in mapper_cols and getattr(obj, 'empresa_id', None) is None:
                    obj.empresa_id = eid
            except Exception:
                pass


def tq(model):
    """
    Tenant-scoped query helper. Substitui Model.query nas rotas admin.

    Uso:
        tq(Cliente).filter_by(nome='Ana').all()

    Enquanto empresa_id não existir nas tabelas de negócio (Etapas 3+),
    retorna Model.query sem filtro — comportamento idêntico ao atual.
    """
    empresa_id = g.get('empresa_id')
    if empresa_id is None:
        return model.query
    # Filtra apenas se o modelo tiver a coluna empresa_id (Etapa 3+)
    mapper_cols = {c.key for c in model.__mapper__.column_attrs}
    if 'empresa_id' not in mapper_cols:
        return model.query
    return model.query.filter_by(empresa_id=empresa_id)
