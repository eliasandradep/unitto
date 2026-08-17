"""Roteamento do webhook: tenant sem atendimento por IA mantém o comportamento
regex de sempre e nunca chama a Anthropic; tenant elegível é roteado pro
orquestrador. Cobre também o fallback quando a IA falha."""
from unittest.mock import patch

from models import Lead, AtendimentoIAEvento
from meta_webhook.routes import _processar_evento
import meta_client
from tests.conftest import make_empresa, make_integracao_whatsapp


def _evento_whatsapp(integracao, mensagem, thread_id='5511988887777'):
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
    }


def test_tenant_sem_ia_mantem_fluxo_regex_e_nao_chama_anthropic(monkeypatch):
    empresa = make_empresa(plano='free', atendimento_ia_ativo=False)
    integracao = make_integracao_whatsapp(empresa)

    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        _processar_evento(_evento_whatsapp(integracao, 'oi'))
        assert mock_classificar.called is False

    lead = Lead.query.filter_by(empresa_id=empresa.id).first()
    assert lead is not None
    assert lead.contato_etapa == 'wa_menu'
    assert 'Bem-vindo' in enviados[0]  # saudação fixa de sempre, sem IA


def test_tenant_com_ia_roteia_pro_orquestrador(monkeypatch):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)

    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))

    with patch('meta_webhook.routes.processar_mensagem', return_value=['resposta da IA']) as mock_proc:
        _processar_evento(_evento_whatsapp(integracao, 'quero marcar um horário'))
        assert mock_proc.called is True

    assert enviados == ['resposta da IA']


def test_falha_na_ia_cai_pro_fallback_e_loga_evento(monkeypatch):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)

    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))

    with patch('meta_webhook.routes.processar_mensagem', side_effect=RuntimeError('boom')):
        _processar_evento(_evento_whatsapp(integracao, 'oi'))

    # nunca deixa o cliente sem resposta — cai na saudação fixa (primeira mensagem)
    assert len(enviados) == 1
    evento = AtendimentoIAEvento.query.filter_by(empresa_id=empresa.id, tipo='AI_ERROR').first()
    assert evento is not None
