"""Fluxo 'Meu agendamento' (APPOINTMENT_MANAGEMENT) — VIEW/RESCHEDULE/CANCEL.

Identificação do cliente pelo telefone do WhatsApp. Toda operação de escrita
(RESCHEDULE/CANCEL) exige validação de posse: o agendamento precisa pertencer
ao tenant (empresa_id) E ao telefone que está conversando — qualquer falha
responde de forma genérica, sem revelar que o agendamento existe mas é de
outro tenant/cliente.
"""
import re
from datetime import date, time as _time

from models import db, Agendamento
from meta_webhook.phone_utils import mesmo_telefone
from public.availability import get_available_slots
from .booking import parse_data_flexivel
from .logging_ia import log_evento_ia
from .conversa import salvar_conversa, resetar_conversa

_RE_RESCHEDULE = re.compile(r'(?i)\bremarcar\b|\breagendar\b|mudar (a |o )?(data|hor[aá]rio)')
_RE_CANCEL     = re.compile(r'(?i)\bcancelar\b|\bcancela\b')
_RE_SIM = re.compile(r'(?i)^\s*(sim|confirmar|confirmo|isso|pode ser|ok)\b')
_RE_NAO = re.compile(r'(?i)^\s*(n[aã]o|deixa|mant[eé]m|manter)\b')

_MAX_AGENDAMENTOS_LISTADOS = 3


def _agendamentos_futuros(empresa, telefone):
    """Agendamentos futuros do tenant cujo telefone bate (últimos 8 dígitos)
    com quem está conversando. empresa_id vem sempre da integração resolvida
    pelo webhook — nunca de input do cliente — garantindo isolamento entre
    tenants mesmo em caso de coincidência de número de telefone."""
    candidatos = Agendamento.query.filter(
        Agendamento.empresa_id == empresa.id,
        Agendamento.data >= date.today(),
        Agendamento.status.notin_(('cancelado',)),
    ).order_by(Agendamento.data, Agendamento.hora_inicio).all()
    return [a for a in candidatos if mesmo_telefone(a.telefone, telefone)]


def _pertence_ao_cliente(agendamento, empresa, telefone):
    return bool(agendamento) and agendamento.empresa_id == empresa.id and mesmo_telefone(agendamento.telefone, telefone)


def _resumo(agendamento):
    return (f'{agendamento.data.strftime("%d/%m")} às {agendamento.hora_inicio.strftime("%H:%M")} '
            f'com {agendamento.profissional.nome} — {agendamento.servico.nome if agendamento.servico else "serviço"}')


def processar(empresa, lead, telefone, conversa, nlu_result, mensagem) -> list:
    contexto = conversa.get_contexto()
    estado = conversa.estado

    if conversa.intent_ativo != 'APPOINTMENT_MANAGEMENT' or estado is None:
        contexto = {}
        return _listar_ou_escolher(empresa, lead, telefone, conversa, contexto)

    if estado == 'aguardando_escolha':
        return _tratar_escolha(empresa, lead, telefone, conversa, contexto, nlu_result, mensagem)
    if estado == 'aguardando_acao':
        return _tratar_acao(empresa, lead, telefone, conversa, contexto, nlu_result, mensagem)
    if estado == 'reschedule_aguardando_data':
        return _reschedule_aguardando_data(empresa, conversa, contexto, nlu_result, mensagem)
    if estado == 'reschedule_aguardando_hora':
        return _reschedule_aguardando_hora(empresa, lead, conversa, contexto, nlu_result, mensagem)
    if estado == 'reschedule_confirmacao':
        return _reschedule_confirmar(empresa, lead, conversa, contexto, mensagem)
    if estado == 'cancel_confirmacao':
        return _cancel_confirmar(empresa, lead, conversa, contexto, mensagem)

    resetar_conversa(conversa)
    return _listar_ou_escolher(empresa, lead, telefone, conversa, {})


def _listar_ou_escolher(empresa, lead, telefone, conversa, contexto):
    agendamentos = _agendamentos_futuros(empresa, telefone)
    log_evento_ia(empresa, 'AI_APPOINTMENT_VIEWED', lead_id=lead.id if lead else None,
                  conversa_id=conversa.id, intent='APPOINTMENT_MANAGEMENT')

    if not agendamentos:
        resetar_conversa(conversa)
        return ['Não encontrei nenhum agendamento futuro no seu número. '
                'Se quiser marcar um horário, é só me chamar.']

    if len(agendamentos) == 1:
        contexto['agendamento_id'] = agendamentos[0].id
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'aguardando_acao', contexto)
        return [f'Encontrei seu agendamento: {_resumo(agendamentos[0])}.\n'
                'O que deseja? 1. Remarcar  2. Cancelar  3. Manter agendamento']

    contexto['agendamentos_oferecidos'] = [a.id for a in agendamentos[:_MAX_AGENDAMENTOS_LISTADOS]]
    salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'aguardando_escolha', contexto)
    linhas = ['Encontrei mais de um agendamento seu:']
    linhas += [f'{i}. {_resumo(a)}' for i, a in enumerate(agendamentos[:_MAX_AGENDAMENTOS_LISTADOS], start=1)]
    linhas.append('Qual deles?')
    return ['\n'.join(linhas)]


def _tratar_escolha(empresa, lead, telefone, conversa, contexto, nlu_result, mensagem):
    ofertados = contexto.get('agendamentos_oferecidos', [])
    texto = (mensagem or '').strip()
    if texto.isdigit():
        idx = int(texto) - 1
        if 0 <= idx < len(ofertados):
            ag_id = ofertados[idx]
            agendamento = db.session.get(Agendamento, ag_id)
            if _pertence_ao_cliente(agendamento, empresa, telefone):
                contexto['agendamento_id'] = ag_id
                salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'aguardando_acao', contexto)
                return [f'{_resumo(agendamento)}.\nO que deseja? 1. Remarcar  2. Cancelar  3. Manter agendamento']
    salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'aguardando_escolha', contexto)
    return ['Não entendi. Responda com o número do agendamento que deseja.']


def _tratar_acao(empresa, lead, telefone, conversa, contexto, nlu_result, mensagem):
    agendamento = db.session.get(Agendamento, contexto.get('agendamento_id'))
    if not _pertence_ao_cliente(agendamento, empresa, telefone):
        log_evento_ia(empresa, 'AI_ERROR', lead_id=lead.id if lead else None, conversa_id=conversa.id,
                      detalhes='tentativa de agir sobre agendamento sem posse confirmada')
        resetar_conversa(conversa)
        return ['Não encontrei esse agendamento. Se quiser, posso listar seus agendamentos de novo.']

    texto = (mensagem or '').strip()
    sub_acao = (nlu_result or {}).get('sub_acao')
    quer_remarcar = sub_acao == 'RESCHEDULE' or texto.startswith('1') or _RE_RESCHEDULE.search(texto)
    quer_cancelar = sub_acao == 'CANCEL' or texto.startswith('2') or _RE_CANCEL.search(texto)

    if quer_remarcar:
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_aguardando_data', contexto)
        return ['Para qual novo dia você quer remarcar?']
    if quer_cancelar:
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'cancel_confirmacao', contexto)
        return [f'Confirma o cancelamento de {_resumo(agendamento)}? (responda SIM ou NÃO)']
    if texto.startswith('3') or _RE_NAO.search(texto):
        resetar_conversa(conversa)
        return ['Combinado, seu agendamento continua como está. Precisando de algo mais é só chamar.']

    salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'aguardando_acao', contexto)
    return ['Não entendi. Responda 1 para remarcar, 2 para cancelar ou 3 para manter o agendamento.']


def _reschedule_aguardando_data(empresa, conversa, contexto, nlu_result, mensagem=None):
    data_val = (parse_data_flexivel((nlu_result or {}).get('data_mencionada'))
                or parse_data_flexivel(mensagem))
    if data_val is None or data_val < date.today():
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_aguardando_data', contexto)
        return ['Para qual dia? (ex: 20/08 ou "amanhã")']

    agendamento = db.session.get(Agendamento, contexto['agendamento_id'])
    slots = get_available_slots(agendamento.profissional_id, agendamento.servico, data_val,
                                 exclude_ag_id=agendamento.id)
    if not slots:
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_aguardando_data', contexto)
        return [f'Não há horários livres em {data_val.strftime("%d/%m")} com {agendamento.profissional.nome}. '
                'Quer tentar outra data?']

    contexto['nova_data'] = data_val.isoformat()
    contexto['horarios_oferecidos'] = [h.strftime('%H:%M') for h in slots]
    salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_aguardando_hora', contexto)
    linhas = [f'Horários livres em {data_val.strftime("%d/%m")}:']
    linhas += [f'{i}. {h}' for i, h in enumerate(contexto['horarios_oferecidos'], start=1)]
    return ['\n'.join(linhas)]


def _reschedule_aguardando_hora(empresa, lead, conversa, contexto, nlu_result, mensagem):
    ofertados = contexto.get('horarios_oferecidos', [])
    hora_txt = None
    if mensagem and mensagem.strip().isdigit():
        idx = int(mensagem.strip()) - 1
        if 0 <= idx < len(ofertados):
            hora_txt = ofertados[idx]
    if hora_txt is None:
        candidato = (nlu_result or {}).get('hora_mencionada') or ''
        m = re.match(r'^(\d{1,2}):?(\d{2})?$', candidato.strip())
        if m:
            hora_txt = f'{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}'
    if hora_txt is None or hora_txt not in ofertados:
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_aguardando_hora', contexto)
        return ['Não entendi o horário. Responda com o número de uma das opções.']

    contexto['nova_hora'] = hora_txt
    salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_confirmacao', contexto)
    data_val = date.fromisoformat(contexto['nova_data'])
    return [f'Remarcar para {data_val.strftime("%d/%m/%Y")} às {hora_txt}? (responda SIM ou NÃO)']


def _reschedule_confirmar(empresa, lead, conversa, contexto, mensagem):
    texto = (mensagem or '').strip()
    if _RE_NAO.search(texto):
        resetar_conversa(conversa)
        return ['Sem problemas, mantive o agendamento original.']
    if not _RE_SIM.search(texto):
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'reschedule_confirmacao', contexto)
        return ['Só para confirmar: remarco? (responda SIM ou NÃO)']

    agendamento = db.session.get(Agendamento, contexto['agendamento_id'])
    data_val = date.fromisoformat(contexto['nova_data'])
    h, m = map(int, contexto['nova_hora'].split(':'))
    hora_val = _time(h, m)

    slots_atuais = get_available_slots(agendamento.profissional_id, agendamento.servico, data_val,
                                        exclude_ag_id=agendamento.id)
    if hora_val not in slots_atuais:
        resetar_conversa(conversa)
        return ['Esse horário acabou de ficar indisponível. Se quiser, chame de novo pra escolher outro.']

    agendamento.data = data_val
    agendamento.hora_inicio = hora_val
    db.session.commit()
    log_evento_ia(empresa, 'AI_APPOINTMENT_RESCHEDULED', lead_id=lead.id if lead else None,
                  agendamento_id=agendamento.id, conversa_id=conversa.id, intent='APPOINTMENT_MANAGEMENT')
    resetar_conversa(conversa)
    return [f'Prontinho, remarcado para {data_val.strftime("%d/%m/%Y")} às {contexto["nova_hora"]}. 😊']


def _cancel_confirmar(empresa, lead, conversa, contexto, mensagem):
    texto = (mensagem or '').strip()
    if _RE_NAO.search(texto):
        resetar_conversa(conversa)
        return ['Combinado, seu agendamento continua confirmado.']
    if not _RE_SIM.search(texto):
        salvar_conversa(conversa, 'APPOINTMENT_MANAGEMENT', 'cancel_confirmacao', contexto)
        return ['Só para confirmar: cancelo o agendamento? (responda SIM ou NÃO)']

    agendamento = db.session.get(Agendamento, contexto['agendamento_id'])
    agendamento.status = 'cancelado'
    db.session.commit()
    log_evento_ia(empresa, 'AI_APPOINTMENT_CANCELLED', lead_id=lead.id if lead else None,
                  agendamento_id=agendamento.id, conversa_id=conversa.id, intent='APPOINTMENT_MANAGEMENT')
    resetar_conversa(conversa)
    return ['Agendamento cancelado. Se quiser marcar outro horário, é só me chamar.']
