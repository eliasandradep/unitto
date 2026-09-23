from datetime import date, datetime, timedelta

from models import db, Profissional, Agendamento, ExpedienteDia, EscalaProfissionalUnidade
from admin.routes import _find_expediente_conflict, _find_escala_conflict, _find_bloqueio_conflict


def unidade_efetiva_id(profissional, data=None):
    """Unidade em que o profissional está efetivamente atuando numa data (hoje,
    por padrão): a escala vigente pra essa data, se houver, senão a unidade
    padrão do cadastro (profissional.unidade_id). Mesma fonte de verdade que
    _find_escala_conflict já usa, só que respondendo "em qual unidade" em vez
    de "há conflito com uma unidade específica"."""
    data = data or date.today()
    escala = EscalaProfissionalUnidade.query.filter(
        EscalaProfissionalUnidade.profissional_id == profissional.id,
        EscalaProfissionalUnidade.data_inicio <= data,
        EscalaProfissionalUnidade.data_fim >= data,
    ).first()
    return escala.unidade_id if escala else profissional.unidade_id


def eligible_profissionais(servico, unidade_id=None):
    """Profissionais aptos a atender `servico`. Quando `unidade_id` é informado
    (empresa com mais de uma unidade — cliente escolheu onde quer ser
    atendido), filtra também por quem está efetivamente atuando ali hoje
    (unidade_efetiva_id) — sem isso, um profissional escalado pra outra
    unidade aparecia como opção mesmo lá não podendo atender."""
    pool = set(servico.categoria.profissionais) if servico.categoria else set()
    pool.update(servico.profissionais_adicionais)
    elegiveis = (p for p in pool if p.ativo and p.agendamento_online)
    if unidade_id is not None:
        elegiveis = (p for p in elegiveis if unidade_efetiva_id(p) == unidade_id)
    return sorted(elegiveis, key=lambda p: p.nome)


def _find_agendamento_overlap(profissional_id, data, hora_inicio, duracao_min, agendamentos_do_dia, exclude_ag_id=None):
    """Retorna o Agendamento existente que sobrepõe o horário proposto, ou None.

    `agendamentos_do_dia` já vem carregado (uma query por dia, não por candidato).
    """
    prof = db.session.get(Profissional, profissional_id)
    if prof and prof.agendamentos_simult:
        return None
    ag_ini = datetime.combine(data, hora_inicio)
    ag_fim = ag_ini + timedelta(minutes=duracao_min)
    for ex in agendamentos_do_dia:
        if exclude_ag_id and ex.id == exclude_ag_id:
            continue
        ex_ini = datetime.combine(data, ex.hora_inicio)
        ex_fim = ex_ini + timedelta(minutes=ex.duracao_min)
        if ag_ini < ex_fim and ag_fim > ex_ini:
            return ex
    return None


def get_available_slots(profissional_id, servico, data, unidade_id=None, exclude_ag_id=None):
    """Retorna lista de `time` livres para `servico` com `profissional_id` em `data`.

    `unidade_id`: unidade que o cliente escolheu (ou a do próprio agendamento,
    ao remarcar). Quando informado, valida a escala contra ELA — não contra a
    unidade padrão do profissional — senão alguém escalado hoje pra outra
    unidade "conflitava" com o próprio cadastro e sempre voltava vazio, mesmo
    estando disponível de verdade na unidade escolhida. None (comportamento
    antigo, ainda usado por quem não passa unidade) cai de volta pra
    prof.unidade_id.

    `exclude_ag_id` ignora um agendamento existente na checagem de overlap —
    usado ao remarcar (o próprio horário atual do agendamento não deve contar
    como ocupado ao recalcular a disponibilidade)."""
    prof = db.session.get(Profissional, profissional_id)
    if not prof or not prof.expediente_id:
        return []

    dow = data.isoweekday() % 7
    dia = ExpedienteDia.query.filter_by(expediente_id=prof.expediente_id, dia_semana=dow).first()
    if not dia:
        return []

    duracao_min = max(15, (servico.duracao_horas or 0) * 60 + (servico.duracao_minutos or 0))

    unidade_ref = unidade_id if unidade_id is not None else prof.unidade_id
    if _find_escala_conflict(profissional_id, unidade_ref, data):
        return []

    agendamentos_do_dia = Agendamento.query.filter(
        Agendamento.profissional_id == profissional_id,
        Agendamento.data == data,
        Agendamento.status != 'cancelado',
    ).all()

    passo = timedelta(minutes=duracao_min)
    cursor = datetime.combine(data, dia.hora_inicio)
    fim_expediente = datetime.combine(data, dia.hora_fim)

    slots = []
    while cursor + passo <= fim_expediente:
        candidato = cursor.time()
        if (_find_expediente_conflict(profissional_id, data, candidato, duracao_min) is None
                and _find_bloqueio_conflict(profissional_id, data, candidato, duracao_min) is None
                and _find_agendamento_overlap(profissional_id, data, candidato, duracao_min,
                                               agendamentos_do_dia, exclude_ag_id=exclude_ag_id) is None):
            slots.append(candidato)
        cursor += passo
    return slots
