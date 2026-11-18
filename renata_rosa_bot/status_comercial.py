"""Pipeline de status comercial (STATUS_COMERCIAL_RR, seção 7 da
especificação), independente da classificação quente/morno/frio
(RenataRosaFunilLead.classificacao). Único ponto de escrita de
`status_comercial` + histórico — nunca gravar direto no campo em outro lugar."""
from datetime import datetime, timedelta

from models import db, Empresa, RenataRosaFunilLead, RenataRosaFunilStatusHistorico
from .gating import RENATA_ROSA_SLUG

# Status setados manualmente pela atendente (refletem uma ação que o bot não
# tem como saber sozinho — agendamento realmente confirmado, serviço
# realmente realizado, ou lead dado como perdido) — uma vez setado um
# desses, nenhuma transição automática do funil sobrescreve de novo; só uma
# nova ação manual muda. 'sem_interesse' fica de fora de propósito: é o bot
# quem normalmente detecta e marca isso, e deve poder reverter sozinho se a
# cliente reengajar.
STATUS_MANUAIS = frozenset({
    'agendamento_confirmado', 'servico_realizado', 'perdido',
})

AGUARDANDO_CLIENTE_HORAS = 48
_STATUS_ATIVOS_PARA_AGUARDANDO_CLIENTE = ('em_atendimento_ia', 'em_qualificacao')


def definir_status(estado, novo_status, forcar=False):
    """Muda `estado.status_comercial` e grava o histórico — no-op se já é
    esse status. `forcar=True` (usado só pela ação manual da atendente)
    ignora a proteção de STATUS_MANUAIS; transições automáticas do funil
    nunca passam `forcar=True`."""
    atual = estado.status_comercial
    if atual == novo_status:
        return
    if not forcar and atual in STATUS_MANUAIS:
        return
    estado.status_comercial = novo_status
    db.session.add(RenataRosaFunilStatusHistorico(
        funil_lead_id=estado.id, status_anterior=atual, status_novo=novo_status))
    db.session.commit()


def marcar_leads_aguardando_cliente():
    """Job periódico (ver app.py) — marca como 'aguardando_cliente' os leads
    da Renata Rosa parados há mais de AGUARDANDO_CLIENTE_HORAS num status
    ativo (a IA já respondeu e a cliente não voltou). Nunca toca em status
    manuais nem em quem já está 'aguardando_cliente'."""
    empresa = Empresa.query.filter_by(slug=RENATA_ROSA_SLUG).first()
    if not empresa:
        return
    limite = datetime.utcnow() - timedelta(hours=AGUARDANDO_CLIENTE_HORAS)
    candidatos = RenataRosaFunilLead.query.filter(
        RenataRosaFunilLead.empresa_id == empresa.id,
        RenataRosaFunilLead.status_comercial.in_(_STATUS_ATIVOS_PARA_AGUARDANDO_CLIENTE),
        RenataRosaFunilLead.atualizado_em < limite,
    ).all()
    for estado in candidatos:
        definir_status(estado, 'aguardando_cliente')
