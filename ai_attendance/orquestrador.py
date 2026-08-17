"""Ponto de entrada do atendimento por IA — chamado pelo webhook do WhatsApp
para tenants elegíveis (ver gating.ia_disponivel). Decide a máquina de estados
em código Python determinístico; a IA (nlu.py) só classifica intent e extrai
slots. Nunca deixa o cliente sem resposta: qualquer falha de NLU cai no
classificador regex determinístico.
"""
import re

from .conversa import get_or_create_conversa, resetar_conversa
from .menu import get_or_create_menu_config, opcoes_ativas, menu_texto
from .informacoes import texto_informacoes
from .logging_ia import log_evento_ia
from .nlu import montar_system_prompt, classificar, classificar_fallback_regex, NLUError
from .booking import servicos_bookable
from . import booking as _booking_mod
from . import appointment_mgmt as _appointment_mgmt_mod
from . import services_info as _services_info_mod
from . import handoff as _handoff_mod

_RE_VOLTAR_MENU = re.compile(r'(?i)^\s*(menu|voltar|in[ií]cio|cancelar)\s*$')


def _intent_por_numero(mensagem, opcoes):
    texto = (mensagem or '').strip()
    if not texto.isdigit():
        return None
    idx = int(texto) - 1
    if 0 <= idx < len(opcoes):
        return opcoes[idx].intent
    return None


def _classificar_com_fallback(empresa, conversa, mensagem):
    opcoes = opcoes_ativas(empresa)
    servicos = servicos_bookable(empresa)
    info_texto = texto_informacoes(empresa)
    system_prompt = montar_system_prompt(empresa, opcoes, servicos, info_texto, conversa)
    try:
        return classificar(system_prompt, mensagem)
    except NLUError as e:
        log_evento_ia(empresa, 'AI_FALLBACK_REGRA', conversa_id=conversa.id, detalhes=str(e)[:500])
        return classificar_fallback_regex(mensagem)


def processar_mensagem(empresa, lead, telefone, mensagem, token) -> list:
    """Retorna a lista de textos a enviar ao cliente, em ordem."""
    conversa = get_or_create_conversa(empresa, telefone, lead)

    if conversa.intent_ativo is None:
        return _processar_novo_pedido(empresa, lead, telefone, conversa, mensagem)
    return _continuar_fluxo(empresa, lead, telefone, conversa, mensagem)


def _processar_novo_pedido(empresa, lead, telefone, conversa, mensagem) -> list:
    opcoes = opcoes_ativas(empresa)

    intent = _intent_por_numero(mensagem, opcoes)
    nlu_result = {'intent': intent} if intent else None
    if nlu_result is None:
        nlu_result = _classificar_com_fallback(empresa, conversa, mensagem)
        intent = nlu_result.get('intent')

    # HUMAN_HANDOFF sempre disponível, mesmo se a opção estiver desativada no
    # menu configurável do tenant — rede de segurança confirmada em produto.
    if intent == 'HUMAN_HANDOFF':
        return _handoff_mod.processar(empresa, lead, conversa)

    intents_habilitados = {o.intent for o in opcoes}
    if intent not in intents_habilitados:
        intent = 'UNCLEAR'  # opção desativada pelo tenant, ou nada reconhecido

    if intent == 'BOOKING':
        log_evento_ia(empresa, 'AI_MENU_OPTION_SELECTED', lead_id=lead.id if lead else None,
                      conversa_id=conversa.id, intent=intent)
        return _booking_mod.processar(empresa, lead, telefone, conversa, nlu_result, mensagem)
    if intent == 'APPOINTMENT_MANAGEMENT':
        log_evento_ia(empresa, 'AI_MENU_OPTION_SELECTED', lead_id=lead.id if lead else None,
                      conversa_id=conversa.id, intent=intent)
        return _appointment_mgmt_mod.processar(empresa, lead, telefone, conversa, nlu_result, mensagem)
    if intent == 'SERVICES':
        log_evento_ia(empresa, 'AI_MENU_OPTION_SELECTED', lead_id=lead.id if lead else None,
                      conversa_id=conversa.id, intent=intent)
        return _services_info_mod.processar(empresa, lead, conversa)
    if intent == 'INFORMATION':
        log_evento_ia(empresa, 'AI_MENU_OPTION_SELECTED', lead_id=lead.id if lead else None,
                      conversa_id=conversa.id, intent=intent)
        log_evento_ia(empresa, 'AI_INFORMATION_VIEWED', lead_id=lead.id if lead else None,
                      conversa_id=conversa.id, intent=intent)
        return [texto_informacoes(empresa)]

    # UNCLEAR — reapresenta o menu
    get_or_create_menu_config(empresa)
    log_evento_ia(empresa, 'AI_MENU_DISPLAYED', lead_id=lead.id if lead else None, conversa_id=conversa.id)
    return [menu_texto(empresa)]


def _continuar_fluxo(empresa, lead, telefone, conversa, mensagem) -> list:
    if _RE_VOLTAR_MENU.match(mensagem or ''):
        resetar_conversa(conversa)
        return [menu_texto(empresa)]

    nlu_result = _classificar_com_fallback(empresa, conversa, mensagem)

    # Mesmo no meio de um fluxo, o cliente pode pedir humano a qualquer momento.
    if nlu_result.get('intent') == 'HUMAN_HANDOFF':
        return _handoff_mod.processar(empresa, lead, conversa)

    if conversa.intent_ativo == 'BOOKING':
        return _booking_mod.processar(empresa, lead, telefone, conversa, nlu_result, mensagem)
    if conversa.intent_ativo == 'APPOINTMENT_MANAGEMENT':
        return _appointment_mgmt_mod.processar(empresa, lead, telefone, conversa, nlu_result, mensagem)

    resetar_conversa(conversa)
    return [menu_texto(empresa)]
