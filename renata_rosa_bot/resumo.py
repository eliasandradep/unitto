"""Resumo pra recepcionista (seção 8 da especificação) — entregue via
Lead.notes (reaproveitando o mecanismo de nota com timestamp já usado por
admin/routes.py::lead_detail()), aparece automaticamente no card
"Anotações" da tela de detalhe do Lead, sem notificação externa (decisão
aprovada na Fase 1, mantida)."""
from datetime import datetime

from models import db, LEAD_SOURCES

from . import pontuacao as _pontuacao_mod

# Da mais forte pra mais fraca — usada só pra escolher uma frase de
# justificativa representativa, não pro cálculo do score em si.
_JUSTIFICATIVAS = (
    ('pt_intencao_agendar',          'demonstrou intenção explícita de agendar'),
    ('pt_pediu_humano_contratar',    'pediu para falar com a equipe para contratar'),
    ('pt_perguntou_disponibilidade', 'perguntou disponibilidade de horário'),
    ('pt_prazo_15dias',              'pretende realizar em até 15 dias'),
    ('pt_prazo_informado',           'informou prazo para realização'),
    ('pt_perguntou_valores',         'perguntou valores ou condições'),
    ('pt_referencia_foto',           'compartilhou referência ou foto'),
    ('pt_resultado_desejado',        'descreveu o resultado desejado'),
    ('pt_servico_especifico',        'identificou serviço específico'),
)


def _justificativa(estado):
    motivos = [texto for campo, texto in _JUSTIFICATIVAS if getattr(estado, campo, False)]
    if estado.forcar_quente and 'demonstrou intenção explícita de agendar' not in motivos:
        motivos.insert(0, 'pediu para agendar')
    return '; '.join(motivos) if motivos else 'interesse exploratório, sem sinal comercial forte'


def montar_resumo(lead, estado, empresa):
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    origem = dict(LEAD_SOURCES).get(lead.source, lead.source)
    score, classificacao, _ = _pontuacao_mod.calcular_pontuacao(estado)
    classificacao_final = _pontuacao_mod.QUENTE if estado.forcar_quente else classificacao

    linhas = [
        f'Nova oportunidade — Lead {classificacao_final.upper()}',
        f'Nome: {lead.name or "não informado"}',
        f'WhatsApp: {lead.phone or "não informado"}',
        f'Origem: {origem}',
        f'Serviço: {estado.servico_opcao_label or "não identificado"}',
        f'Objetivo: {estado.resultado_desejado_texto or "não informado"}',
        f'Prazo: {estado.prazo_texto or "não informado"}',
        f'Score: {score}/100',
        f'Motivo da classificação: {_justificativa(estado)}',
        f'Status: Aguardando atendimento humano',
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
