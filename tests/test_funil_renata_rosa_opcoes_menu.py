"""Fase 5g do funil da Renata Rosa — reconhecer a opção do menu principal
não só pelo número, mas também pela frase completa (atalho determinístico,
sem chamar a IA) ou por uma palavra única/variação (via NLU real, reforçada
no prompt, e via fallback por regex quando a IA falha). Mesmo padrão das
demais fases (_processar_evento direto, NLU sempre mockada)."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilLead
from renata_rosa_bot.nlu import NLUError, classificar_fallback_regex
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


def test_frase_completa_da_opcao_e_atalho_sem_chamar_nlu(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    with patch('renata_rosa_bot.nlu.classificar') as mock_nlu:
        _enviar(integracao, 'Quero mudar meu corte', thread_id, monkeypatch)
        assert mock_nlu.called is False

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.topico_ativo == 'CORTE'


def test_frase_completa_com_emoji_tambem_e_atalho(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    with patch('renata_rosa_bot.nlu.classificar') as mock_nlu:
        _enviar(integracao, '💬 Quero falar com uma especialista', thread_id, monkeypatch)
        assert mock_nlu.called is False

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'  # HUMANO transfere direto


def test_palavra_unica_passa_pela_nlu_normal(monkeypatch):
    """Uma palavra só (não é a frase completa de nenhuma opção) não vira
    atalho determinístico — vai pra NLU normal, que já é instruída a
    reconhecer isso (ver nlu.py::montar_system_prompt)."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'corte', thread_id, monkeypatch, nlu_result=_resultado(topico='CORTE'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.topico_ativo == 'CORTE'


def test_fallback_regex_reconhece_palavra_unica_iluminar():
    dados = classificar_fallback_regex('iluminar')
    assert dados['topico'] == 'ILUMINAR'


def test_fallback_regex_reconhece_palavra_unica_cor():
    dados = classificar_fallback_regex('cor')
    assert dados['topico'] == 'COR'


def test_fallback_regex_reconhece_palavra_unica_salao():
    dados = classificar_fallback_regex('salão')
    assert dados['topico'] == 'SALAO'


def test_fallback_regex_reconhece_palavra_unica_corte():
    dados = classificar_fallback_regex('corte')
    assert dados['topico'] == 'CORTE'


def test_fallback_regex_reconhece_palavra_unica_tratamento():
    dados = classificar_fallback_regex('tratamento')
    assert dados['topico'] == 'TRATAMENTO'
