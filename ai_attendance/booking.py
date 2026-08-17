"""Fluxo 'Agendar horário' (BOOKING) — reusa 100% o motor de agendamento já
existente (public/availability.py, mesma criação de Agendamento de
public/routes.py::agendar_submit). Nenhuma regra de conflito é reimplementada.
"""
import re
import unicodedata
from datetime import date, time as _time

from admin.tenant import tq
from models import db, Servico, Agendamento, Profissional
from public.availability import eligible_profissionais, get_available_slots
from .logging_ia import log_evento_ia
from .conversa import salvar_conversa, resetar_conversa

_RE_SIM = re.compile(r'(?i)^\s*(sim|confirmar|confirmo|isso|pode ser|ok|beleza|show)\b')
_RE_NAO = re.compile(r'(?i)^\s*(n[aã]o|cancela|deixa|melhor n[aã]o)\b')


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower().strip()
    return re.sub(r'\s+', ' ', texto)


def servicos_bookable(empresa):
    return tq(Servico).filter_by(ativo=True, agendamento_online=True).order_by(Servico.nome).all()


def _casar_servico(servicos, texto_mencionado):
    if not texto_mencionado:
        return None
    alvo = _normalizar(texto_mencionado)
    for s in servicos:
        if _normalizar(s.nome) == alvo:
            return s
    return None


def _texto_lista_servicos(servicos):
    linhas = ['Temos esses serviços disponíveis para agendamento:']
    for i, s in enumerate(servicos, start=1):
        preco = f' — R$ {s.preco:.2f}'.replace('.', ',') if (s.exibir_preco_online and s.preco) else ''
        linhas.append(f'{i}. {s.nome}{preco}')
    linhas.append('Qual você quer agendar?')
    return '\n'.join(linhas)


def _selecionar_por_indice_ou_nome(texto, itens, nomes):
    texto = (texto or '').strip()
    if texto.isdigit():
        idx = int(texto) - 1
        if 0 <= idx < len(itens):
            return itens[idx]
        return None
    alvo = _normalizar(texto)
    for item, nome in zip(itens, nomes):
        if _normalizar(nome) == alvo:
            return item
    return None


def processar(empresa, lead, telefone, conversa, nlu_result, mensagem) -> list:
    contexto = conversa.get_contexto()
    estado = conversa.estado

    if conversa.intent_ativo != 'BOOKING' or estado is None:
        log_evento_ia(empresa, 'AI_BOOKING_STARTED', lead_id=lead.id if lead else None,
                       conversa_id=conversa.id, intent='BOOKING')
        contexto = {}
        estado = 'aguardando_servico'

    servicos = servicos_bookable(empresa)
    if not servicos:
        resetar_conversa(conversa)
        return ['No momento não temos serviços disponíveis para agendamento online. '
                'Posso te transferir para um atendente, se quiser.']

    # ── Etapa: serviço ───────────────────────────────────────────────────
    if estado == 'aguardando_servico':
        servico = _casar_servico(servicos, nlu_result.get('servico_mencionado'))
        if servico is None:
            servico = _selecionar_por_indice_ou_nome(mensagem, servicos, [s.nome for s in servicos])
        if servico is None:
            salvar_conversa(conversa, 'BOOKING', 'aguardando_servico', contexto)
            return [_texto_lista_servicos(servicos)]
        contexto['servico_id'] = servico.id
        contexto['servico_nome'] = servico.nome
        return _avancar_para_profissional(empresa, lead, conversa, contexto, servico)

    servico = db.session.get(Servico, contexto.get('servico_id'))
    if not servico:
        resetar_conversa(conversa)
        return ['Esse serviço não está mais disponível. Vamos recomeçar — ' + _texto_lista_servicos(servicos)]

    # ── Etapa: profissional ──────────────────────────────────────────────
    if estado == 'aguardando_profissional':
        profissionais = eligible_profissionais(servico)
        prof = _selecionar_por_indice_ou_nome(mensagem, profissionais, [p.nome for p in profissionais])
        if prof is None:
            salvar_conversa(conversa, 'BOOKING', 'aguardando_profissional', contexto)
            linhas = ['Com qual profissional você prefere?']
            linhas += [f'{i}. {p.nome}' for i, p in enumerate(profissionais, start=1)]
            return ['\n'.join(linhas)]
        contexto['profissional_id'] = prof.id
        contexto['profissional_nome'] = prof.nome
        return _avancar_para_data(conversa, contexto)

    # ── Etapa: data ───────────────────────────────────────────────────────
    if estado == 'aguardando_data':
        data_val = parse_data_flexivel(nlu_result.get('data_mencionada')) or parse_data_flexivel(mensagem)
        if data_val is None or data_val < date.today():
            salvar_conversa(conversa, 'BOOKING', 'aguardando_data', contexto)
            return ['Para qual dia você quer agendar? (ex: 20/08 ou "amanhã")']
        contexto['data'] = data_val.isoformat()
        return _avancar_para_hora(empresa, conversa, contexto, servico)

    # ── Etapa: horário ────────────────────────────────────────────────────
    if estado == 'aguardando_hora':
        return _tratar_escolha_hora(empresa, lead, conversa, contexto, servico, nlu_result, mensagem)

    # ── Etapa: nome do cliente (se ainda não temos) ─────────────────────
    if estado == 'aguardando_nome':
        nome = (mensagem or '').strip()
        if len(nome) < 2:
            salvar_conversa(conversa, 'BOOKING', 'aguardando_nome', contexto)
            return ['Qual seu nome completo, para eu confirmar o agendamento?']
        contexto['nome_cliente'] = nome
        return _apresentar_confirmacao(conversa, contexto, servico)

    # ── Etapa: confirmação ────────────────────────────────────────────────
    if estado == 'aguardando_confirmacao':
        return _tratar_confirmacao(empresa, lead, telefone, conversa, contexto, servico, mensagem, servicos)

    # Estado desconhecido — reinicia com segurança
    resetar_conversa(conversa)
    return [_texto_lista_servicos(servicos)]


def _avancar_para_profissional(empresa, lead, conversa, contexto, servico):
    profissionais = eligible_profissionais(servico)
    if not profissionais:
        resetar_conversa(conversa)
        return [f'No momento não há profissional disponível para {servico.nome} no agendamento online. '
                'Posso te transferir para um atendente, se quiser.']
    if len(profissionais) == 1:
        contexto['profissional_id'] = profissionais[0].id
        contexto['profissional_nome'] = profissionais[0].nome
        return _avancar_para_data(conversa, contexto)
    salvar_conversa(conversa, 'BOOKING', 'aguardando_profissional', contexto)
    linhas = [f'Perfeito, {servico.nome}. Com qual profissional você prefere?']
    linhas += [f'{i}. {p.nome}' for i, p in enumerate(profissionais, start=1)]
    return ['\n'.join(linhas)]


def _avancar_para_data(conversa, contexto):
    salvar_conversa(conversa, 'BOOKING', 'aguardando_data', contexto)
    return ['Para qual dia você quer agendar? (ex: 20/08 ou "amanhã")']


_RE_DATA_BR = re.compile(r'^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$')


def parse_data_flexivel(texto):
    """Tenta ISO (YYYY-MM-DD, como a IA normalmente extrai) e depois DD/MM[/AAAA]
    (fallback quando a IA está indisponível e o texto cru do cliente chega direto).
    Ano omitido assume o próximo ano com essa data (nunca no passado)."""
    if not texto:
        return None
    texto = texto.strip()
    try:
        return date.fromisoformat(texto)
    except ValueError:
        pass
    m = _RE_DATA_BR.match(texto)
    if not m:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        if ano:
            ano = int(ano)
            if ano < 100:
                ano += 2000
            return date(ano, mes, dia)
        candidato = date(date.today().year, mes, dia)
        if candidato < date.today():
            candidato = date(candidato.year + 1, mes, dia)
        return candidato
    except ValueError:
        return None


def _parse_hora(hora_mencionada):
    if not hora_mencionada:
        return None
    m = re.match(r'^(\d{1,2}):?(\d{2})?$', hora_mencionada.strip())
    if not m:
        return None
    try:
        return _time(int(m.group(1)), int(m.group(2) or 0))
    except ValueError:
        return None


def _avancar_para_hora(empresa, conversa, contexto, servico):
    data_val = date.fromisoformat(contexto['data'])
    slots = get_available_slots(contexto['profissional_id'], servico, data_val)
    if not slots:
        salvar_conversa(conversa, 'BOOKING', 'aguardando_data', {**contexto, 'data': None})
        return [f'Não encontrei horários disponíveis para {data_val.strftime("%d/%m")}. '
                'Quer tentar outra data?']
    contexto['horarios_oferecidos'] = [h.strftime('%H:%M') for h in slots]
    salvar_conversa(conversa, 'BOOKING', 'aguardando_hora', contexto)
    linhas = [f'Horários disponíveis em {data_val.strftime("%d/%m")}:']
    linhas += [f'{i}. {h}' for i, h in enumerate(contexto['horarios_oferecidos'], start=1)]
    linhas.append('Qual horário prefere?')
    return ['\n'.join(linhas)]


def _tratar_escolha_hora(empresa, lead, conversa, contexto, servico, nlu_result, mensagem):
    data_val = date.fromisoformat(contexto['data'])
    ofertados = contexto.get('horarios_oferecidos', [])

    hora_txt = None
    if mensagem and mensagem.strip().isdigit():
        idx = int(mensagem.strip()) - 1
        if 0 <= idx < len(ofertados):
            hora_txt = ofertados[idx]
    if hora_txt is None:
        candidato = nlu_result.get('hora_mencionada') or mensagem
        hora_val = _parse_hora(candidato)
        if hora_val:
            hora_txt = hora_val.strftime('%H:%M')

    if hora_txt is None or hora_txt not in ofertados:
        salvar_conversa(conversa, 'BOOKING', 'aguardando_hora', contexto)
        linhas = [f'Não entendi o horário. Opções em {data_val.strftime("%d/%m")}:']
        linhas += [f'{i}. {h}' for i, h in enumerate(ofertados, start=1)]
        return ['\n'.join(linhas)]

    contexto['hora'] = hora_txt
    if not (lead and lead.name) and not contexto.get('nome_cliente'):
        salvar_conversa(conversa, 'BOOKING', 'aguardando_nome', contexto)
        return ['Qual seu nome completo, para eu confirmar o agendamento?']
    if lead and lead.name and not contexto.get('nome_cliente'):
        contexto['nome_cliente'] = lead.name
    return _apresentar_confirmacao(conversa, contexto, servico)


def _apresentar_confirmacao(conversa, contexto, servico):
    salvar_conversa(conversa, 'BOOKING', 'aguardando_confirmacao', contexto)
    data_val = date.fromisoformat(contexto['data'])
    preco = ''
    if servico.exibir_preco_online and servico.preco:
        preco = f' (R$ {servico.preco:.2f})'.replace('.', ',')
    resumo = (
        f'Confirmando:\n'
        f'• Serviço: {contexto["servico_nome"]}{preco}\n'
        f'• Profissional: {contexto["profissional_nome"]}\n'
        f'• Data: {data_val.strftime("%d/%m/%Y")} às {contexto["hora"]}\n\n'
        'Posso confirmar? (responda SIM ou NÃO)'
    )
    return [resumo]


def _tratar_confirmacao(empresa, lead, telefone, conversa, contexto, servico, mensagem, servicos):
    texto = (mensagem or '').strip()
    if _RE_NAO.search(texto):
        resetar_conversa(conversa)
        return ['Sem problemas, agendamento não confirmado. Se quiser recomeçar, é só me chamar.']
    if not _RE_SIM.search(texto):
        salvar_conversa(conversa, 'BOOKING', 'aguardando_confirmacao', contexto)
        return ['Só para confirmar: posso agendar? (responda SIM ou NÃO)']

    # Revalida disponibilidade — protege contra corrida entre a etapa de
    # escolha do horário e a confirmação (outro cliente pode ter pego o horário).
    data_val = date.fromisoformat(contexto['data'])
    hora_val = _parse_hora(contexto['hora'])
    slots_atuais = get_available_slots(contexto['profissional_id'], servico, data_val)
    if hora_val not in slots_atuais:
        contexto.pop('horarios_oferecidos', None)
        contexto.pop('hora', None)
        if not slots_atuais:
            resetar_conversa(conversa)
            return [f'Esse horário acabou de ser ocupado e não há mais vagas em {data_val.strftime("%d/%m")}. '
                    'Quer tentar outra data?']
        return _avancar_para_hora(empresa, conversa, contexto, servico)

    duracao_min = max(15, (servico.duracao_horas or 0) * 60 + (servico.duracao_minutos or 0))
    profissional = db.session.get(Profissional, contexto['profissional_id'])

    agendamento = Agendamento(
        nome_cliente=contexto['nome_cliente'],
        telefone=telefone,
        profissional_id=contexto['profissional_id'],
        servico_id=servico.id,
        servicos_lista=[servico],
        unidade_id=profissional.unidade_id if profissional else None,
        data=data_val,
        hora_inicio=hora_val,
        duracao_min=duracao_min,
        status='agendado',
        como_conheceu='Atendimento IA (WhatsApp)',
        empresa_id=empresa.id,
    )
    db.session.add(agendamento)
    db.session.commit()

    log_evento_ia(empresa, 'AI_BOOKING_COMPLETED', lead_id=lead.id if lead else None,
                  agendamento_id=agendamento.id, conversa_id=conversa.id, intent='BOOKING')
    resetar_conversa(conversa)
    return [f'Agendamento confirmado! {servico.nome} em {data_val.strftime("%d/%m/%Y")} às '
            f'{contexto["hora"]} com {contexto["profissional_nome"]}. Até lá! 😊']
