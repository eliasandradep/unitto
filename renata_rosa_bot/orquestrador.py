"""Ponto de entrada do funil de qualificação da Renata Rosa — chamado pelo
webhook do WhatsApp quando renata_rosa_bot.gating.funil_ativo(empresa) é True
(ver meta_webhook/routes.py::_processar_turno_whatsapp). State machine 100%
determinística por dígito — sem chamada a LLM/NLU (RN01-RN08 são todo menu
numerado fixo; RN19 pede explicitamente "não inventar")."""
import re

from models import db, RenataRosaFunilFoto

from . import mensagens, precos, pontuacao, handoff, fotos as fotos_mod, status_comercial
from .estado import get_or_create_estado, resetar_estado, registrar_transcricao

_RE_ATENDENTE = re.compile(r'(?i)atendente|humano|\bpessoa\b')
_RE_MENU      = re.compile(r'(?i)^\s*(menu|voltar\s+ao\s+in[ií]cio|in[ií]cio)\s*$')
_RE_CORRIGIR  = re.compile(r'(?i)corrigi|resposta\s+anterior')


def _parse_opcao(mensagem, n_opcoes):
    texto = (mensagem or '').strip()
    if not texto.isdigit():
        return None
    idx = int(texto)
    return idx if 1 <= idx <= n_opcoes else None


def _texto_pergunta(empresa, estado):
    if estado.estado == 'tipo_transformacao':
        return mensagens.TIPO_TRANSFORMACAO
    if estado.estado == 'prazo':
        return mensagens.PRAZO
    if estado.estado == 'historico_cabelo':
        return mensagens.HISTORICO_CABELO
    if estado.estado == 'investimento':
        return mensagens.texto_investimento(precos.texto_investimento(empresa, estado.servico_opcao_idx))
    if estado.estado == 'avaliacao':
        return mensagens.AVALIACAO
    if estado.estado == 'fotos':
        return mensagens.FOTOS
    if estado.estado == 'agendamento':
        return mensagens.AGENDAMENTO
    return mensagens.MENU_PRINCIPAL


def _nao_entendido(empresa, lead, estado):
    """RN14: 2 respostas não reconhecidas seguidas transferem pra humano.
    Na 1ª falha só repete a pergunta — sem penalizar a 1ª mensagem de um
    contato novo (ex: 'Oi'), que nunca teve uma pergunta feita ainda."""
    estado.contador_nao_entendido = (estado.contador_nao_entendido or 0) + 1
    if estado.contador_nao_entendido >= 2:
        db.session.commit()
        return handoff.transferir(empresa, lead, estado, 'nao_entendido_2x', mensagens.HANDOFF_NAO_ENTENDIDO)
    db.session.commit()
    return [mensagens.NAO_ENTENDIDO, _texto_pergunta(empresa, estado)]


def _h_menu_principal(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 4)
    if opcao is None:
        # Nunca escala pra handoff a partir do menu principal — cobre tanto
        # a 1ª mensagem de um contato novo (qualquer coisa que não é 1-4)
        # quanto um "oi"/"bom dia" no meio do caminho; só reapresenta o menu.
        return [mensagens.MENU_PRINCIPAL]
    estado.contador_nao_entendido = 0

    if opcao == 4:  # já sou cliente / outros assuntos — handoff direto, sem pontuação
        if lead.status == 'novo':
            lead.status = 'cliente_existente'
        db.session.commit()
        return handoff.transferir(empresa, lead, estado, 'ja_cliente', mensagens.HANDOFF_CLIENTE_EXISTENTE)

    if opcao == 3:  # corte/tratamento/escova — fluxo simplificado (RN02)
        estado.fluxo = 'corte_tratamento'
        estado.servico_opcao_label = mensagens.CORTE_TRATAMENTO_LABEL
        estado.servico_identificado = True
        estado.estado_anterior = 'menu_principal'
        estado.estado = 'prazo'
        db.session.commit()
        status_comercial.definir_status(estado, 'em_qualificacao')
        return [mensagens.PRAZO]

    estado.fluxo = 'mechas_coloracao'
    estado.estado_anterior = 'menu_principal'
    estado.estado = 'tipo_transformacao'
    db.session.commit()
    status_comercial.definir_status(estado, 'em_qualificacao')
    return [mensagens.TIPO_TRANSFORMACAO]


def _h_tipo_transformacao(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 5)
    if opcao is None:
        return _nao_entendido(empresa, lead, estado)
    estado.contador_nao_entendido = 0
    estado.servico_opcao_idx = opcao
    estado.servico_opcao_label = mensagens._TIPO_TRANSFORMACAO_LABELS[opcao]
    estado.servico_identificado = (opcao != 5)
    estado.estado_anterior = 'tipo_transformacao'
    estado.estado = 'prazo'
    db.session.commit()
    return [mensagens.PRAZO]


def _h_prazo(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 4)
    if opcao is None:
        return _nao_entendido(empresa, lead, estado)
    estado.contador_nao_entendido = 0
    estado.prazo_opcao = opcao
    estado.estado_anterior = 'prazo'
    if estado.fluxo == 'corte_tratamento':
        # RN02: fluxo simplificado pula histórico/investimento/avaliação
        estado.estado = 'agendamento'
        db.session.commit()
        return [mensagens.AGENDAMENTO]
    estado.estado = 'historico_cabelo'
    db.session.commit()
    return [mensagens.HISTORICO_CABELO]


def _h_historico_cabelo(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 5)
    if opcao is None:
        return _nao_entendido(empresa, lead, estado)
    estado.contador_nao_entendido = 0
    estado.historico_cabelo_opcao = opcao
    estado.estado_anterior = 'historico_cabelo'
    estado.estado = 'investimento'
    db.session.commit()
    texto = mensagens.texto_investimento(precos.texto_investimento(empresa, estado.servico_opcao_idx))
    return [texto]


def _h_investimento(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 3)
    if opcao is None:
        return _nao_entendido(empresa, lead, estado)
    estado.contador_nao_entendido = 0
    estado.investimento_opcao = opcao
    estado.estado_anterior = 'investimento'
    estado.estado = 'avaliacao'
    db.session.commit()
    return [mensagens.AVALIACAO]


def _h_avaliacao(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 3)
    if opcao is None:
        return _nao_entendido(empresa, lead, estado)
    estado.contador_nao_entendido = 0
    estado.avaliacao_opcao = opcao
    estado.estado_anterior = 'avaliacao'
    estado.estado = 'fotos'
    db.session.commit()
    return [mensagens.FOTOS]


def _h_fotos(empresa, lead, estado, mensagem, media_id=None, media_mime_type=None, token=None):
    """RN07 — sem menu numerado (único estado assim no funil). Imagem: baixa
    e grava, continua nesse estado; qualquer texto: avança pra 'agendamento'
    sem analisar o conteúdo — "ausência de foto não pode impedir a
    continuidade" é satisfeito por desenho, não por uma opção de pular."""
    if media_id:
        if fotos_mod.limite_atingido(lead):
            return [mensagens.FOTOS_LIMITE_ATINGIDO]
        era_primeira = RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).count() == 0
        try:
            fotos_mod.baixar_e_salvar(empresa, lead, media_id, media_mime_type, token)
        except Exception:
            return [mensagens.FOTO_FALHA_DOWNLOAD]
        return [mensagens.FOTO_RECEBIDA_PRIMEIRA] if era_primeira else []

    estado.estado_anterior = 'fotos'
    estado.estado = 'agendamento'
    db.session.commit()
    return [mensagens.AGENDAMENTO]


def _h_agendamento(empresa, lead, estado, mensagem):
    opcao = _parse_opcao(mensagem, 3)
    if opcao is None:
        return _nao_entendido(empresa, lead, estado)
    estado.contador_nao_entendido = 0
    estado.agendamento_opcao = opcao

    score, classificacao, _breakdown = pontuacao.calcular_pontuacao(estado)
    estado.score_total = score
    estado.classificacao = classificacao
    if lead.status not in ('convertido', 'perdido'):
        lead.status = 'qualificado'
    db.session.commit()
    status_comercial.definir_status(estado, f'qualificado_{classificacao}')

    # RN11/RN14: QUENTE transfere sempre; MORNO/FRIO também transferem se
    # pediu agendamento ou quer conversar com atendente antes (opção 1 ou 2).
    if classificacao == pontuacao.QUENTE or opcao in (1, 2):
        return handoff.transferir(empresa, lead, estado, 'qualificacao_completa', mensagens.HANDOFF_QUALIFICACAO)

    estado.estado = 'concluido'
    db.session.commit()
    return [mensagens.MORNO_FINAL if classificacao == pontuacao.MORNO else mensagens.FRIO_FINAL]


_HANDLERS = {
    'menu_principal':     _h_menu_principal,
    'tipo_transformacao': _h_tipo_transformacao,
    'prazo':              _h_prazo,
    'historico_cabelo':   _h_historico_cabelo,
    'investimento':       _h_investimento,
    'avaliacao':          _h_avaliacao,
    'fotos':              _h_fotos,
    'agendamento':        _h_agendamento,
}


def processar_mensagem(empresa, lead, telefone, mensagem, token=None, media_id=None, media_mime_type=None) -> list:
    """Retorna a lista de textos a enviar ao cliente, em ordem. `token`/
    `media_id`/`media_mime_type` só são usados no estado 'fotos' (RN07) —
    opcionais pra manter chamadas antigas/diretas (testes) funcionando."""
    estado = get_or_create_estado(empresa, lead)

    # Funil já tinha concluído (transferido ou finalizado morno/frio) — uma
    # nova mensagem é um novo atendimento, não a continuação de algo fechado.
    if estado.estado == 'concluido':
        resetar_estado(estado)
        status_comercial.definir_status(estado, 'novo_lead')

    # RN15/RN16: lead marcado 'sem_resposta' (job periódico) que volta a
    # escrever retoma o fluxo de onde parou (se ainda não foi resetado
    # acima) — não é mais "sem resposta".
    if estado.status_comercial == 'sem_resposta':
        status_comercial.definir_status(estado, 'em_qualificacao')

    # Escape hatch pra humano, disponível em qualquer etapa (RN14/RN19).
    if _RE_ATENDENTE.search(mensagem or ''):
        textos = handoff.transferir(empresa, lead, estado, 'pedido_humano', mensagens.HANDOFF_PEDIDO_HUMANO)
        registrar_transcricao(estado, bot=textos, cliente=mensagem)
        return textos

    # Voltar ao menu principal (RN19).
    if _RE_MENU.match(mensagem or ''):
        resetar_estado(estado)
        status_comercial.definir_status(estado, 'novo_lead')
        textos = [mensagens.MENU_PRINCIPAL]
        registrar_transcricao(estado, bot=textos, cliente=mensagem)
        return textos

    # Corrigir a resposta anterior (RN19).
    if _RE_CORRIGIR.search(mensagem or '') and estado.estado_anterior:
        estado.estado, estado.estado_anterior = estado.estado_anterior, None
        db.session.commit()
        textos = [_texto_pergunta(empresa, estado)]
        registrar_transcricao(estado, bot=textos, cliente=mensagem)
        return textos

    handler = _HANDLERS.get(estado.estado, _h_menu_principal)
    if estado.estado == 'fotos':
        textos = handler(empresa, lead, estado, mensagem,
                          media_id=media_id, media_mime_type=media_mime_type, token=token)
    else:
        textos = handler(empresa, lead, estado, mensagem)
    registrar_transcricao(estado, bot=textos, cliente=mensagem)
    return textos
