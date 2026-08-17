"""Fluxo 'Serviços e valores' (SERVICES) — só dados reais cadastrados pelo
tenant, nunca inventados."""
from admin.tenant import tq
from models import Servico
from .logging_ia import log_evento_ia


def texto_servicos(empresa) -> str:
    servicos = tq(Servico).filter_by(ativo=True, agendamento_online=True).order_by(Servico.nome).all()
    if not servicos:
        return 'No momento não temos serviços disponíveis para agendamento online.'
    linhas = ['Nossos serviços:']
    for s in servicos:
        preco = f' — R$ {s.preco:.2f}'.replace('.', ',') if (s.exibir_preco_online and s.preco) else ''
        duracao_min = (s.duracao_horas or 0) * 60 + (s.duracao_minutos or 0)
        duracao = f' (~{duracao_min}min)' if duracao_min else ''
        linhas.append(f'💇 {s.nome}{preco}{duracao}')
        if s.descricao:
            linhas.append(f'   {s.descricao}')
    return '\n'.join(linhas)


def processar(empresa, lead, conversa) -> list:
    log_evento_ia(empresa, 'AI_SERVICES_VIEWED', lead_id=lead.id if lead else None,
                  conversa_id=conversa.id, intent='SERVICES')
    return [texto_servicos(empresa)]
