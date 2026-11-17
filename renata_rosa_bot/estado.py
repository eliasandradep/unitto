"""Estado do funil (RenataRosaFunilLead) — get-or-create, reset e transcrição.

Sem staleness automática (diferente de ai_attendance/conversa.py): RN19 pede
que a cliente possa retomar o atendimento a qualquer momento, então o estado
persiste indefinidamente até ser concluído (handoff) ou resetado explicitamente
('menu'/'voltar')."""
from models import db, RenataRosaFunilLead

_CAMPOS_RESPOSTA = (
    'fluxo', 'servico_opcao_idx', 'servico_opcao_label', 'servico_identificado',
    'prazo_opcao', 'historico_cabelo_opcao', 'investimento_opcao',
    'avaliacao_opcao', 'agendamento_opcao', 'score_total', 'classificacao',
)


def get_or_create_estado(empresa, lead) -> RenataRosaFunilLead:
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first()
    if estado:
        return estado
    estado = RenataRosaFunilLead(lead_id=lead.id, empresa_id=empresa.id, estado='menu_principal')
    db.session.add(estado)
    db.session.commit()
    return estado


def resetar_estado(estado):
    """Limpa todas as respostas e volta pro menu principal — usado por
    'menu'/'voltar ao início' e ao reativar um funil já concluído."""
    estado.estado = 'menu_principal'
    estado.estado_anterior = None
    estado.contador_nao_entendido = 0
    estado.resumo_enviado = False
    # transcricao NÃO é limpa — preserva o histórico completo da conversa
    # entre ciclos do funil (ex: reativação pós-handoff), só reseta as
    # respostas pra um novo ciclo de qualificação poder gerar seu próprio resumo.
    for campo in _CAMPOS_RESPOSTA:
        setattr(estado, campo, None)
    db.session.commit()


def registrar_transcricao(estado, bot=None, cliente=None):
    linhas = []
    if estado.transcricao:
        linhas.append(estado.transcricao)
    if cliente is not None:
        linhas.append(f'Cliente: {cliente}')
    if bot is not None:
        for texto in (bot if isinstance(bot, list) else [bot]):
            linhas.append(f'Bot: {texto}')
    estado.transcricao = '\n'.join(linhas)
    db.session.commit()
