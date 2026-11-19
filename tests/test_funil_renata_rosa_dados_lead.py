"""Fase 5c do funil da Renata Rosa — Lead.email/service/unit/message, e o
fallback determinístico de objetivo/prazo (ver plano em
C:\\Users\\elias\\.claude\\plans\\lovely-kindling-wind.md, seção E3-E5).

Mesmo padrão das demais fases (_processar_evento direto, NLU sempre
mockada). A empresa 'renatarosa' tem 2 unidades reais (Varginha/São José dos
Campos), então todo fluxo passa primeiro pela pergunta de unidade — ver
_entrar_topico()."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilLead
from renata_rosa_bot import fluxos
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


def test_mensagem_original_recebe_resumo_formatado_com_labels(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '1', thread_id, monkeypatch)  # ILUMINAR
    _enviar(integracao, 'já tenho mechas', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas'))
    _enviar(integracao, 'sem química nenhuma', thread_id, monkeypatch, nlu_result=_resultado(topico='ILUMINAR'))
    _enviar(integracao, 'algo bem marcante e iluminado', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR'))  # pergunta de objetivo (fallback determinístico)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.service == 'Mechas'
    assert lead.message == (
        'Unidade: São José dos Campos – SP\n'
        'Serviço de interesse: Mechas\n'
        'Objetivo: algo bem marcante e iluminado'
    )


def test_mensagem_original_usa_label_do_topico_quando_nao_ha_servico_especifico(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '4', thread_id, monkeypatch)  # CORTE, sem servico_mencionado nenhuma vez

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.service == 'Corte'  # label do tópico — ainda não identificou nada mais específico
    assert lead.message == 'Unidade: São José dos Campos – SP\nServiço de interesse: Corte'


def test_objetivo_e_prazo_nunca_ficam_em_branco_mesmo_sem_a_ia_extrair(monkeypatch):
    """Fallback determinístico (E4): a IA aqui NUNCA marca resultado_desejado
    nem prazo_mencionado — só o fato de ser a pergunta certa do roteiro (ver
    fluxos.py::campo_da_pergunta) já grava o texto literal da cliente."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '4', thread_id, monkeypatch)  # CORTE: comprimento / resultado / prazo
    _enviar(integracao, 'na altura dos ombros', thread_id, monkeypatch, nlu_result=_resultado(topico='CORTE'))
    _enviar(integracao, 'quero um corte curto e moderno', thread_id, monkeypatch,
            nlu_result=_resultado(topico='CORTE'))  # pergunta de resultado_desejado
    _enviar(integracao, 'ainda esse mês', thread_id, monkeypatch,
            nlu_result=_resultado(topico='CORTE'))  # pergunta de prazo

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.resultado_desejado_texto == 'quero um corte curto e moderno'
    assert estado.prazo_texto == 'ainda esse mês'
    assert estado.pt_resultado_desejado is True
    assert estado.pt_prazo_informado is True


def test_ia_extraindo_objetivo_tem_prioridade_sobre_fallback(monkeypatch):
    """Quando a IA já extraiu o objetivo nesse mesmo turno (resultado_desejado
    preenchido no resultado da NLU), o fallback por posição da pergunta não
    sobrescreve com o texto cru — fica com a versão já processada da IA."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _entrar_topico(integracao, '4', thread_id, monkeypatch)
    _enviar(integracao, 'na altura dos ombros', thread_id, monkeypatch, nlu_result=_resultado(topico='CORTE'))
    _enviar(integracao, 'queria ficar com um corte moderno e curto', thread_id, monkeypatch,
            nlu_result=_resultado(topico='CORTE', resultado_desejado='corte curto e moderno'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.resultado_desejado_texto == 'corte curto e moderno'  # versão da IA, não o texto cru


def test_email_opcional_grava_no_lead_e_nao_insiste_quando_invalido(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    total = fluxos.total_perguntas('TRATAMENTO')
    _entrar_topico(integracao, '3', thread_id, monkeypatch)
    for _ in range(total):
        _enviar(integracao, 'resposta', thread_id, monkeypatch, nlu_result=_resultado(topico='TRATAMENTO'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.email is None

    # resposta sem e-mail reconhecível -> só avança (sem insistir), sem gravar nada
    enviados = _enviar(integracao, 'prefiro não informar', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='TRATAMENTO'))
    db.session.refresh(lead)
    assert lead.email is None
    assert lead.contato_etapa == 'transferido'  # Tratamento não tem fotos, encaminha direto


def test_historico_completo_da_conversa_fica_registrado(monkeypatch):
    """Resposta ao item 4 do pedido do usuário: o "Histórico da conversa" do
    resumo é o estado.transcricao acumulado — confere que uma conversa longa
    (unidade + perguntas + e-mail + encaminhamento) preserva TODOS os turnos,
    não só o menu principal."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'oi', thread_id, monkeypatch, nlu_result=_resultado(topico='OUTRO'))
    _entrar_topico(integracao, '3', thread_id, monkeypatch)  # TRATAMENTO
    _enviar(integracao, 'tenho muito frizz', thread_id, monkeypatch, nlu_result=_resultado(topico='TRATAMENTO'))
    _enviar(integracao, 'o quanto antes', thread_id, monkeypatch, nlu_result=_resultado(topico='TRATAMENTO'))
    _enviar(integracao, 'fulana@exemplo.com', thread_id, monkeypatch, nlu_result=_resultado(topico='TRATAMENTO'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    transcricao = estado.transcricao
    assert transcricao.count('Cliente: oi') == 1
    assert 'Cliente: 3' in transcricao
    assert 'Cliente: 1' in transcricao  # escolha da unidade
    assert 'Cliente: tenho muito frizz' in transcricao
    assert 'Cliente: o quanto antes' in transcricao
    assert 'Cliente: fulana@exemplo.com' in transcricao
    assert transcricao.count('menu principal') == 0 or 'O que você deseja fazer' not in transcricao
    assert lead.contato_etapa == 'transferido'
