"""RN14 — resumo estruturado entregue à atendente. Nesta fase, "entregue"
significa gravado em Lead.notes (reaproveitando exatamente o mecanismo de
nota com timestamp já usado por admin/routes.py::lead_detail()) — aparece
automaticamente no card "Anotações" da tela de detalhe do Lead, sem precisar
de nenhuma notificação por e-mail/push/WhatsApp (decisão aprovada)."""
from datetime import datetime

from models import db, LEAD_SOURCES

_LABELS_PRAZO = {
    1: 'Nesta semana', 2: 'Nos próximos 15 dias',
    3: 'Ainda neste mês', 4: 'Estou apenas pesquisando',
}
_LABELS_HISTORICO = {
    1: 'Cabelo natural, sem química', 2: 'Já tenho mechas ou luzes',
    3: 'Tenho coloração', 4: 'Fiz progressiva ou outro alisamento',
    5: 'Não tenho certeza / preciso de orientação',
}
_LABELS_INVESTIMENTO = {
    1: 'Dentro do que procura', 2: 'Precisa entender melhor os valores',
    3: 'Fora do orçamento neste momento',
}
_LABELS_AVALIACAO = {
    1: 'Sim, gostaria', 2: 'Precisa confirmar', 3: 'Não neste momento',
}
_LABELS_AGENDAMENTO = {
    1: 'Sim, quer agendar', 2: 'Quer conversar com atendente antes',
    3: 'Ainda não quer agendar',
}


def _label(mapa, opcao):
    return mapa.get(opcao, 'Não informado') if opcao else 'Não informado'


def montar_resumo(lead, estado, empresa):
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    entrada = (estado.criado_em or lead.created_at)
    entrada_fmt = entrada.strftime('%d/%m/%Y %H:%M') if entrada else 'não registrada'
    origem = dict(LEAD_SOURCES).get(lead.source, lead.source)

    linhas = [
        f'Funil Renata Rosa — classificação: {(estado.classificacao or "não calculada").upper()} '
        f'(score {estado.score_total if estado.score_total is not None else "-"}/100)',
        f'Nome: {lead.name or "não informado"}',
        f'WhatsApp: {lead.phone or "não informado"}',
        f'Origem: {origem}',
        f'Serviço desejado: {estado.servico_opcao_label or "não informado"}',
        f'Prazo desejado: {_label(_LABELS_PRAZO, estado.prazo_opcao)}',
        f'Histórico capilar: {_label(_LABELS_HISTORICO, estado.historico_cabelo_opcao)}',
        f'Compatibilidade de investimento: {_label(_LABELS_INVESTIMENTO, estado.investimento_opcao)}',
        f'Interesse em avaliação: {_label(_LABELS_AVALIACAO, estado.avaliacao_opcao)}',
        f'Intenção de agendamento: {_label(_LABELS_AGENDAMENTO, estado.agendamento_opcao)}',
        f'Entrada no funil: {entrada_fmt}',
        '',
        '--- Histórico da conversa ---',
        estado.transcricao or '(sem transcrição)',
    ]
    return f"[{agora}] " + '\n'.join(linhas)


def gravar_em_notes(lead, texto):
    existing = lead.notes or ''
    lead.notes = f"{texto}\n{existing}".strip()
    lead.updated_at = datetime.utcnow()
    db.session.commit()
