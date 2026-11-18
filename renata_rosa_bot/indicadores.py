"""RN18 — indicadores comerciais do funil. Calculado iterando em Python
sobre os RenataRosaFunilLead da empresa (volume baixo — um salão só — não
precisa de SQL agregado). Métricas 8/9/10 (comparecimento, contratação
efetiva, receita) só enxergam leads com `agendamento_vinculado` setado
(vínculo manual, ver admin/routes.py); métrica 11 (tempo de 1ª resposta) é
um proxy — tempo até a atendente mudar o status manualmente depois de
'aguardando_atendimento_humano', não a resposta real no WhatsApp (que o
sistema não tem como observar, ver renata_rosa_bot/handoff.py)."""
from collections import Counter
from datetime import datetime

from models import RenataRosaFunilLead


def _pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def calcular_indicadores(empresa):
    leads = RenataRosaFunilLead.query.filter_by(empresa_id=empresa.id).all()
    total = len(leads)

    leads_por_origem = Counter()
    leads_por_servico = Counter()
    leads_por_classificacao = Counter()
    for estado in leads:
        if estado.lead:
            leads_por_origem[estado.lead.source_label()] += 1
        if estado.servico_opcao_label:
            leads_por_servico[estado.servico_opcao_label] += 1
        if estado.classificacao:
            leads_por_classificacao[estado.classificacao] += 1

    concluiu_questionario = sum(1 for e in leads if e.classificacao)

    transferidos = 0
    converteu_agendamento = 0
    tempos_resposta_min = []
    for estado in leads:
        hist = sorted(estado.status_historico, key=lambda h: h.criado_em or datetime.min)
        novos = [h.status_novo for h in hist]
        if 'aguardando_atendimento_humano' in novos:
            transferidos += 1
            for i, h in enumerate(hist):
                if h.status_novo == 'aguardando_atendimento_humano' and i + 1 < len(hist):
                    seguinte = hist[i + 1]
                    if h.criado_em and seguinte.criado_em:
                        tempos_resposta_min.append((seguinte.criado_em - h.criado_em).total_seconds() / 60)
                    break
        if any(s in ('agendamento_confirmado', 'servico_realizado') for s in novos):
            converteu_agendamento += 1

    compareceu = faltou = fechou_comanda = 0
    receita_total = 0.0
    receita_por_origem = Counter()
    receita_por_servico = Counter()
    for estado in leads:
        ag = estado.agendamento_vinculado
        if not ag:
            continue
        if ag.status == 'concluido':
            compareceu += 1
        elif ag.status == 'faltou':
            faltou += 1
        comanda = ag.comanda
        if comanda and comanda.status == 'fechada':
            fechou_comanda += 1
            valor = float(comanda.valor_pago or 0)
            receita_total += valor
            if estado.lead:
                receita_por_origem[estado.lead.source_label()] += valor
            if estado.servico_opcao_label:
                receita_por_servico[estado.servico_opcao_label] += valor

    motivos_nao_conversao = [
        {'nome': estado.lead.name or estado.lead.phone, 'motivo': estado.motivo_nao_convertido,
         'data': estado.atualizado_em}
        for estado in leads
        if estado.status_comercial == 'perdido' and estado.motivo_nao_convertido and estado.lead
    ]

    return {
        'total_leads': total,
        'leads_por_origem': dict(leads_por_origem),
        'leads_por_servico': dict(leads_por_servico),
        'leads_por_classificacao': dict(leads_por_classificacao),
        'taxa_conclusao_questionario': _pct(concluiu_questionario, total),
        'taxa_transferencia_humana': _pct(transferidos, total),
        'taxa_conversao_agendamento': _pct(converteu_agendamento, total),
        'taxa_comparecimento': _pct(compareceu, compareceu + faltou),
        'taxa_contratacao_efetiva': _pct(fechou_comanda, total),
        'receita_total': receita_total,
        'receita_por_origem': dict(receita_por_origem),
        'receita_por_servico': dict(receita_por_servico),
        'tempo_medio_resposta_minutos': (
            round(sum(tempos_resposta_min) / len(tempos_resposta_min), 1) if tempos_resposta_min else None
        ),
        'motivos_nao_conversao': motivos_nao_conversao,
    }
