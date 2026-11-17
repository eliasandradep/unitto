"""Testes unitários puros de renata_rosa_bot.pontuacao — sem webhook, sem DB
real (um objeto qualquer com os atributos certos serve)."""
from types import SimpleNamespace

from renata_rosa_bot.pontuacao import calcular_pontuacao, QUENTE, MORNO, FRIO


def _estado(servico_identificado=None, prazo_opcao=None, investimento_opcao=None,
            avaliacao_opcao=None, agendamento_opcao=None):
    return SimpleNamespace(
        servico_identificado=servico_identificado, prazo_opcao=prazo_opcao,
        investimento_opcao=investimento_opcao, avaliacao_opcao=avaliacao_opcao,
        agendamento_opcao=agendamento_opcao,
    )


def test_pontuacao_maxima_e_quente():
    estado = _estado(servico_identificado=True, prazo_opcao=1, investimento_opcao=1,
                      avaliacao_opcao=1, agendamento_opcao=1)
    score, classificacao, breakdown = calcular_pontuacao(estado)
    assert score == 100
    assert classificacao == QUENTE
    assert breakdown == {'prazo': 25, 'investimento': 25, 'agendamento': 30, 'avaliacao': 10, 'clareza': 10}


def test_pontuacao_minima_e_fria():
    estado = _estado(servico_identificado=None, prazo_opcao=4, investimento_opcao=3,
                      avaliacao_opcao=3, agendamento_opcao=3)
    score, classificacao, _ = calcular_pontuacao(estado)
    assert score == 0
    assert classificacao == FRIO


def test_servico_nao_identificado_vale_5_pontos_de_clareza():
    estado = _estado(servico_identificado=False, prazo_opcao=4, investimento_opcao=3,
                      avaliacao_opcao=3, agendamento_opcao=3)
    score, _, breakdown = calcular_pontuacao(estado)
    assert breakdown['clareza'] == 5
    assert score == 5


def test_limiar_morno():
    estado = _estado(servico_identificado=True, prazo_opcao=2, investimento_opcao=1,
                      avaliacao_opcao=3, agendamento_opcao=3)
    score, classificacao, _ = calcular_pontuacao(estado)
    assert score == 10 + 20 + 25 + 0 + 0
    assert classificacao == MORNO


def test_calculo_e_idempotente():
    estado = _estado(servico_identificado=True, prazo_opcao=1, investimento_opcao=2,
                      avaliacao_opcao=2, agendamento_opcao=2)
    primeira = calcular_pontuacao(estado)
    segunda = calcular_pontuacao(estado)
    assert primeira == segunda


def test_fluxo_simplificado_nunca_ultrapassa_65_pontos():
    """RN02 pula investimento/avaliação no fluxo de corte/tratamento — mesmo
    no melhor cenário possível (prazo+agendamento máximos), o score máximo é
    10 (clareza) + 25 (prazo) + 30 (agendamento) = 65, nunca QUENTE (70+)."""
    estado = _estado(servico_identificado=True, prazo_opcao=1, investimento_opcao=None,
                      avaliacao_opcao=None, agendamento_opcao=1)
    score, classificacao, _ = calcular_pontuacao(estado)
    assert score == 65
    assert classificacao == MORNO
