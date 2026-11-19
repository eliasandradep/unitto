"""Fluxos completos de qualificação por tópico de serviço (Fase 5b, seções
4.1-4.4 da especificação) — copy persuasiva, uma pergunta por mensagem, pra
chegar no encaminhamento com o máximo de contexto possível pra atendente só
precisar agendar. Dado puro (textos/estrutura); a mecânica de avanço fica em
orquestrador.py, junto da pontuação/handoff que ela já aciona.

`permite_foto` (Iluminar/Cor/Corte, seções 4.1 e 4.4 citam referência
visual) liga a etapa de fotos (renata_rosa_bot/fotos.py, Fase 2) ao final das
perguntas de texto — Tratamento (seção 4.3) encaminha direto, sem essa etapa,
pois a avaliação final é sempre presencial com a profissional.

Cada pergunta é (texto, opcoes) — `opcoes` é um dict {numero: label} só
quando a pergunta já lista alternativas numeradas (caso do Tratamento), pra
dígito solto virar um rótulo legível no resumo em vez do número cru."""

_CAUSAS_TRATAMENTO = {
    1: 'Ressecamento',
    2: 'Quebra e fragilidade',
    3: 'Frizz',
    4: 'Falta de brilho',
    5: 'Danos químicos',
    6: 'Não sei, quero uma avaliação',
}

FLUXOS = {
    'ILUMINAR': {
        'intro': (
            'Que escolha maravilhosa! ✨ Uma iluminação bem planejada traz luz, '
            'movimento e valoriza muito o seu visual — é uma das transformações '
            'que a gente mais ama fazer aqui no salão! 💫\n\n'
            'Vou te fazer algumas perguntinhas rápidas pra já deixar tudo pronto '
            'pra nossa especialista te atender super bem.'
        ),
        'perguntas': [
            ('Pra começar: você já tem mechas ou luzes, ou seria a sua primeira vez? 💛', None),
            ('Seu cabelo tem alguma química no momento, como alisamento ou coloração?', None),
            ('Você imagina algo mais discreto e natural, ou um resultado bem marcante e cheio de luz? ✨', None),
            ('E pra quando você está pensando em fazer essa transformação?', None),
        ],
        'permite_foto': True,
    },
    'COR': {
        'intro': (
            'Renovar a cor é uma das formas mais rápidas de dar uma nova vida '
            'pro visual! 🎨 Vou te fazer algumas perguntas rápidas pra já '
            'adiantar seu atendimento.'
        ),
        'perguntas': [
            ('Qual é a cor atual do seu cabelo?', None),
            ('Seu cabelo já tem alguma química, como alisamento ou outra coloração?', None),
            ('Você já tem uma tonalidade em mente, ou prefere sugestões da nossa especialista? 💭', None),
            ('E pra quando você pretende fazer essa mudança?', None),
        ],
        'permite_foto': True,
    },
    'TRATAMENTO': {
        'intro': (
            'Vamos cuidar desses fios! 💖 Cada cabelo pede um tratamento '
            'diferente, então me conta um pouco mais pra eu já te direcionar '
            'certinha.'
        ),
        'perguntas': [
            (
                'O que mais está te incomodando no seu cabelo hoje?\n'
                '1. Ressecamento\n2. Quebra e fragilidade\n3. Frizz\n'
                '4. Falta de brilho\n5. Danos químicos\n6. Não sei, quero uma avaliação',
                _CAUSAS_TRATAMENTO,
            ),
            ('Entendido! 💕 E pra quando você pretende fazer esse tratamento?', None),
        ],
        'permite_foto': False,
    },
    'CORTE': {
        'intro': (
            'Às vezes um corte novo é tudo que a gente precisa pra renovar o '
            'visual! ✂️ Vou te fazer algumas perguntinhas rápidas.'
        ),
        'perguntas': [
            ('Qual é o comprimento atual do seu cabelo?', None),
            ('Como você imagina o resultado final? Me conta um pouquinho! 💫', None),
            ('E pra quando você está pensando em fazer esse corte?', None),
        ],
        'permite_foto': True,
    },
}


def intro(topico):
    return FLUXOS[topico]['intro']


def total_perguntas(topico):
    return len(FLUXOS[topico]['perguntas'])


def pergunta_texto(topico, idx):
    return FLUXOS[topico]['perguntas'][idx][0]


def opcoes_da_pergunta(topico, idx):
    return FLUXOS[topico]['perguntas'][idx][1]


def permite_foto(topico):
    return FLUXOS[topico]['permite_foto']


def opcao_por_numero(opcoes, mensagem):
    """Mapeia uma resposta de dígito solto pro label da opção numerada da
    pergunta atual, se houver. None quando a pergunta não tem opções
    numeradas ou o dígito não corresponde a nenhuma."""
    if not opcoes:
        return None
    texto = (mensagem or '').strip()
    if not texto.isdigit():
        return None
    return opcoes.get(int(texto))
