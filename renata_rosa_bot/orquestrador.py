"""Ponto de entrada do funil da Renata Rosa — Fase 5 (motor com NLU real,
ver plano em C:\\Users\\elias\\.claude\\plans\\lovely-kindling-wind.md).
Chamado pelo webhook do WhatsApp quando renata_rosa_bot.gating.funil_ativo
(empresa) é True (ver meta_webhook/routes.py::_processar_turno_whatsapp).

Fase 5a cobre SALAO e HUMANO de ponta a ponta. Fase 5b (atual) cobre os 4
tópicos de serviço (ILUMINAR/COR/TRATAMENTO/CORTE) com um fluxo completo de
perguntas (ver fluxos.py) — uma pergunta por mensagem, terminando numa etapa
de fotos opcional (reaproveita renata_rosa_bot/fotos.py, Fase 2) pros 3
tópicos que fazem sentido (não Tratamento, cuja causa real só a avaliação
presencial confirma) e encaminhando pra equipe ao final.

Fase 5b também adiciona um atalho determinístico por número (replica
ai_attendance/orquestrador.py::_intent_por_numero) — responder só o dígito
da opção, no menu principal ou numa pergunta com alternativas numeradas,
nunca precisa de uma chamada à IA pra ser entendido.

Fase 5c adiciona, dentro do mesmo fluxo: a pergunta de unidade (só quando a
empresa tem mais de uma, só uma vez por lead — mesmo padrão de
ai_attendance/booking.py, mas com query própria tenant-scoped: o branch do
funil no webhook nunca seta g.empresa_id, então tq()/unidades_ativas()
vazaria unidades de outro tenant aqui) e a pergunta opcional de e-mail, e
passa a manter Lead.email/service/unit/message atualizados — ver
_atualizar_mensagem_lead e resumo.montar_mensagem_lead."""
import re
import unicodedata

from models import db, Servico, Unidade, RenataRosaFunilFoto

from . import mensagens, menu as menu_mod, pontuacao, handoff, status_comercial, nlu, resumo, fluxos as fluxos_mod
from . import fotos as fotos_mod
from .estado import get_or_create_estado, resetar_estado, registrar_transcricao
from ai_attendance.informacoes import texto_informacoes

_AGUARDANDO_UNIDADE = -1  # sentinela de estado.pergunta_idx — aguardando resposta da pergunta de unidade


def _intent_por_numero_menu(mensagem, opcoes):
    texto = (mensagem or '').strip()
    if not texto.isdigit():
        return None
    idx = int(texto) - 1
    if 0 <= idx < len(opcoes):
        return opcoes[idx].intent
    return None


def _catalogo(empresa):
    return Servico.query.filter_by(empresa_id=empresa.id, ativo=True).order_by(Servico.nome).all()


def _unidades_ativas(empresa):
    """Query própria (não tq()) — ver nota no docstring do módulo."""
    return Unidade.query.filter_by(empresa_id=empresa.id, ativo=True).order_by(Unidade.nome).all()


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower().strip()
    return re.sub(r'\s+', ' ', texto)


def _selecionar_unidade(mensagem, unidades):
    texto = (mensagem or '').strip()
    if texto.isdigit():
        idx = int(texto) - 1
        return unidades[idx] if 0 <= idx < len(unidades) else None
    alvo = _normalizar(texto)
    for u in unidades:
        if _normalizar(u.label()) == alvo:
            return u
    return None


def _texto_pergunta_unidade(unidades):
    linhas = ['Antes de continuar, em qual unidade você prefere ser atendida?']
    linhas += [f'{i}. {u.label()}' for i, u in enumerate(unidades, start=1)]
    return '\n'.join(linhas)


def _slug_unidade_admin(unidade):
    """O <select> de Unidade em templates/admin/lead_detail.html só
    reconhece 'varginha'/'sao_jose' (específico deste tenant) — se a unidade
    não bater com nenhum dos dois, não grava Lead.unit (evita um valor que o
    dropdown não entende); o nome completo ainda vai pro Lead.message via
    resumo.montar_mensagem_lead."""
    texto = _normalizar(f'{unidade.nome} {unidade.cidade or ""}')
    if 'varginha' in texto:
        return 'varginha'
    if 'jose' in texto:
        return 'sao_jose'
    return None


_RE_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')


def _extrair_email(mensagem):
    m = _RE_EMAIL.search(mensagem or '')
    return m.group(0) if m else None


def _atualizar_mensagem_lead(lead, estado):
    """E3/E5 do plano: mantém Lead.service (texto livre, sem FK) e
    Lead.message (resumo formatado) sempre em dia com o que já foi
    coletado — sem pergunta nova pro serviço, reaproveita o que o fluxo/IA
    já identificou (label específico, ou o nome amigável do tópico)."""
    servico = estado.servico_opcao_label or fluxos_mod.TOPICO_LABEL.get(estado.topico_ativo)
    if servico:
        lead.service = servico
    texto = resumo.montar_mensagem_lead(lead, estado)
    if texto:
        lead.message = texto
    db.session.commit()


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
    if resultado.get('quer_humano') and estado.topico_ativo in fluxos_mod.FLUXOS:
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


def _avancar_para_email_ou_seguinte(empresa, lead, estado, topico):
    if lead.email:
        # já sabemos o e-mail de um ciclo anterior — nunca pergunta de novo.
        return _avancar_apos_email(empresa, lead, estado, topico, mostrar_ack=False)
    estado.pergunta_idx = fluxos_mod.total_perguntas(topico)
    db.session.commit()
    return [mensagens.PEDIR_EMAIL]


def _avancar_apos_email(empresa, lead, estado, topico, mostrar_ack):
    total = fluxos_mod.total_perguntas(topico)
    if fluxos_mod.permite_foto(topico):
        estado.pergunta_idx = total + 1
        db.session.commit()
        textos = [mensagens.FOTOS]
        return ([mensagens.EMAIL_ANOTADO] + textos) if mostrar_ack else textos
    textos = handoff.transferir(empresa, lead, estado, 'fluxo_concluido', mensagens.HANDOFF_PADRAO)
    return ([mensagens.EMAIL_ANOTADO] + textos) if mostrar_ack else textos


def _avancar_fluxo_servico(empresa, lead, estado, topico, mensagem, media_id, media_mime_type, token):
    """Fase 5b/5c — avança a sequência de perguntas de um dos 4 tópicos de
    serviço (fluxos.py): [unidade, só na 1ª vez e só se houver mais de uma] →
    perguntas de texto → [e-mail, opcional] → [fotos, se o tópico aceitar] →
    encaminhamento, sem pergunta extra de confirmação (quem respondeu tudo já
    demonstrou engajamento suficiente). Entra/troca de tópico sempre do zero
    (RN seção 4: a cliente pode mudar de assunto quando quiser)."""
    if estado.topico_ativo != topico:
        estado.topico_ativo = topico
        status_comercial.definir_status(estado, 'em_atendimento_ia')
        unidades = _unidades_ativas(empresa)
        if not lead.unit and len(unidades) > 1:
            estado.pergunta_idx = _AGUARDANDO_UNIDADE
            db.session.commit()
            return [_texto_pergunta_unidade(unidades)]
        if not lead.unit and len(unidades) == 1:
            slug = _slug_unidade_admin(unidades[0])
            if slug:
                lead.unit = slug
        estado.pergunta_idx = 0
        db.session.commit()
        return [fluxos_mod.intro(topico), fluxos_mod.pergunta_texto(topico, 0)]

    idx = estado.pergunta_idx if estado.pergunta_idx is not None else 0

    if idx == _AGUARDANDO_UNIDADE:
        unidades = _unidades_ativas(empresa)
        unidade = _selecionar_unidade(mensagem, unidades)
        if unidade is None:
            return [_texto_pergunta_unidade(unidades)]
        slug = _slug_unidade_admin(unidade)
        if slug:
            lead.unit = slug
        estado.pergunta_idx = 0
        db.session.commit()
        return [fluxos_mod.intro(topico), fluxos_mod.pergunta_texto(topico, 0)]

    total = fluxos_mod.total_perguntas(topico)

    if idx < total:
        label = fluxos_mod.opcao_por_numero(fluxos_mod.opcoes_da_pergunta(topico, idx), mensagem)
        if label:
            estado.pt_servico_especifico = True
            estado.servico_opcao_label = label
            _recalcular_score(estado)

        # Fallback determinístico (E4 do plano): se a IA não extraiu
        # objetivo/prazo desse turno, mas a pergunta respondida É a pergunta
        # de objetivo/prazo desse tópico, usa o texto literal da cliente —
        # nunca fica "não informado" só por depender da inferência livre.
        campo = fluxos_mod.campo_da_pergunta(topico, idx)
        texto_resposta = (mensagem or '').strip()
        if campo == 'resultado_desejado' and not estado.pt_resultado_desejado and texto_resposta:
            estado.pt_resultado_desejado = True
            estado.resultado_desejado_texto = texto_resposta[:500]
            _recalcular_score(estado)
        elif campo == 'prazo' and not estado.pt_prazo_informado and texto_resposta:
            estado.pt_prazo_informado = True
            estado.prazo_texto = texto_resposta[:200]
            _recalcular_score(estado)

        next_idx = idx + 1
        if next_idx < total:
            estado.pergunta_idx = next_idx
            db.session.commit()
            return [fluxos_mod.pergunta_texto(topico, next_idx)]

        return _avancar_para_email_ou_seguinte(empresa, lead, estado, topico)

    if idx == total:
        # resposta à pergunta de e-mail (etapa opcional, universal aos 4 fluxos)
        email = _extrair_email(mensagem)
        if email:
            lead.email = email
        return _avancar_apos_email(empresa, lead, estado, topico, mostrar_ack=bool(email))

    # idx == total + 1 — etapa de fotos (só alcançável quando permite_foto)
    if media_id:
        if fotos_mod.limite_atingido(lead):
            return [mensagens.FOTOS_LIMITE_ATINGIDO]
        era_primeira = RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).count() == 0
        try:
            fotos_mod.baixar_e_salvar(empresa, lead, media_id, media_mime_type, token)
        except Exception:
            return [mensagens.FOTO_FALHA_DOWNLOAD]
        if era_primeira:
            estado.pt_referencia_foto = True
            _recalcular_score(estado)
            db.session.commit()
            return [mensagens.FOTO_RECEBIDA_PRIMEIRA]
        return []

    return handoff.transferir(empresa, lead, estado, 'fluxo_concluido_com_fotos', mensagens.HANDOFF_PADRAO)


def processar_mensagem(empresa, lead, telefone, mensagem, token=None, media_id=None, media_mime_type=None) -> list:
    """Retorna a lista de textos a enviar à cliente, em ordem. Wrapper fino:
    no finally, mantém Lead.message como um resumo formatado das respostas
    já coletadas (ver resumo.montar_mensagem_lead) — cobre todo retorno de
    _processar_mensagem_interno sem precisar duplicar a chamada em cada um."""
    estado = get_or_create_estado(empresa, lead)
    try:
        return _processar_mensagem_interno(empresa, lead, estado, mensagem, token, media_id, media_mime_type)
    finally:
        _atualizar_mensagem_lead(lead, estado)


def _processar_mensagem_interno(empresa, lead, estado, mensagem, token, media_id, media_mime_type):
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

    # Atalhos determinísticos (D1/E1 do plano) — nunca gastam uma chamada à
    # IA pra entender um dígito solto (menu principal, pergunta de unidade,
    # ou pergunta de fluxo que já lista alternativas numeradas, caso do
    # Tratamento) nem pra processar uma foto na etapa de fotos (mensagem é
    # só o placeholder '[image]', não há nada pra classificar). A etapa de
    # e-mail (idx == total_topico) é texto livre de propósito — sem atalho,
    # precisa continuar passando pela IA pra não perder reclamação/pedido de
    # humano nessa etapa.
    resultado = None
    if estado.topico_ativo is None:
        intent_numero = _intent_por_numero_menu(mensagem, opcoes)
        if intent_numero:
            resultado = {'topico': intent_numero, 'resposta_ao_cliente': ''}
    elif estado.topico_ativo in fluxos_mod.FLUXOS and estado.pergunta_idx is not None:
        if estado.pergunta_idx == _AGUARDANDO_UNIDADE:
            if _selecionar_unidade(mensagem, _unidades_ativas(empresa)):
                resultado = {'topico': estado.topico_ativo, 'resposta_ao_cliente': ''}
        else:
            total_topico = fluxos_mod.total_perguntas(estado.topico_ativo)
            if estado.pergunta_idx < total_topico:
                opcoes_pergunta = fluxos_mod.opcoes_da_pergunta(estado.topico_ativo, estado.pergunta_idx)
                if fluxos_mod.opcao_por_numero(opcoes_pergunta, mensagem):
                    resultado = {'topico': estado.topico_ativo, 'resposta_ao_cliente': ''}
            elif media_id and estado.pergunta_idx == total_topico + 1:
                resultado = {'topico': estado.topico_ativo, 'resposta_ao_cliente': ''}

    if resultado is None:
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

    if topico in fluxos_mod.FLUXOS:
        textos = _avancar_fluxo_servico(empresa, lead, estado, topico, mensagem, media_id, media_mime_type, token)
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
