"""Isolamento multi-tenant do fluxo 'Meu agendamento' — o ponto de maior risco
de seguranca da feature. Telefone de WhatsApp não é único globalmente; o
filtro por empresa_id (nunca vindo de input do cliente) é o que garante que
um tenant nunca vê/mexe no agendamento de outro."""
from datetime import time
from unittest.mock import patch

from flask import g

from models import db, Agendamento
from ai_attendance.orquestrador import processar_mensagem
from ai_attendance.appointment_mgmt import _agendamentos_futuros, _pertence_ao_cliente
from tests.conftest import make_empresa, make_integracao_whatsapp, make_booking_setup, make_lead, proxima_segunda

MESMO_TELEFONE = '5511977776666'


def _resultado(intent, sub_acao='NONE'):
    return {'intent': intent, 'sub_acao': sub_acao, 'servico_mencionado': '',
            'data_mencionada': '', 'hora_mencionada': '', 'resposta_ao_cliente': ''}


def _criar_agendamento(empresa, servico, profissional, telefone, data_val):
    ag = Agendamento(nome_cliente='Cliente', telefone=telefone, profissional_id=profissional.id,
                      servico_id=servico.id, servicos_lista=[servico], data=data_val,
                      hora_inicio=time(9, 0), duracao_min=60, status='agendado', empresa_id=empresa.id)
    db.session.add(ag)
    db.session.commit()
    return ag


def test_agendamentos_futuros_nao_vazam_entre_tenants_com_mesmo_telefone():
    empresa_a = make_empresa(plano='pro', atendimento_ia_ativo=True, nome='Empresa A')
    empresa_b = make_empresa(plano='pro', atendimento_ia_ativo=True, nome='Empresa B')
    servico_a, prof_a = make_booking_setup(empresa_a, nome_servico='Corte A')
    servico_b, prof_b = make_booking_setup(empresa_b, nome_servico='Corte B')
    data_alvo = proxima_segunda()

    ag_a = _criar_agendamento(empresa_a, servico_a, prof_a, MESMO_TELEFONE, data_alvo)
    ag_b = _criar_agendamento(empresa_b, servico_b, prof_b, MESMO_TELEFONE, data_alvo)

    encontrados_a = _agendamentos_futuros(empresa_a, MESMO_TELEFONE)
    encontrados_b = _agendamentos_futuros(empresa_b, MESMO_TELEFONE)

    assert [a.id for a in encontrados_a] == [ag_a.id]
    assert [a.id for a in encontrados_b] == [ag_b.id]
    assert ag_b.id not in [a.id for a in encontrados_a]


def test_pertence_ao_cliente_rejeita_agendamento_de_outro_tenant():
    empresa_a = make_empresa(plano='pro', atendimento_ia_ativo=True)
    empresa_b = make_empresa(plano='pro', atendimento_ia_ativo=True)
    servico_b, prof_b = make_booking_setup(empresa_b)
    ag_b = _criar_agendamento(empresa_b, servico_b, prof_b, MESMO_TELEFONE, proxima_segunda())

    # mesmo telefone batendo, mas empresa errada — deve ser recusado
    assert _pertence_ao_cliente(ag_b, empresa_a, MESMO_TELEFONE) is False
    assert _pertence_ao_cliente(ag_b, empresa_b, MESMO_TELEFONE) is True


def test_cancelamento_via_ia_nao_alcanca_agendamento_de_outro_tenant():
    empresa_a = make_empresa(plano='pro', atendimento_ia_ativo=True)
    empresa_b = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao_a = make_integracao_whatsapp(empresa_a)
    servico_a, prof_a = make_booking_setup(empresa_a)
    servico_b, prof_b = make_booking_setup(empresa_b)
    data_alvo = proxima_segunda()

    ag_a = _criar_agendamento(empresa_a, servico_a, prof_a, MESMO_TELEFONE, data_alvo)
    ag_b = _criar_agendamento(empresa_b, servico_b, prof_b, MESMO_TELEFONE, data_alvo)

    lead_a = make_lead(empresa_a, integracao_a, external_thread_id=MESMO_TELEFONE)
    g.empresa, g.empresa_id = empresa_a, empresa_a.id

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        mock_classificar.return_value = _resultado('APPOINTMENT_MANAGEMENT', sub_acao='CANCEL')
        processar_mensagem(empresa_a, lead_a, MESMO_TELEFONE, 'quero cancelar meu agendamento', 'tok')
        processar_mensagem(empresa_a, lead_a, MESMO_TELEFONE, 'sim', 'tok')  # confirma que quer cancelar
        processar_mensagem(empresa_a, lead_a, MESMO_TELEFONE, 'sim', 'tok')  # confirma o cancelamento em si

    db.session.refresh(ag_a)
    db.session.refresh(ag_b)
    assert ag_a.status == 'cancelado'  # o cancelamento real do tenant A aconteceu...
    assert ag_b.status == 'agendado'   # ...mas nunca alcançou o agendamento do tenant B
