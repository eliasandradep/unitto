"""Uma vez transferido pra atendente humano, o bot nunca mais respondia esse
contato — permanentemente, mesmo semanas depois. Bug real observado em
produção (lead ficou preso em 'transferido' e parou de responder). Agora
reativa automaticamente após HANDOFF_REATIVACAO_HORAS de silêncio total,
sem interromper uma troca de mensagens ainda em andamento com o humano."""
from datetime import datetime, timedelta
from unittest.mock import patch

from models import db, Lead
import meta_client
from meta_webhook.routes import _processar_evento, HANDOFF_REATIVACAO_HORAS
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


def _lead_transferido(empresa, integracao, horas_atras):
    lead = Lead(empresa_id=empresa.id, integracao_id=integracao.id, name='Cliente Teste',
                external_thread_id='5511988887777', phone='5511988887777',
                source='whatsapp_meta', contato_etapa='transferido')
    db.session.add(lead)
    db.session.commit()
    # updated_at tem onupdate automático — força o valor antigo direto via UPDATE,
    # sem passar pelo ORM (senão o commit reescreveria com datetime.utcnow() de novo).
    Lead.query.filter_by(id=lead.id).update(
        {'updated_at': datetime.utcnow() - timedelta(hours=horas_atras)})
    db.session.commit()
    db.session.refresh(lead)
    return lead


def test_nao_reativa_antes_de_1h_de_silencio(monkeypatch):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    lead = _lead_transferido(empresa, integracao, horas_atras=0.5)

    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))

    with patch('meta_webhook.routes.processar_mensagem') as mock_proc:
        _processar_evento(_evento_whatsapp(integracao, 'oi de novo'))
        assert mock_proc.called is False  # ainda dentro da janela — não interrompe

    db.session.refresh(lead)
    assert lead.contato_etapa == 'transferido'  # continua transferido
    assert enviados == []  # nenhuma resposta automática enviada


def test_reativa_apos_1h_de_silencio(monkeypatch):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    horas = HANDOFF_REATIVACAO_HORAS + 0.5
    lead = _lead_transferido(empresa, integracao, horas_atras=horas)

    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))

    with patch('meta_webhook.routes.processar_mensagem', return_value=['resposta da IA']) as mock_proc:
        _processar_evento(_evento_whatsapp(integracao, 'quero marcar um horário nesse mesmo numero'))
        assert mock_proc.called is True

    db.session.refresh(lead)
    assert lead.contato_etapa != 'transferido'  # reativado
    assert enviados == ['resposta da IA']
