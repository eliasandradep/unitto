"""Resumo pra recepcionista (seção 8 da especificação) — entregue via
Lead.notes (reaproveitando o mecanismo de nota com timestamp já usado por
admin/routes.py::lead_detail()), aparece automaticamente no card
"Anotações" da tela de detalhe do Lead, sem notificação externa (decisão
aprovada na Fase 1, mantida)."""
from datetime import datetime

from models import db, LEAD_SOURCES

from . import pontuacao as _pontuacao_mod
from . import fluxos as _fluxos_mod

# O <select> de Unidade em templates/admin/lead_detail.html só tem esses 2
# valores fixos (específicos deste tenant) — Lead.unit grava o slug (ver
# orquestrador.py), aqui só traduzimos de volta pro texto amigável que o
# próprio dropdown já usa, sem reconsultar o banco.
_UNIDADE_LABEL = {'varginha': 'Varginha – MG', 'sao_jose': 'São José dos Campos – SP'}

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


def montar_mensagem_lead(lead, estado):
    """Resumo curto e formatado (com labels) das respostas já coletadas, pro
    campo "Mensagem original" do Lead (admin) — Fase 5c. Bem mais útil pra
    identificação rápida do que o texto cru da última mensagem recebida, que
    meta_webhook/routes.py deixa de sobrescrever pra esse tenant enquanto o
    funil está ativo (ver renata_rosa_bot.gating.funil_ativo). None quando
    ainda não há nada de estruturado coletado — nesse caso quem chama
    preserva o que já estava em Lead.message."""
    linhas = []
    unidade_label = _UNIDADE_LABEL.get(lead.unit)
    if unidade_label:
        linhas.append(f'Unidade: {unidade_label}')
    servico = estado.servico_opcao_label or _fluxos_mod.TOPICO_LABEL.get(estado.topico_ativo)
    if servico:
        linhas.append(f'Serviço de interesse: {servico}')
    if estado.resultado_desejado_texto:
        linhas.append(f'Objetivo: {estado.resultado_desejado_texto}')
    if estado.prazo_texto:
        linhas.append(f'Prazo: {estado.prazo_texto}')
    if lead.email:
        linhas.append(f'E-mail: {lead.email}')
    return '\n'.join(linhas) if linhas else None


def gravar_em_notes(lead, texto):
    existing = lead.notes or ''
    lead.notes = f"{texto}\n{existing}".strip()
    lead.updated_at = datetime.utcnow()
    db.session.commit()
