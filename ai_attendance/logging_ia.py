"""Auditoria dos eventos do atendimento por IA (AtendimentoIAEvento)."""
from models import db, EVENTOS_IA_TIPOS, AtendimentoIAEvento


def log_evento_ia(empresa, tipo, lead_id=None, cliente_id=None, agendamento_id=None,
                   conversa_id=None, intent=None, detalhes=None):
    """Grava um evento de auditoria. Nunca levanta exceção — falha de log não
    pode derrubar o atendimento ao cliente."""
    if tipo not in EVENTOS_IA_TIPOS:
        tipo = 'AI_ERROR'
    try:
        evento = AtendimentoIAEvento(
            empresa_id=empresa.id, lead_id=lead_id, cliente_id=cliente_id,
            agendamento_id=agendamento_id, conversa_id=conversa_id,
            tipo=tipo, intent=intent, detalhes=(detalhes or '')[:2000] or None,
        )
        db.session.add(evento)
        db.session.commit()
    except Exception:
        db.session.rollback()
