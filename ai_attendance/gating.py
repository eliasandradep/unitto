"""Ponto único de checagem de elegibilidade do atendimento por IA.

Usado tanto no roteamento do webhook do WhatsApp quanto nas rotas admin de
configuração — nunca confiar só no frontend para esconder a funcionalidade."""


def ia_disponivel(empresa) -> bool:
    """True somente se a empresa está ativa (status + trial/vencimento em dia)
    E tem o atendimento por IA contratado/ligado (plano PRO + toggle ativo)."""
    return bool(empresa) and empresa.is_ativa() and empresa.tem_atendimento_ia()
