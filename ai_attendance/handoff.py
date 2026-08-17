"""Fluxo 'Falar com atendente' (HUMAN_HANDOFF) — sempre disponível, mesmo se a
opção estiver desativada no menu configurável do tenant (rede de segurança:
o cliente sempre consegue escapar pro humano). Reaproveita o mesmo mecanismo
já usado no fluxo regex atual: Lead.contato_etapa='transferido' +
Empresa.whatsapp_humano_resolvido()."""
from .logging_ia import log_evento_ia
from .conversa import resetar_conversa


def processar(empresa, lead, conversa) -> list:
    if lead:
        lead.contato_etapa = 'transferido'
    log_evento_ia(empresa, 'AI_HUMAN_HANDOFF', lead_id=lead.id if lead else None,
                  conversa_id=conversa.id, intent='HUMAN_HANDOFF', detalhes='transfer_reason=HUMAN_REQUEST')
    resetar_conversa(conversa)

    numero = empresa.whatsapp_humano_resolvido()
    if numero:
        return [f'Claro! 😊 Vou encaminhar seu atendimento para nossa equipe. '
                f'Você também pode falar direto por aqui: https://wa.me/{numero}']
    return ['Claro! 😊 Vou encaminhar seu atendimento para nossa equipe. Aguarde um momento.']
