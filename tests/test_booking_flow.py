"""Fluxo completo de BOOKING via IA — serviço -> data -> horário -> confirmação
-> Agendamento criado reusando o mesmo motor de disponibilidade do site
(public/availability.py). Anthropic mockada; controla o teste passo a passo."""
from unittest.mock import patch

from flask import g

from models import db, Agendamento, AtendimentoIAConversa, AtendimentoIAEvento, Servico
from ai_attendance.orquestrador import processar_mensagem
from tests.conftest import make_empresa, make_integracao_whatsapp, make_booking_setup, make_lead, proxima_segunda


def _resultado(intent, **kwargs):
    base = {'intent': intent, 'sub_acao': 'NONE', 'servico_mencionado': '', 'data_mencionada': '',
            'hora_mencionada': '', 'resposta_ao_cliente': ''}
    base.update(kwargs)
    return base


def test_fluxo_completo_de_agendamento_via_ia():
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    servico, profissional = make_booking_setup(empresa, nome_servico='Corte', preco=80, duracao_min=60)
    lead = make_lead(empresa, integracao)
    telefone = lead.external_thread_id

    g.empresa, g.empresa_id = empresa, empresa.id
    data_alvo = proxima_segunda()

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        mock_classificar.return_value = _resultado('BOOKING', servico_mencionado='Corte')
        textos = processar_mensagem(empresa, lead, telefone, 'quero agendar um corte', 'tok')
        assert any('dia' in t.lower() for t in textos)

        mock_classificar.return_value = _resultado('BOOKING', data_mencionada=data_alvo.isoformat())
        textos = processar_mensagem(empresa, lead, telefone, data_alvo.strftime('%d/%m'), 'tok')
        assert any('horários' in t.lower() for t in textos)

        textos = processar_mensagem(empresa, lead, telefone, '1', 'tok')
        assert any('confirmando' in t.lower() for t in textos)

        textos = processar_mensagem(empresa, lead, telefone, 'sim', 'tok')
        assert any('confirmado' in t.lower() for t in textos)

    agendamento = Agendamento.query.filter_by(empresa_id=empresa.id).first()
    assert agendamento is not None
    assert agendamento.status == 'agendado'
    assert agendamento.data == data_alvo
    assert agendamento.servico_id == servico.id
    assert agendamento.profissional_id == profissional.id

    evento = AtendimentoIAEvento.query.filter_by(empresa_id=empresa.id, tipo='AI_BOOKING_COMPLETED').first()
    assert evento is not None
    assert evento.agendamento_id == agendamento.id


def test_selecionar_agendar_horario_pelo_menu_nao_pula_pergunta_de_servico():
    """Bug real observado em produção: o "1" usado pra escolher 'Agendar
    horário' no menu principal era reaproveitado como resposta a 'qual
    serviço' (índice 1 da lista) — agendava o primeiro serviço do catálogo
    sem o cliente nunca ter escolhido. Esse caminho (mensagem = dígito puro)
    é 100% determinístico via _intent_por_numero, sem chamar a Anthropic —
    por isso não mocka classificar aqui, pra reproduzir o caminho real."""
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    servico1, prof1 = make_booking_setup(empresa, nome_servico='Botox Capilar Cabelo Curto')
    servico2 = Servico(nome='Mechas', empresa_id=empresa.id, ativo=True, agendamento_online=True,
                        duracao_horas=1, duracao_minutos=0)
    servico2.profissionais_adicionais.append(prof1)
    db.session.add(servico2)
    db.session.commit()
    lead = make_lead(empresa, integracao)
    telefone = lead.external_thread_id

    g.empresa, g.empresa_id = empresa, empresa.id

    textos = processar_mensagem(empresa, lead, telefone, '1', 'tok')

    # pergunta qual serviço (o nome aparece normalmente NA LISTA de opções —
    # o que importa é que nada foi selecionado sozinho, checado abaixo)
    assert any('qual você quer agendar' in t.lower() for t in textos)

    conversa = AtendimentoIAConversa.query.filter_by(empresa_id=empresa.id).first()
    assert conversa.get_contexto().get('servico_id') is None
    assert Agendamento.query.filter_by(empresa_id=empresa.id).count() == 0


def test_booking_nunca_inventa_servico_fora_do_catalogo():
    """Se a IA extrai um nome de serviço que não bate com o catálogo real, o
    fluxo pede de novo em vez de agendar algo inexistente."""
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    make_booking_setup(empresa, nome_servico='Corte')
    lead = make_lead(empresa, integracao)
    telefone = lead.external_thread_id

    g.empresa, g.empresa_id = empresa, empresa.id

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        mock_classificar.return_value = _resultado('BOOKING', servico_mencionado='Massagem Inexistente')
        textos = processar_mensagem(empresa, lead, telefone, 'quero uma massagem', 'tok')

    assert any('Corte' in t for t in textos)  # lista o catálogo real
    assert Agendamento.query.filter_by(empresa_id=empresa.id).count() == 0
