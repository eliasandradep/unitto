"""Permissões por perfil de acesso do profissional (PERFIL_ACESSO em models.py).

Mapeia o perfil de acesso do cadastro de profissional (ou o role legado do
User, para contas que não são de profissional) para escopos de acesso a
Agenda, Comissões e Financeiro.
"""
from flask_login import current_user

PERFIL_CAPS = {
    'leitura':       {'agenda': 'own_ro', 'comissoes': 'none', 'financeiro': 'none'},
    'pessoal':       {'agenda': 'own',    'comissoes': 'own',  'financeiro': 'none'},
    'profissional':  {'agenda': 'own',    'comissoes': 'own',  'financeiro': 'limited'},
    'atendente':     {'agenda': 'all',    'comissoes': 'own',  'financeiro': 'none'},
    'recepcao':      {'agenda': 'all',    'comissoes': 'own',  'financeiro': 'limited'},
    'administrador': {'agenda': 'all',    'comissoes': 'all',  'financeiro': 'full'},
}

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
