"""Transferência pra atendimento humano (RN11/RN14) — reaproveita o mecanismo
já existente Lead.contato_etapa='transferido', checado em
meta_webhook/routes.py pra bloquear qualquer resposta automática depois da
transferência (com reativação automática só após 1h de silêncio total,
ver _handoff_expirado em meta_webhook/routes.py)."""
from models import db

from ai_attendance.logging_ia import log_evento_ia

from . import resumo as _resumo_mod


def transferir(empresa, lead, estado, motivo, mensagem_cliente):
    lead.contato_etapa = 'transferido'
    if not estado.resumo_enviado:
        _resumo_mod.gravar_em_notes(lead, _resumo_mod.montar_resumo(lead, estado, empresa))
        estado.resumo_enviado = True
    estado.estado = 'concluido'
    log_evento_ia(empresa, 'RR_HANDOFF', lead_id=lead.id, detalhes=f'motivo={motivo}')
    db.session.commit()
    return [mensagem_cliente]
