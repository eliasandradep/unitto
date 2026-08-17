"""HUMAN_HANDOFF é sempre disponível — mesmo se a opção estiver desativada no
menu configurável do tenant (decisão de produto confirmada: rede de
segurança para o cliente nunca ficar preso no bot)."""
from unittest.mock import patch

from flask import g

from models import Lead
from ai_attendance.orquestrador import processar_mensagem
from ai_attendance.menu import get_or_create_menu_config
from tests.conftest import make_empresa, make_integracao_whatsapp, make_lead


def _resultado(intent):
    return {'intent': intent, 'sub_acao': 'NONE', 'servico_mencionado': '',
            'data_mencionada': '', 'hora_mencionada': '', 'resposta_ao_cliente': ''}


def test_handoff_funciona_mesmo_com_opcao_desativada_no_menu():
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    lead = make_lead(empresa, integracao)
    g.empresa, g.empresa_id = empresa, empresa.id

    cfg = get_or_create_menu_config(empresa)
    for opcao in cfg.opcoes:
        if opcao.intent == 'HUMAN_HANDOFF':
            opcao.ativo = False
    from models import db
    db.session.commit()

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        mock_classificar.return_value = _resultado('HUMAN_HANDOFF')
        textos = processar_mensagem(empresa, lead, lead.external_thread_id,
                                     'quero falar com uma pessoa', 'tok')

    assert any('encaminhar' in t.lower() for t in textos)
    db.session.refresh(lead)
    assert lead.contato_etapa == 'transferido'
