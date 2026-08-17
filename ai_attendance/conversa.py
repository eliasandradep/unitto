"""Estado da conversa multi-turno do atendimento por IA (AtendimentoIAConversa).

1 linha por (empresa_id, telefone). Conversas paradas há mais de STALE_MINUTOS
sem interação são tratadas como abandonadas — a próxima mensagem reinicia no
menu principal em vez de tentar continuar um fluxo velho."""
from datetime import datetime, timedelta

from models import db, AtendimentoIAConversa

STALE_MINUTOS = 30


def get_or_create_conversa(empresa, telefone, lead=None) -> AtendimentoIAConversa:
    conversa = AtendimentoIAConversa.query.filter_by(empresa_id=empresa.id, telefone=telefone).first()
    if conversa is None:
        conversa = AtendimentoIAConversa(empresa_id=empresa.id, telefone=telefone,
                                          lead_id=lead.id if lead else None)
        db.session.add(conversa)
        db.session.commit()
        return conversa

    if lead and conversa.lead_id != lead.id:
        conversa.lead_id = lead.id

    if conversa.atualizado_em and datetime.utcnow() - conversa.atualizado_em > timedelta(minutes=STALE_MINUTOS):
        resetar_conversa(conversa, commit=False)

    db.session.commit()
    return conversa


def resetar_conversa(conversa, commit=True):
    conversa.intent_ativo = None
    conversa.estado = None
    conversa.contexto_json = None
    if commit:
        db.session.commit()


def salvar_conversa(conversa, intent_ativo=None, estado=None, contexto=None):
    conversa.intent_ativo = intent_ativo
    conversa.estado = estado
    if contexto is not None:
        conversa.set_contexto(contexto)
    db.session.commit()
