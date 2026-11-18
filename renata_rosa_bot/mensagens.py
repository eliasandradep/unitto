"""Textos fixos do funil — RN01-RN06/RN08/RN11 são cópia literal do documento
de regras de negócio do cliente. RN12/RN13 e as mensagens de erro/handoff
genérico não vieram prontas no documento — são rascunho e devem ser validadas
com o cliente antes de produção."""

MENU_PRINCIPAL = (
    'Olá! 💕 Seja muito bem-vinda ao Renata Rosa Beauty Concept!\n\n'
    'Somos especialistas em transformar cabelos e valorizar a beleza de cada mulher. ✨\n\n'
    'Vou te ajudar a encontrar o atendimento ideal!\n\n'
    'O que você deseja fazer?\n'
    '1. ✨ Mechas, loiros ou iluminado\n'
    '2. 🎨 Coloração ou correção de cor\n'
    '3. 💇‍♀️ Corte, tratamento ou escova\n'
    '4. 💬 Já sou cliente / outros assuntos'
)

TIPO_TRANSFORMACAO = (
    'Que tipo de transformação você deseja realizar? 💕\n'
    '1. Loiro com mechas\n'
    '2. Morena iluminada\n'
    '3. Retoque de mechas\n'
    '4. Mudança ou correção de cor\n'
    '5. Ainda não sei, quero orientação'
)
_TIPO_TRANSFORMACAO_LABELS = {
    1: 'Loiro com mechas',
    2: 'Morena iluminada',
    3: 'Retoque de mechas',
    4: 'Mudança ou correção de cor',
    5: 'Ainda não sei, quero orientação',
}

CORTE_TRATAMENTO_LABEL = 'Corte, tratamento ou escova'

PRAZO = (
    'Que maravilha! ✨ E para quando você está pensando em realizar essa transformação?\n'
    '1. Nesta semana\n'
    '2. Nos próximos 15 dias\n'
    '3. Ainda neste mês\n'
    '4. Estou apenas pesquisando'
)

HISTORICO_CABELO = (
    'Para entendermos melhor seu cabelo e oferecer a melhor orientação, como ele está atualmente?\n'
    '1. Cabelo natural, sem química\n'
    '2. Já tenho mechas ou luzes\n'
    '3. Tenho coloração\n'
    '4. Fiz progressiva ou outro alisamento\n'
    '5. Não tenho certeza / preciso de orientação'
)

_INVESTIMENTO_INTRO = (
    'Cada transformação é personalizada, pois respeitamos as características e '
    'necessidades de cada cabelo. 💕\n\n'
)
_INVESTIMENTO_OPCOES = (
    '\n\nO investimento final será definido após uma avaliação profissional.\n\n'
    'Essa referência está dentro do que você procura?\n'
    '1. Sim, está dentro do que procuro\n'
    '2. Gostaria de entender melhor os valores\n'
    '3. Está fora do meu orçamento neste momento'
)


def texto_investimento(texto_referencia):
    """`texto_referencia` vem de precos.texto_investimento() — nunca um valor
    inventado aqui, só a moldura da mensagem (RN05/RN19)."""
    return _INVESTIMENTO_INTRO + texto_referencia + _INVESTIMENTO_OPCOES


AVALIACAO = (
    'Gostaria de realizar uma avaliação com nossa especialista para definirmos '
    'a melhor transformação para seu cabelo? ✨\n'
    '1. Sim, gostaria\n'
    '2. Preciso confirmar\n'
    '3. Não neste momento'
)

FOTOS = (
    'Se desejar, você pode nos enviar uma foto atual do seu cabelo e uma '
    'imagem de referência do resultado que gostaria de alcançar. 💕\n\n'
    'Usamos as fotos só como referência preliminar pra nossa especialista se '
    'preparar — elas ficam guardadas no seu cadastro e só a equipe autorizada '
    'tem acesso. O envio é totalmente opcional.\n\n'
    'Quando terminar (ou se preferir não enviar agora), é só me mandar '
    'qualquer mensagem que a gente continua. 😊'
)

FOTO_RECEBIDA_PRIMEIRA = 'Recebido! 💕 Pode mandar mais uma, se quiser, ou é só seguir quando terminar.'
FOTO_FALHA_DOWNLOAD = (
    'Não consegui receber essa imagem agora 😕 Mas sem problemas, pode '
    'tentar enviar de novo ou seguir sem ela.'
)
FOTOS_LIMITE_ATINGIDO = 'Já recebi fotos suficientes, obrigada! 💕 Pode seguir quando quiser.'

AGENDAMENTO = (
    'Estamos quase terminando! 💕 Gostaria que nossa equipe verificasse os '
    'horários disponíveis para você?\n'
    '1. Sim, quero agendar\n'
    '2. Quero conversar com uma atendente antes\n'
    '3. Ainda não quero agendar'
)

HANDOFF_QUALIFICACAO = (
    'Perfeito! 💕 Já tenho as informações necessárias para te ajudar com sua transformação!\n\n'
    'Vou encaminhar seu atendimento para nossa equipe, que vai verificar os '
    'melhores horários e te ajudar com os próximos passos. ✨'
)

MORNO_FINAL = (
    'Combinado! 💕 Fico à disposição pra tirar qualquer dúvida sobre nossos '
    'serviços ou falar com uma de nossas especialistas quando quiser. Você '
    'também pode retomar seu agendamento a qualquer momento — é só me chamar! 😊'
)

FRIO_FINAL = (
    'Tudo bem! 💕 Ficamos à disposição sempre que quiser saber mais sobre o '
    'Renata Rosa Beauty Concept. Sem pressa nenhuma — quando estiver pronta, '
    'estaremos aqui. Se quiser falar com a equipe, é só pedir.'
)

HANDOFF_CLIENTE_EXISTENTE = (
    'Claro! 💕 Vou te encaminhar para nossa equipe para continuar seu atendimento.'
)

HANDOFF_PEDIDO_HUMANO = (
    'Claro! 💕 Vou te encaminhar para nossa equipe para continuar seu atendimento.'
)

HANDOFF_NAO_ENTENDIDO = (
    'Vou te encaminhar pra nossa equipe pra te ajudar melhor! 💕'
)

NAO_ENTENDIDO = 'Não entendi 😅 Digite o número de uma das opções acima.'

# ── Fase 5 — motor com NLU real (ver renata_rosa_bot/nlu.py) ────────────────
# Textos acima (RN01-RN14) ficam só pra renata_rosa_bot/fotos.py, que
# continua reaproveitado sem mudança estrutural (D7 do plano da Fase 5).

MENU_INTRO_PADRAO = (
    'Oi! 💕 Seja muito bem-vinda ao Renata Rosa Beauty Concept!\n\n'
    'Sou a assistente virtual do salão e estou aqui para te ajudar a encontrar '
    'o cuidado ideal para seus cabelos. ✨\n\n'
    'Me conta o que você gostaria de fazer hoje!'
)

HANDOFF_PADRAO = (
    'Perfeito! 💕 Vou encaminhar nossa conversa para a equipe do Renata Rosa '
    'Beauty Concept, que poderá te orientar sobre valores, disponibilidade e '
    'os próximos passos. ✨'
)

SALAO_PERGUNTA_FINAL = 'Qual desses cuidados combina mais com o que você está procurando neste momento?'
SALAO_SEM_INFO = (
    'Ainda não tenho essas informações cadastradas por aqui. Posso te '
    'transferir para uma especialista, se preferir.'
)

DESINTERESSE_FINAL = (
    'Claro! 💕 Pode pesquisar com tranquilidade. Se quiser, posso te mostrar '
    'algumas opções para você se inspirar quando quiser. 😊'
)

TOPICO_RECEBIDO_GENERICO = 'Adorei saber um pouquinho do que você procura! 💕'
OFERECER_ENCAMINHAR = (
    'Quer que eu encaminhe suas informações para nossa equipe conversar com '
    'você sobre os próximos passos?'
)
