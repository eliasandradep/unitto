"""Comandos especiais do funil da Renata Rosa (Fase 5d):
- "0" a qualquer momento do fluxo -> volta pro menu principal, sem perder
  pontuação/sinais já coletados (reset "leve").
- "reset" a qualquer momento -> reinicia tudo, inclusive campos pegajosos
  do Lead (email/unidade/serviço) e destrava um handoff em andamento —
  comando de teste, interceptado em meta_webhook/routes.py ANTES do gating
  normal de conversa transferida (ver renata_rosa_bot/orquestrador.py::
  resetar_interacao_teste)."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilLead
from renata_rosa_bot.nlu import NLUError
import meta_client
from meta_webhook.routes import _processar_evento
from tests.conftest import make_empresa, make_integracao_whatsapp


def _empresa_rr(**kwargs):
    defaults = dict(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                     funil_qualificacao_rr_ativo=True)
    defaults.update(kwargs)
    return make_empresa(**defaults)


def _evento(integracao, mensagem, thread_id):
    return {
        'identificador_externo': integracao.identificador_externo,
        'external_thread_id': thread_id,
        'phone': thread_id,
        'nome': 'Cliente Teste',
        'mensagem': mensagem,
        'canal': 'whatsapp',
        'quick_reply_payload': None,
        'ad_id': None,
        'ad_title': None,
        'media_id': None,
        'media_mime_type': None,
    }


def _resultado(topico='OUTRO', **overrides):
    base = {
        'topico': topico, 'quer_agendar': False, 'quer_humano': False, 'tem_reclamacao': False,
        'demonstrou_desinteresse': False, 'servico_mencionado': '', 'resultado_desejado': '',
        'prazo_mencionado': '', 'prazo_ate_15_dias': False, 'perguntou_valores': False,
        'perguntou_disponibilidade': False, 'pergunta_direta': '', 'resposta_ao_cliente': '',
    }
    base.update(overrides)
    return base


def _enviar(integracao, mensagem, thread_id, monkeypatch, nlu_result=None, nlu_erro=False):
    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    patcher = patch('renata_rosa_bot.nlu.classificar',
                     side_effect=NLUError('mock') if nlu_erro else None,
                     return_value=nlu_result)
    with patcher:
        _processar_evento(_evento(integracao, mensagem, thread_id))
    return enviados


def _lead_e_estado(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first() if lead else None
    return lead, estado


def _entrar_topico(integracao, digito_menu, thread_id, monkeypatch):
    _enviar(integracao, digito_menu, thread_id, monkeypatch)  # pergunta a unidade
    return _enviar(integracao, '1', thread_id, monkeypatch)  # escolhe e entra no fluxo


def test_zero_volta_pro_menu_mantendo_pontuacao_ja_coletada(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '1', thread_id, monkeypatch)  # ILUMINAR
    _enviar(integracao, 'já tenho mechas', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.pt_servico_especifico is True
    assert estado.score_total == 15

    enviados = _enviar(integracao, '0', thread_id, monkeypatch)
    assert 'O que você deseja fazer' in enviados[0] or 'Mechas' not in enviados[0]  # é o menu, não o fluxo
    db.session.refresh(estado)
    assert estado.topico_ativo is None
    assert estado.pergunta_idx is None
    assert estado.pt_servico_especifico is True  # pontuação não se perde no "0"
    assert estado.score_total == 15


def test_zero_funciona_durante_a_pergunta_de_unidade(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, '1', thread_id, monkeypatch)  # pergunta a unidade
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.pergunta_idx == -1

    enviados = _enviar(integracao, '0', thread_id, monkeypatch)
    db.session.refresh(estado)
    assert estado.topico_ativo is None
    assert estado.pergunta_idx is None
    assert lead.unit is None  # nunca chegou a escolher


def test_reset_zera_tudo_inclusive_campos_pegajosos_do_lead(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '1', thread_id, monkeypatch)  # ILUMINAR, grava unidade
    _enviar(integracao, 'já tenho mechas', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas'))
    lead, estado = _lead_e_estado(empresa, thread_id)
    lead.email = 'teste@exemplo.com'
    db.session.commit()
    assert lead.unit is not None
    assert estado.score_total == 15

    enviados = _enviar(integracao, 'reset', thread_id, monkeypatch)
    # só o menu principal de sempre — não revela pra um usuário externo que
    # "reset" é um comando especial (ver meta_webhook/routes.py)
    assert len(enviados) == 1
    assert '✨ Quero iluminar' in enviados[0]  # é o menu principal, não o fluxo

    db.session.refresh(lead)
    db.session.refresh(estado)
    assert lead.unit is None
    assert lead.email is None
    assert lead.service is None
    assert estado.topico_ativo is None
    assert estado.pergunta_idx is None
    assert estado.pt_servico_especifico is False
    assert estado.score_total in (0, None)
    assert estado.status_comercial == 'novo_lead'


def test_reset_funciona_mesmo_com_handoff_em_andamento(monkeypatch):
    """O cenário que motivou o pedido: depois de um handoff, o webhook
    normalmente bloqueia qualquer processamento novo por até 1h
    (_handoff_expirado) — "reset" precisa furar esse bloqueio, senão nunca
    seria possível recomeçar um teste logo após transferir pra atendente."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '1', thread_id, monkeypatch)
    _enviar(integracao, 'quero agendar agora mesmo', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', quer_agendar=True))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'  # handoff concluído, updated_at acabou de avançar

    enviados = _enviar(integracao, 'reset', thread_id, monkeypatch)
    assert len(enviados) == 1  # só o menu principal, nada que revele o comando
    db.session.refresh(lead)
    assert lead.contato_etapa is None  # destravado
    db.session.refresh(estado)
    assert estado.estado == 'menu_principal'

    # confirma que o funil volta a responder normalmente depois do reset
    enviados = _enviar(integracao, '1', thread_id, monkeypatch)
    assert any('unidade' in t.lower() for t in enviados)
