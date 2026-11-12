"""Permissões por perfil de acesso do profissional (PERFIL_ACESSO em models.py).

Mapeia o perfil de acesso do cadastro de profissional (ou o role legado do
User, para contas que não são de profissional) para escopos de acesso a
Agenda, Comissões e Financeiro.
"""
from flask_login import current_user

PERFIL_CAPS = {
    'leitura':       {'agenda': 'own_ro', 'comissoes': 'none', 'financeiro': 'none'},
    'pessoal':       {'agenda': 'own',    'comissoes': 'own',  'financeiro': 'none'},
    'profissional':  {'agenda': 'own',    'comissoes': 'own',  'financeiro': 'own'},
    'atendente':     {'agenda': 'all',    'comissoes': 'own',  'financeiro': 'none'},
    'recepcao':      {'agenda': 'all',    'comissoes': 'own',  'financeiro': 'limited'},
    'administrador': {'agenda': 'all',    'comissoes': 'all',  'financeiro': 'full'},
}
# financeiro: 'none' sem acesso · 'own' só comandas do próprio profissional (qualquer
# data) · 'limited' qualquer comanda, só do dia de hoje · 'full' sem restrição

_ROLE_TO_PERFIL = {
    'saas_admin':    'administrador',
    'empresa_admin': 'administrador',
    'recepcionista': 'recepcao',
}


def current_perfil():
    """Resolve o perfil de acesso efetivo do usuário logado."""
    if not current_user.is_authenticated:
        return 'leitura'
    role = current_user.role
    if role in _ROLE_TO_PERFIL:
        return _ROLE_TO_PERFIL[role]
    if role == 'profissional':
        prof = current_user.profissional
        if prof and prof.perfil_acesso in PERFIL_CAPS:
            return prof.perfil_acesso
        return 'leitura'
    return 'leitura'


def current_profissional():
    if not current_user.is_authenticated:
        return None
    return current_user.profissional


def _cap(area):
    return PERFIL_CAPS.get(current_perfil(), PERFIL_CAPS['leitura'])[area]


def agenda_scope():
    return _cap('agenda')


def comissoes_scope():
    return _cap('comissoes')


def financeiro_scope():
    return _cap('financeiro')


def is_administrador():
    return current_perfil() == 'administrador'


def financeiro_pode_acessar(c=None):
    """True se o usuário logado pode ver/editar/fechar/lançar pagamento em `c`
    (uma Comanda ou um Agendamento — ambos têm .data e .profissional_id),
    considerando seu escopo financeiro. Sem `c`, só diz se há acesso geral
    à área financeira (ignora dono/data)."""
    scope = financeiro_scope()
    if scope == 'none':
        return False
    if scope == 'full':
        return True
    if scope == 'limited':
        from datetime import date
        return c is None or c.data == date.today()
    if scope == 'own':
        if c is None:
            return True
        prof = current_profissional()
        return prof is not None and c.profissional_id == prof.id
    return False


def bloqueios_pode_gerenciar(b=None):
    """True se o usuário logado pode ver/criar/editar/excluir o bloqueio `b`
    (BloqueioAgenda). Perfis com agenda 'all' (atendente/recepção/
    administrador) mexem em qualquer bloqueio, inclusive os sem profissional
    (bloqueio geral da empresa). O perfil 'profissional' só mexe nos
    próprios bloqueios (b.profissional_id igual ao seu id) — não pode criar
    bloqueio geral nem de outro profissional. Demais perfis ('pessoal',
    'leitura') não têm acesso à tela. Sem `b`, só diz se há acesso geral à
    tela (ignora dono)."""
    if agenda_scope() == 'all':
        return True
    if current_perfil() == 'profissional':
        if b is None:
            return True
        prof = current_profissional()
        return prof is not None and b.profissional_id == prof.id
    return False


def tem_acesso_catalogo():
    """Telas de catálogo (Serviços, Categorias, Produtos, Profissionais,
    Unidades, Expedientes, Pacotes) — administrador, atendente e recepção
    têm acesso de leitura/escrita; exclusão continua restrita a
    administrador, checada em cada rota (ver admin/__init__.py). Usuários,
    Configurações, Financeiro e Integrações continuam fora — são cadastros
    estratégicos, não de catálogo."""
    return current_perfil() in ('administrador', 'atendente', 'recepcao')
