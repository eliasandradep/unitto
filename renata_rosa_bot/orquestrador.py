"""Ponto de entrada do funil da Renata Rosa — Fase 5 (motor com NLU real,
ver plano em C:\\Users\\elias\\.claude\\plans\\lovely-kindling-wind.md).
Chamado pelo webhook do WhatsApp quando renata_rosa_bot.gating.funil_ativo
(empresa) é True (ver meta_webhook/routes.py::_processar_turno_whatsapp).

Fase 5a cobre os tópicos SALAO e HUMANO de ponta a ponta. Os 4 tópicos de
serviço (ILUMINAR/COR/TRATAMENTO/CORTE) ainda não têm qualificação própria
por pergunta — a IA reconhece o interesse com empatia e oferece encaminhar
pra equipe, pra nunca deixar a cliente travada esperando uma pergunta que
ainda não existe (Fase 5b implementa a qualificação completa desses 4,
reaproveitando renata_rosa_bot/fotos.py nesse momento)."""
from models import db, Servico

from . import mensagens, menu as menu_mod, pontuacao, handoff, status_comercial, nlu
from .estado import get_or_create_estado, resetar_estado, registrar_transcricao
from ai_attendance.informacoes import texto_informacoes

_TOPICOS_SERVICO_SEM_FLUXO_PROPRIO = ('ILUMINAR', 'COR', 'TRATAMENTO', 'CORTE')


def _catalogo(empresa):
    return Servico.query.filter_by(empresa_id=empresa.id, ativo=True).order_by(Servico.nome).all()


def _aplicar_sinais(estado, resultado):
    """Marca as flags de pontuação (seção 5.1) uma única vez por ciclo —
    nunca desmarca sozinha, só o reset explícito do funil zera de novo."""
    if resultado.get('servico_mencionado'):
        estado.pt_servico_especifico = True
        estado.servico_opcao_label = resultado['servico_mencionado'][:100]
    if resultado.get('resultado_desejado'):
        estado.pt_resultado_desejado = True
        estado.resultado_desejado_texto = resultado['resultado_desejado'][:500]
    if resultado.get('prazo_mencionado'):
        estado.pt_prazo_informado = True
        estado.prazo_texto = resultado['prazo_mencionado'][:200]
        if resultado.get('prazo_ate_15_dias'):
            estado.pt_prazo_15dias = True
    if resultado.get('perguntou_valores'):
        estado.pt_perguntou_valores = True
    if resultado.get('perguntou_disponibilidade'):
        estado.pt_perguntou_disponibilidade = True
    if resultado.get('quer_humano') and estado.topico_ativo in _TOPICOS_SERVICO_SEM_FLUXO_PROPRIO:
        # pediu atendente já estando numa qualificação de serviço = sinal de
        # quem quer contratar, não só tirar dúvida (seção 5.1).
        estado.pt_pediu_humano_contratar = True
    if resultado.get('quer_agendar'):
        estado.pt_intencao_agendar = True
        estado.forcar_quente = True


def _recalcular_score(estado):
    score, classificacao, _ = pontuacao.calcular_pontuacao(estado)
    estado.score_total = score
    estado.classificacao = pontuacao.QUENTE if estado.forcar_quente else classificacao


def processar_mensagem(empresa, lead, telefone, mensagem, token=None, media_id=None, media_mime_type=None) -> list:
    """Retorna a lista de textos a enviar à cliente, em ordem."""
    estado = get_or_create_estado(empresa, lead)

    # Funil já tinha concluído (transferido) — uma nova mensagem é um novo
    # atendimento, não a continuação de algo fechado.
    if estado.estado == 'concluido':
        resetar_estado(estado)
        status_comercial.definir_status(estado, 'novo_lead')

    # Lead que a própria IA já marcou 'sem_interesse' reengaja sozinho — só
    # 'perdido'/outros status manuais ficam protegidos, não reabrem sozinhos
    # (ver STATUS_MANUAIS em status_comercial.py).
    if estado.status_comercial == 'sem_interesse':
        status_comercial.definir_status(estado, 'em_atendimento_ia')

    registrar_transcricao(estado, cliente=mensagem)

    opcoes = menu_mod.opcoes_ativas(empresa)
    servicos = _catalogo(empresa)
    info_texto = texto_informacoes(empresa)
    system_prompt = nlu.montar_system_prompt(empresa, estado, opcoes, servicos, info_texto)
    try:
        resultado = nlu.classificar(system_prompt, mensagem)
    except nlu.NLUError:
        resultado = nlu.classificar_fallback_regex(mensagem)

    # Prioridades (seção 5.3) — sempre antes do score/tópico, e
    # independentes de qualquer coisa que a cliente já tenha respondido.
    if resultado.get('tem_reclamacao') or resultado.get('quer_humano'):
        textos = handoff.transferir(empresa, lead, estado, 'pedido_ou_reclamacao', mensagens.HANDOFF_PADRAO)
        registrar_transcricao(estado, bot=textos)
        return textos

    _aplicar_sinais(estado, resultado)
    _recalcular_score(estado)
    db.session.commit()

    if resultado.get('demonstrou_desinteresse'):
        status_comercial.definir_status(estado, 'sem_interesse')
        textos = [mensagens.DESINTERESSE_FINAL]
        registrar_transcricao(estado, bot=textos)
        return textos

    # Lead Quente (seção 5.2) transfere sempre — seja por pontuação natural
    # (score >= 60) ou por override explícito (forcar_quente, seção 5.3) —
    # "evitar perguntas adicionais desnecessárias, notificar a equipe".
    if estado.classificacao == pontuacao.QUENTE or estado.forcar_quente:
        textos = handoff.transferir(empresa, lead, estado, 'lead_quente', mensagens.HANDOFF_PADRAO)
        registrar_transcricao(estado, bot=textos)
        return textos

    topico = resultado.get('topico') or 'OUTRO'
    if topico == 'OUTRO' and estado.topico_ativo:
        topico = estado.topico_ativo  # continua o assunto em vez de voltar ao menu sozinha

    if topico == 'HUMANO':
        textos = handoff.transferir(empresa, lead, estado, 'pedido_humano', mensagens.HANDOFF_PADRAO)
        registrar_transcricao(estado, bot=textos)
        return textos

    if topico == 'SALAO':
        estado.topico_ativo = 'SALAO'
        status_comercial.definir_status(estado, 'em_atendimento_ia')
        db.session.commit()
        textos = [info_texto or mensagens.SALAO_SEM_INFO, mensagens.SALAO_PERGUNTA_FINAL]
        registrar_transcricao(estado, bot=textos)
        return textos

    if topico in _TOPICOS_SERVICO_SEM_FLUXO_PROPRIO:
        estado.topico_ativo = topico
        status_comercial.definir_status(estado, 'em_atendimento_ia')
        db.session.commit()
        resposta_ia = (resultado.get('resposta_ao_cliente') or '').strip()
        textos = [resposta_ia or mensagens.TOPICO_RECEBIDO_GENERICO, mensagens.OFERECER_ENCAMINHAR]
        registrar_transcricao(estado, bot=textos)
        return textos

    # OUTRO sem tópico ativo — responde dúvida pontual (se houver) e
    # reapresenta o menu principal.
    textos = []
    pergunta_direta = (resultado.get('pergunta_direta') or '').strip()
    resposta_ia = (resultado.get('resposta_ao_cliente') or '').strip()
    if pergunta_direta and resposta_ia:
        textos.append(resposta_ia)
    textos.append(menu_mod.menu_texto(empresa))
    registrar_transcricao(estado, bot=textos)
    return textos
