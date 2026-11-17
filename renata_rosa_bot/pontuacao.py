"""RN09/RN10 — cálculo de pontuação e classificação. Pura e determinística:
sempre recalculada do zero a partir do estado salvo, nunca somada
incrementalmente, pra ser "refazível" a qualquer momento como a RN09 exige."""

_PTS_PRAZO        = {1: 25, 2: 20, 3: 12, 4: 0}
_PTS_INVESTIMENTO = {1: 25, 2: 10, 3: 0}
_PTS_AGENDAMENTO  = {1: 30, 2: 12, 3: 0}
_PTS_AVALIACAO    = {1: 10, 2: 5,  3: 0}

QUENTE, MORNO, FRIO = 'quente', 'morno', 'frio'


def calcular_pontuacao(estado):
    """Retorna (score_total, classificacao, breakdown)."""
    pts_prazo        = _PTS_PRAZO.get(estado.prazo_opcao, 0)
    pts_investimento = _PTS_INVESTIMENTO.get(estado.investimento_opcao, 0)
    pts_agendamento  = _PTS_AGENDAMENTO.get(estado.agendamento_opcao, 0)
    pts_avaliacao    = _PTS_AVALIACAO.get(estado.avaliacao_opcao, 0)

    # Clareza do serviço (RN09): serviço definido (RN02 opção 1-4) = 10 pts;
    # "ainda não sei, quero orientação" (opção 5) = 5 pts; pergunta nem
    # chegou a ser feita (fluxo simplificado, ou handoff antes de RN02) = 0 pts.
    if estado.servico_identificado is True:
        pts_clareza = 10
    elif estado.servico_identificado is False:
        pts_clareza = 5
    else:
        pts_clareza = 0

    score = pts_prazo + pts_investimento + pts_agendamento + pts_avaliacao + pts_clareza
    if score >= 70:
        classificacao = QUENTE
    elif score >= 40:
        classificacao = MORNO
    else:
        classificacao = FRIO

    breakdown = {
        'prazo': pts_prazo, 'investimento': pts_investimento,
        'agendamento': pts_agendamento, 'avaliacao': pts_avaliacao,
        'clareza': pts_clareza,
    }
    return score, classificacao, breakdown
