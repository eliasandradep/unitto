"""Compreensão de linguagem natural do atendimento por IA — Anthropic (Claude)
com tool-use, sempre "grounded" nos dados reais do tenant.

A IA aqui SÓ classifica intent, extrai slots (serviço/data/hora mencionados) e
gera o tom conversacional da resposta deste turno — nunca decide nem executa
ação de negócio (isso é sempre código Python determinístico em orquestrador.py
e nos módulos de fluxo). Para dados factuais críticos (preço, horário,
endereço, confirmação de agendamento), o texto final enviado ao cliente é
montado por template Python com dados reais do banco, não copiado direto do
campo `resposta_ao_cliente` da IA.
"""
import os
import re
from datetime import date

INTENTS_VALIDOS = ('BOOKING', 'APPOINTMENT_MANAGEMENT', 'SERVICES',
                    'INFORMATION', 'HUMAN_HANDOFF', 'UNCLEAR')

RESOLVE_INTENT_TOOL = {
    'name': 'resolve_intent',
    'description': (
        'Classifica a mensagem do cliente em UM dos intents do menu de atendimento, '
        'extraindo os parâmetros já mencionados (se houver). SEMPRE chame esta tool — '
        'nunca responda em texto livre diretamente ao cliente.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'intent': {
                'type': 'string',
                'enum': list(INTENTS_VALIDOS),
                'description': 'UNCLEAR quando a mensagem não permite identificar nenhuma das 5 opções do menu.',
            },
            'sub_acao': {
                'type': 'string',
                'enum': ['VIEW', 'RESCHEDULE', 'CANCEL', 'NONE'],
                'description': 'Só relevante quando intent=APPOINTMENT_MANAGEMENT.',
            },
            'servico_mencionado': {
                'type': 'string',
                'description': ('Nome do serviço citado pelo cliente, se houver — DEVE bater com um '
                                 'serviço real da lista fornecida no contexto; se não bater com nada '
                                 'da lista, deixe vazio.'),
            },
            'data_mencionada': {
                'type': 'string',
                'description': ('Data ISO (YYYY-MM-DD) se o cliente mencionou, resolvendo relativos '
                                 'como "amanhã"/"segunda que vem" contra a data atual informada no contexto.'),
            },
            'hora_mencionada': {
                'type': 'string',
                'description': 'Horário HH:MM se mencionado.',
            },
            'resposta_ao_cliente': {
                'type': 'string',
                'description': ('Texto curto e natural para responder ao cliente neste turno, coerente '
                                 'com o intent. Use SOMENTE dados fornecidos no contexto — nunca invente '
                                 'preço, serviço, horário ou qualquer dado de agendamento.'),
            },
        },
        'required': ['intent', 'resposta_ao_cliente'],
    },
}

_SYSTEM_PROMPT_BASE = (
    'Você é o atendimento automático por WhatsApp de um negócio de agendamentos (salão, '
    'clínica, barbearia etc — não presuma o segmento, use só o que estiver no contexto). '
    'Seja objetivo e natural, evite textos longos. Faça uma pergunta por vez quando precisar '
    'coletar informação. Sempre chame a tool resolve_intent — nunca responda fora dela. '
    'NUNCA invente preço, serviço, horário disponível, endereço ou qualquer dado de agendamento '
    'que não esteja explicitamente no contexto fornecido abaixo. Se não souber algo, diga que vai '
    'confirmar com um atendente em vez de inventar.'
)


class NLUError(Exception):
    """Falha ao chamar/interpretar a resposta da Claude API — quem chama decide o fallback."""


def montar_system_prompt(empresa, opcoes_menu, servicos, info_texto, conversa) -> str:
    linhas = [_SYSTEM_PROMPT_BASE, '', f'Negócio: {empresa.nome}', '']

    linhas.append('Opções do menu de atendimento (labels customizados pelo tenant):')
    for opcao in opcoes_menu:
        linhas.append(f'- {opcao.intent}: "{opcao.label}"')
    linhas.append('')

    if servicos:
        linhas.append('Catálogo real de serviços (nunca cite serviço fora desta lista):')
        for s in servicos:
            preco = f' — R$ {s.preco:.2f}'.replace('.', ',') if (s.exibir_preco_online and s.preco) else ''
            linhas.append(f'- {s.nome}{preco}')
    else:
        linhas.append('Nenhum serviço cadastrado para agendamento online no momento.')
    linhas.append('')

    linhas.append(f'Data de hoje: {date.today().isoformat()}')
    linhas.append('')

    if info_texto:
        linhas.append('Informações do estabelecimento (só use o que está aqui):')
        linhas.append(info_texto)
        linhas.append('')

    if conversa and conversa.intent_ativo:
        linhas.append(f'Estado atual da conversa: no meio do fluxo {conversa.intent_ativo}'
                       f'{f", etapa {conversa.estado}" if conversa.estado else ""}. '
                       'Continue esse fluxo em vez de reapresentar o menu, a menos que o '
                       'cliente peça claramente pra voltar/mudar de assunto.')

    return '\n'.join(linhas)


def _client():
    import anthropic
    api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise NLUError('ANTHROPIC_API_KEY não configurada.')
    timeout = float(os.getenv('AI_ATTENDANCE_TIMEOUT_SECONDS', '8'))
    return anthropic.Anthropic(api_key=api_key, timeout=timeout)


def classificar(system_prompt: str, mensagem: str) -> dict:
    """Chama a Claude API com tool-use forçado. Levanta NLUError em qualquer
    falha (rede, timeout, resposta inesperada) — o orquestrador decide o
    fallback (classificar_fallback_regex), nunca deixa o cliente sem resposta."""
    model = os.getenv('AI_ATTENDANCE_MODEL', 'claude-sonnet-5').strip() or 'claude-sonnet-5'
    try:
        resp = _client().messages.create(
            model=model,
            max_tokens=512,
            system=system_prompt,
            messages=[{'role': 'user', 'content': mensagem}],
            tools=[RESOLVE_INTENT_TOOL],
            tool_choice={'type': 'tool', 'name': 'resolve_intent'},
        )
    except Exception as e:
        raise NLUError(f'Falha na chamada à Anthropic: {e}') from e

    for bloco in resp.content:
        if getattr(bloco, 'type', None) == 'tool_use' and bloco.name == 'resolve_intent':
            dados = dict(bloco.input or {})
            if dados.get('intent') not in INTENTS_VALIDOS:
                dados['intent'] = 'UNCLEAR'
            return dados
    raise NLUError('Resposta da Anthropic sem tool_use de resolve_intent.')


# ── Fallback determinístico (regex) ──────────────────────────────────────────
# Extensão de meta_webhook/routes.py::_classificar_intent_whatsapp pros 5
# intents — usado quando a Anthropic falha/expira, ou como rede de segurança
# pro pedido de humano mesmo com a opção desativada no menu configurável.

_RE_HANDOFF   = re.compile(r'(?i)^\s*5\b|atendente|humano|\bpessoa\b|falar com (algu[ée]m|voc[eê]s)')
_RE_BOOKING   = re.compile(r'(?i)^\s*1\b|agend|marcar|marca[cç][aã]o|hor[aá]rio dispon')
_RE_MEU_AG    = re.compile(r'(?i)^\s*2\b|meu agendamento|remarcar|reagendar|cancelar (meu|o) agendamento|cancelar hor[aá]rio')
_RE_SERVICOS  = re.compile(r'(?i)^\s*3\b|servi[cç]o|pre[cç]o|valor|quanto custa')
_RE_INFO      = re.compile(r'(?i)^\s*4\b|endere[cç]o|onde fica|localiza[cç][aã]o|hor[aá]rio de funcionamento|forma(s)? de pagamento')


def classificar_fallback_regex(mensagem: str) -> dict:
    texto = (mensagem or '').strip()
    if _RE_HANDOFF.search(texto):
        intent = 'HUMAN_HANDOFF'
    elif _RE_MEU_AG.search(texto):
        intent = 'APPOINTMENT_MANAGEMENT'
    elif _RE_BOOKING.search(texto):
        intent = 'BOOKING'
    elif _RE_SERVICOS.search(texto):
        intent = 'SERVICES'
    elif _RE_INFO.search(texto):
        intent = 'INFORMATION'
    else:
        intent = 'UNCLEAR'
    return {'intent': intent, 'sub_acao': 'NONE', 'servico_mencionado': '',
            'data_mencionada': '', 'hora_mencionada': '', 'resposta_ao_cliente': ''}
