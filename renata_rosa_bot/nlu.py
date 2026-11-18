"""Compreensão de linguagem natural do funil da Renata Rosa — mesmo padrão
de ai_attendance/nlu.py (Anthropic com tool-use forçado), schema próprio.

A IA aqui SÓ classifica tópico/sinais da mensagem e sugere o tom da
resposta deste turno — nunca decide pontuação, status comercial ou
transferência (isso é sempre código Python determinístico em
orquestrador.py). Preço/catálogo/endereço nunca são escritos pela IA — o
texto final enviado à cliente, quando envolve dado factual, vem sempre de
template Python com dado real do banco (mesma disciplina do motor
genérico)."""
import os

TOPICOS_VALIDOS = ('ILUMINAR', 'COR', 'TRATAMENTO', 'CORTE', 'SALAO', 'HUMANO', 'OUTRO')

RESOLVE_INTENT_RR_TOOL = {
    'name': 'resolve_intent_rr',
    'description': (
        'Classifica a mensagem da cliente pro atendimento de um salão de beleza capilar, '
        'extraindo os sinais comerciais já mencionados (se houver). SEMPRE chame esta tool — '
        'nunca responda em texto livre diretamente à cliente.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'topico': {
                'type': 'string',
                'enum': list(TOPICOS_VALIDOS),
                'description': (
                    'Assunto principal desta mensagem. OUTRO quando for saudação, agradecimento, '
                    'despedida ou não permitir identificar nenhum dos 6 tópicos do menu. Se a '
                    'conversa já estava num tópico e a cliente não mudou de assunto, repita o '
                    'mesmo tópico em vez de OUTRO.'
                ),
            },
            'quer_agendar': {
                'type': 'boolean',
                'description': 'True se a cliente demonstrou intenção explícita de agendar/marcar horário.',
            },
            'quer_humano': {
                'type': 'boolean',
                'description': 'True se pediu pra falar com uma pessoa/atendente/especialista, ou perguntou disponibilidade real de horário.',
            },
            'tem_reclamacao': {
                'type': 'boolean',
                'description': 'True se há reclamação, insatisfação ou assunto delicado que exija atendimento humano.',
            },
            'demonstrou_desinteresse': {
                'type': 'boolean',
                'description': 'True se a cliente deixou claro que não quer prosseguir / só está pesquisando sem intenção.',
            },
            'servico_mencionado': {
                'type': 'string',
                'description': 'Serviço ou necessidade específica que a cliente identificou, se houver. Vazio se não.',
            },
            'resultado_desejado': {
                'type': 'string',
                'description': 'Resultado/objetivo que a cliente descreveu querer alcançar, se houver. Vazio se não.',
            },
            'prazo_mencionado': {
                'type': 'string',
                'description': 'Prazo em que a cliente pretende realizar o serviço, em texto livre (ex: "essa semana", "mês que vem"). Vazio se não mencionou.',
            },
            'prazo_ate_15_dias': {
                'type': 'boolean',
                'description': 'True só quando o prazo mencionado é claramente dentro de 15 dias.',
            },
            'perguntou_valores': {
                'type': 'boolean',
                'description': 'True se perguntou preço, valor ou condições de pagamento.',
            },
            'perguntou_disponibilidade': {
                'type': 'boolean',
                'description': 'True se perguntou disponibilidade de horário/agenda.',
            },
            'pergunta_direta': {
                'type': 'string',
                'description': 'Uma dúvida pontual e objetiva que a cliente fez, se houver, pra ser respondida diretamente. Vazio se não houve.',
            },
            'resposta_ao_cliente': {
                'type': 'string',
                'description': (
                    'Texto curto, caloroso e natural pra responder a cliente neste turno — tom de '
                    'consultora de beleza capilar. NUNCA inclua preço, promoção, horário disponível '
                    'ou resultado técnico garantido; esses dados, quando necessários, são adicionados '
                    'por fora pelo sistema, não por você.'
                ),
            },
        },
        'required': ['topico', 'resposta_ao_cliente'],
    },
}

_SYSTEM_PROMPT_BASE = (
    'Você é a Assistente Virtual do Renata Rosa Beauty Concept, uma consultora virtual de beleza '
    'capilar no WhatsApp. Tom: feminino, acolhedor, simpático, profissional, natural e consultivo — '
    'nunca robotizado ou excessivamente formal. Mensagens curtas, como se fossem de WhatsApp. Emojis '
    'com moderação. Valorize autoestima, transformação e bem-estar, sem exagero. Faça no máximo uma '
    'pergunta por mensagem. Não repita a apresentação inicial nem perguntas já respondidas nesta '
    'conversa. Não insista quando a cliente demonstrar desinteresse. Se perguntarem se você é uma IA, '
    'diga que sim, com naturalidade. NUNCA invente preço, promoção, horário disponível, resultado '
    'técnico garantido ou qualquer informação que não esteja explicitamente no contexto abaixo — nesses '
    'casos, diga que a equipe confirma os detalhes. Você NUNCA agenda, confirma, cancela ou remarca '
    'nada sozinha — isso é sempre feito pela equipe humana. Sempre chame a tool resolve_intent_rr — '
    'nunca responda fora dela.'
)


class NLUError(Exception):
    """Falha ao chamar/interpretar a resposta da Claude API — quem chama decide o fallback."""


def montar_system_prompt(empresa, estado, opcoes_menu, servicos, info_texto) -> str:
    linhas = [_SYSTEM_PROMPT_BASE, '', f'Salão: {empresa.nome}', '']

    linhas.append('Opções do menu principal (labels customizados pelo salão):')
    for opcao in opcoes_menu:
        linhas.append(f'- {opcao.intent}: "{opcao.label}"')
    linhas.append('')

    if servicos:
        linhas.append('Catálogo real de serviços (nunca cite serviço ou preço fora desta lista):')
        for s in servicos:
            preco = f' — a partir de R$ {s.preco:.2f}'.replace('.', ',') if (s.exibir_preco_online and s.preco) else ''
            linhas.append(f'- {s.nome}{preco}')
        linhas.append('')

    if info_texto:
        linhas.append('Informações do salão (só use o que está aqui):')
        linhas.append(info_texto)
        linhas.append('')

    if estado and estado.topico_ativo:
        linhas.append(f'Tópico ativo nesta conversa: {estado.topico_ativo}. Continue esse assunto, a '
                       'menos que a cliente claramente mude de assunto ou peça outra coisa.')

    return '\n'.join(linhas)


def _client():
    import anthropic
    api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise NLUError('ANTHROPIC_API_KEY não configurada.')
    timeout = float(os.getenv('AI_ATTENDANCE_TIMEOUT_SECONDS', '8'))
    return anthropic.Anthropic(api_key=api_key, timeout=timeout)


_CAMPOS_PADRAO = {
    'quer_agendar': False, 'quer_humano': False, 'tem_reclamacao': False,
    'demonstrou_desinteresse': False, 'servico_mencionado': '', 'resultado_desejado': '',
    'prazo_mencionado': '', 'prazo_ate_15_dias': False, 'perguntou_valores': False,
    'perguntou_disponibilidade': False, 'pergunta_direta': '',
}


def classificar(system_prompt: str, mensagem: str) -> dict:
    """Chama a Claude API com tool-use forçado. Levanta NLUError em qualquer
    falha (rede, timeout, resposta inesperada) — quem chama decide o
    fallback (classificar_fallback_regex), nunca deixa a cliente sem resposta."""
    model = os.getenv('AI_ATTENDANCE_MODEL', 'claude-sonnet-5').strip() or 'claude-sonnet-5'
    try:
        resp = _client().messages.create(
            model=model,
            max_tokens=512,
            system=system_prompt,
            messages=[{'role': 'user', 'content': mensagem}],
            tools=[RESOLVE_INTENT_RR_TOOL],
            tool_choice={'type': 'tool', 'name': 'resolve_intent_rr'},
        )
    except Exception as e:
        raise NLUError(f'Falha na chamada à Anthropic: {e}') from e

    for bloco in resp.content:
        if getattr(bloco, 'type', None) == 'tool_use' and bloco.name == 'resolve_intent_rr':
            dados = dict(_CAMPOS_PADRAO)
            dados.update(bloco.input or {})
            if dados.get('topico') not in TOPICOS_VALIDOS:
                dados['topico'] = 'OUTRO'
            return dados
    raise NLUError('Resposta da Anthropic sem tool_use de resolve_intent_rr.')


# ── Fallback determinístico (regex) ──────────────────────────────────────────
# Usado quando a Anthropic falha/expira — rede de segurança pro pedido de
# humano/reclamação mesmo sem a IA, nunca deixa a cliente sem resposta.
import re  # noqa: E402

_RE_HUMANO     = re.compile(r'(?i)atendente|especialista|humano|\bpessoa\b|falar com (algu[ée]m|voc[eê]s)')
_RE_RECLAMACAO = re.compile(r'(?i)reclama|p[ée]ssimo|horr[ií]vel|insatisfe|decep|absurdo')
_RE_AGENDAR    = re.compile(r'(?i)agend|marcar|marca[cç][aã]o|quero fazer (j[aá]|agora)')
_RE_DESINTERESSE = re.compile(r'(?i)s[oó] (estou |to )?pesquisando|n[aã]o quero|n[aã]o tenho interesse|deixa pra l[aá]|agora n[aã]o')
_RE_ILUMINAR   = re.compile(r'(?i)mecha|loiro|ilumina[çc][aã]o|morena ilumin')
_RE_COR        = re.compile(r'(?i)colora[çc][aã]o|tingir|cor do cabelo|mudar a cor')
_RE_TRATAMENTO = re.compile(r'(?i)tratamento|hidrata|ressecad|quebra|frizz|recuperar')
_RE_CORTE      = re.compile(r'(?i)corte|cortar|franja')
_RE_SALAO      = re.compile(r'(?i)conhecer o sal[aã]o|endere[çc]o|onde fica|localiza[çc][aã]o|funcionamento')


def classificar_fallback_regex(mensagem: str) -> dict:
    texto = (mensagem or '').strip()
    dados = dict(_CAMPOS_PADRAO)
    dados['resposta_ao_cliente'] = ''

    if _RE_HUMANO.search(texto):
        dados['quer_humano'] = True
        dados['topico'] = 'HUMANO'
        return dados
    if _RE_RECLAMACAO.search(texto):
        dados['tem_reclamacao'] = True
        dados['topico'] = 'OUTRO'
        return dados
    if _RE_AGENDAR.search(texto):
        dados['quer_agendar'] = True
    if _RE_DESINTERESSE.search(texto):
        dados['demonstrou_desinteresse'] = True

    if _RE_ILUMINAR.search(texto):
        dados['topico'] = 'ILUMINAR'
    elif _RE_COR.search(texto):
        dados['topico'] = 'COR'
    elif _RE_TRATAMENTO.search(texto):
        dados['topico'] = 'TRATAMENTO'
    elif _RE_CORTE.search(texto):
        dados['topico'] = 'CORTE'
    elif _RE_SALAO.search(texto):
        dados['topico'] = 'SALAO'
    else:
        dados['topico'] = 'OUTRO'
    return dados
