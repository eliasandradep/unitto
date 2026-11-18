"""RN15 — pipeline de status comercial (11 estágios), independente da
classificação quente/morno/frio (RenataRosaFunilLead.classificacao). Único
ponto de escrita de `status_comercial` + histórico — nunca gravar direto no
campo em outro lugar."""
from datetime import datetime, timedelta

from models import db, Empresa, RenataRosaFunilLead, RenataRosaFunilStatusHistorico
from .gating import RENATA_ROSA_SLUG

# Status setados manualmente pela atendente (refletem uma ação fora do
# alcance do bot) — uma vez setado um desses, nenhuma transição automática
# do funil sobrescreve de novo; só uma nova ação manual muda.
STATUS_MANUAIS = frozenset({
    'em_negociacao', 'agendamento_realizado', 'atendimento_realizado', 'nao_convertido',
})

SEM_RESPOSTA_HORAS = 48
_STATUS_ATIVOS_PARA_SEM_RESPOSTA = ('em_qualificacao', 'aguardando_atendimento_humano')


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


def marcar_sem_resposta():
    """Job periódico (ver app.py) — marca como 'sem_resposta' os leads da
    Renata Rosa parados há mais de SEM_RESPOSTA_HORAS num status ativo.
    Nunca toca em status manuais nem em quem já está 'sem_resposta'."""
    empresa = Empresa.query.filter_by(slug=RENATA_ROSA_SLUG).first()
    if not empresa:
        return
    limite = datetime.utcnow() - timedelta(hours=SEM_RESPOSTA_HORAS)
    candidatos = RenataRosaFunilLead.query.filter(
        RenataRosaFunilLead.empresa_id == empresa.id,
        RenataRosaFunilLead.status_comercial.in_(_STATUS_ATIVOS_PARA_SEM_RESPOSTA),
        RenataRosaFunilLead.atualizado_em < limite,
    ).all()
    for estado in candidatos:
        definir_status(estado, 'sem_resposta')
