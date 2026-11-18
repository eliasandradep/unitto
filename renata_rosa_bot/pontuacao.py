"""Motor de qualificação de leads (seção 5 da especificação) — cálculo e
classificação. Pura e determinística: sempre recalculada do zero a partir
das flags salvas em RenataRosaFunilLead, nunca somada incrementalmente."""

_PESOS = {
    'pt_servico_especifico':        15,
    'pt_resultado_desejado':        10,
    'pt_referencia_foto':           10,
    'pt_prazo_informado':           15,
    'pt_prazo_15dias':              20,
    'pt_perguntou_valores':         10,
    'pt_perguntou_disponibilidade': 20,
    'pt_pediu_humano_contratar':    25,
    'pt_intencao_agendar':          30,
}

QUENTE, MORNO, FRIO = 'quente', 'morno', 'frio'


def calcular_pontuacao(estado):
    """Retorna (score_total, classificacao, breakdown). `classificacao` aqui
    é só a derivada do score — as regras de prioridade (seção 5.3, ex:
    pedido explícito de agendar) são aplicadas à parte pelo orquestrador via
    `estado.forcar_quente`, nunca aqui dentro."""
    breakdown = {campo: (peso if getattr(estado, campo, False) else 0)
                 for campo, peso in _PESOS.items()}
    score = min(sum(breakdown.values()), 100)

    if score >= 60:
        classificacao = QUENTE
    elif score >= 30:
        classificacao = MORNO
    else:
        classificacao = FRIO

    return score, classificacao, breakdown
