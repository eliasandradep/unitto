from datetime import datetime, timedelta

from models import db, Profissional, Agendamento, ExpedienteDia
from admin.routes import _find_expediente_conflict, _find_escala_conflict, _find_bloqueio_conflict


def eligible_profissionais(servico):
    pool = set(servico.categoria.profissionais) if servico.categoria else set()
    pool.update(servico.profissionais_adicionais)
    return sorted((p for p in pool if p.ativo and p.agendamento_online), key=lambda p: p.nome)


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


def get_available_slots(profissional_id, servico, data):
    """Retorna lista de `time` livres para `servico` com `profissional_id` em `data`."""
    prof = db.session.get(Profissional, profissional_id)
    if not prof or not prof.expediente_id:
        return []

    dow = data.isoweekday() % 7
    dia = ExpedienteDia.query.filter_by(expediente_id=prof.expediente_id, dia_semana=dow).first()
    if not dia:
        return []

    duracao_min = max(15, (servico.duracao_horas or 0) * 60 + (servico.duracao_minutos or 0))

    if _find_escala_conflict(profissional_id, prof.unidade_id, data):
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
                and _find_agendamento_overlap(profissional_id, data, candidato, duracao_min, agendamentos_do_dia) is None):
            slots.append(candidato)
        cursor += passo
    return slots
