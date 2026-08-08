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

# Endpoints reservados a perfil 'administrador' — telas de configuração/gestão
# do negócio, sem sentido para quem só atende clientes (Agenda/Comissões/
# Financeiro têm suas próprias regras de escopo, aplicadas nas rotas).
_ADMIN_ONLY_ENDPOINTS = frozenset({
    'dashboard',
    'leads', 'lead_new', 'lead_detail', 'lead_convert', 'lead_delete', 'lead_marcar_pessoal',
    'users', 'user_new', 'user_edit', 'user_delete',
    'metrics',
    'configuracoes',
    'themes', 'theme_set',
    'servicos', 'servicos_importar_csv', 'servico_novo', 'servico_detalhe',
    'categorias',
    'produtos', 'produto_novo', 'produto_detalhe', 'produto_categorias',
    'profissionais', 'profissional_novo', 'profissional_detalhe',
    'profissional_comissao_add', 'profissional_comissao_delete',
    'profissional_escala_data', 'profissional_escalas',
    'profissional_escala_add', 'profissional_escala_delete',
    'unidades',
    'expedientes', 'expediente_novo', 'expediente_detalhe', 'expediente_excluir',
    'boas_vindas',
    'pacotes', 'api_pacote_criar', 'api_pacote_detalhe', 'api_servico_preco',
    'api_cat_profissionais',
    'financeiro',
    'vendas_pacote', 'venda_pacote_nova', 'venda_pacote_detalhe',
    'venda_pacote_usar_sessao', 'venda_pacote_cancelar',
    'contas_pagar', 'conta_pagar_baixa', 'conta_pagar_excluir',
    'contas_receber', 'conta_receber_baixa', 'conta_receber_excluir',
    'formas_pagamento',
    'integracoes', 'integracoes_meta_conectar', 'integracoes_meta_callback',
    'integracoes_meta_desconectar',
    'integracoes_meta_ads_conectar', 'integracoes_meta_ads_callback',
    'integracoes_meta_ads_sincronizar', 'integracoes_meta_ads_desconectar',
    'contatos_ignorados', 'contato_ignorado_remover',
    'campanhas',
})


@admin_bp.before_request
def _check_perfil_acesso():
    """Bloqueia áreas administrativas para perfis não-administrador."""
    from flask_login import current_user
    from flask import abort

    if not current_user.is_authenticated:
        return
    if request.endpoint is None or not request.endpoint.startswith('admin.'):
        return

    view = request.endpoint.split('.', 1)[1]
    if view in _ADMIN_ONLY_ENDPOINTS:
        from .permissions import is_administrador
        if not is_administrador():
            abort(403)


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
        return  # trial válido ou plano pago dentro do prazo de vencimento

    # Assinatura paga vencida: marca como tal para refletir no painel do SaaS Admin
    try:
        from models import db, Assinatura
        assin = Assinatura.query.filter_by(empresa_id=empresa.id, status='ativa').first()
        if assin:
            assin.status = 'vencida'
            db.session.commit()
    except Exception:
        pass

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
    profissionais_limite_atingido = False
    if empresa:
        try:
            from models import Profissional, Expediente, Servico
            eid = empresa.id
            n_profs_ativos = Profissional.query.filter_by(empresa_id=eid, ativo=True).count()
            setup_pendente = not all([
                n_profs_ativos > 0,
                Expediente.query.filter_by(empresa_id=eid).count() > 0,
                Servico.query.filter_by(empresa_id=eid, ativo=True).count() > 0,
            ])
            limite = empresa.limite_profissionais
            profissionais_limite_atingido = limite is not None and n_profs_ativos >= limite
        except Exception:
            pass

    from flask_login import current_user
    from .permissions import agenda_scope, comissoes_scope, financeiro_scope, is_administrador
    if current_user.is_authenticated:
        perm = {'agenda': agenda_scope(), 'comissoes': comissoes_scope(),
                'financeiro': financeiro_scope(), 'admin': is_administrador()}
    else:
        perm = {'agenda': 'own_ro', 'comissoes': 'none', 'financeiro': 'none', 'admin': False}

    return {'empresa': empresa, 'setup_pendente': setup_pendente, 'theme_css': theme_css,
            'profissionais_limite_atingido': profissionais_limite_atingido, 'perm': perm}


from . import routes  # noqa: F401, E402
