"""Empresas com mais de uma unidade: um profissional escalado pra outra
unidade (EscalaProfissionalUnidade) aparecia como opção mesmo lá não podendo
atender, tanto no site quanto no bot — nem eligible_profissionais nem
get_available_slots levavam em conta QUAL unidade o cliente escolheu, só a
unidade padrão do cadastro do profissional. Bug real relatado em produção
(Renata Rosa Beauty Concept, unidades Varginha/MG e São José dos Campos/SP)."""
from datetime import date, time, timedelta
from unittest.mock import patch

from flask import g

from models import db, Unidade, Profissional, Servico, Expediente, ExpedienteDia, EscalaProfissionalUnidade
from public.availability import eligible_profissionais, get_available_slots
from ai_attendance.orquestrador import processar_mensagem
from tests.conftest import make_empresa, make_integracao_whatsapp, make_lead


def _resultado(intent, **kwargs):
    base = {'intent': intent, 'sub_acao': 'NONE', 'servico_mencionado': '', 'data_mencionada': '',
            'hora_mencionada': '', 'resposta_ao_cliente': ''}
    base.update(kwargs)
    return base


def _setup_duas_unidades(empresa):
    varginha = Unidade(nome='Studio Varginha', cidade='Varginha', estado='MG', ativo=True, empresa_id=empresa.id)
    sjc = Unidade(nome='Studio SJC', cidade='São José dos Campos', estado='SP', ativo=True, empresa_id=empresa.id)
    db.session.add_all([varginha, sjc])
    db.session.flush()

    expediente = Expediente(nome='Padrão', empresa_id=empresa.id)
    db.session.add(expediente)
    db.session.flush()
    for dow in range(7):
        db.session.add(ExpedienteDia(expediente_id=expediente.id, dia_semana=dow,
                                      hora_inicio=time(8, 0), hora_fim=time(18, 0)))
    db.session.flush()

    # Ana: casa em Varginha, sem escala — sempre efetivamente em Varginha.
    ana = Profissional(nome='Ana Varginha', empresa_id=empresa.id, ativo=True, agendamento_online=True,
                        expediente_id=expediente.id, unidade_id=varginha.id)
    # Renata: casa cadastrada em Varginha, mas com escala vigente pra SJC —
    # exatamente o cenário relatado (aparecia disponível em Varginha, mas
    # está fisicamente em SJC nesse período).
    renata = Profissional(nome='Renata Rosa', empresa_id=empresa.id, ativo=True, agendamento_online=True,
                           expediente_id=expediente.id, unidade_id=varginha.id)
    db.session.add_all([ana, renata])
    db.session.flush()

    db.session.add(EscalaProfissionalUnidade(
        profissional_id=renata.id, unidade_id=sjc.id,
        data_inicio=date.today() - timedelta(days=5), data_fim=date.today() + timedelta(days=25)))

    servico = Servico(nome='Mechas', empresa_id=empresa.id, ativo=True, agendamento_online=True,
                       exibir_preco_online=True, preco=680, duracao_horas=4, duracao_minutos=0)
    servico.profissionais_adicionais.extend([ana, renata])
    db.session.add(servico)
    db.session.commit()

    return varginha, sjc, ana, renata, servico


def test_eligible_profissionais_exclui_quem_esta_escalado_pra_outra_unidade():
    empresa = make_empresa()
    varginha, sjc, ana, renata, servico = _setup_duas_unidades(empresa)

    em_varginha = eligible_profissionais(servico, unidade_id=varginha.id)
    assert ana in em_varginha
    assert renata not in em_varginha  # escalada pra SJC agora — não deve aparecer em Varginha

    em_sjc = eligible_profissionais(servico, unidade_id=sjc.id)
    assert renata in em_sjc
    assert ana not in em_sjc

    # Sem unidade_id (compatibilidade com quem ainda não passa esse filtro): comportamento antigo, mostra todo mundo.
    assert set(eligible_profissionais(servico)) == {ana, renata}


def test_get_available_slots_valida_escala_contra_a_unidade_escolhida():
    empresa = make_empresa()
    varginha, sjc, ana, renata, servico = _setup_duas_unidades(empresa)

    hoje = date.today()
    # Escolhendo a unidade onde ela REALMENTE está (SJC) — tem horário normalmente.
    slots_sjc = get_available_slots(renata.id, servico, hoje, unidade_id=sjc.id)
    assert len(slots_sjc) > 0

    # Escolhendo a unidade do cadastro dela (Varginha), mas a escala diz que ela está em SJC agora — sem vaga.
    slots_varginha = get_available_slots(renata.id, servico, hoje, unidade_id=varginha.id)
    assert slots_varginha == []


def test_bot_pergunta_unidade_quando_ha_mais_de_uma_e_filtra_profissional_certo():
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)
    varginha, sjc, ana, renata, servico = _setup_duas_unidades(empresa)
    lead = make_lead(empresa, integracao)
    telefone = lead.external_thread_id
    g.empresa, g.empresa_id = empresa, empresa.id

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        mock_classificar.return_value = _resultado('BOOKING', servico_mencionado='Mechas')
        textos = processar_mensagem(empresa, lead, telefone, 'quero agendar mechas', 'tok')
        # pergunta a unidade antes de mostrar profissional
        assert any('unidade' in t.lower() for t in textos)
        assert any('sjc' in t.lower() or 'varginha' in t.lower() for t in textos)

        # unidades ordenadas por nome: "Studio SJC" < "Studio Varginha" -> índice 1 é SJC
        textos = processar_mensagem(empresa, lead, telefone, '1', 'tok')
        # em SJC só a Renata está disponível — pula direto pra pergunta de data
        # (mesmo padrão de "pula pergunta" quando só há 1 profissional elegível)
        assert any('dia' in t.lower() for t in textos)
        assert not any('ana' in t.lower() for t in textos)


def test_bot_pula_pergunta_de_unidade_quando_so_ha_uma():
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)
    integracao = make_integracao_whatsapp(empresa)

    unidade = Unidade(nome='Única', ativo=True, empresa_id=empresa.id)
    expediente = Expediente(nome='Padrão', empresa_id=empresa.id)
    db.session.add_all([unidade, expediente])
    db.session.flush()
    for dow in range(7):
        db.session.add(ExpedienteDia(expediente_id=expediente.id, dia_semana=dow,
                                      hora_inicio=time(8, 0), hora_fim=time(18, 0)))
    prof = Profissional(nome='Única Prof', empresa_id=empresa.id, ativo=True, agendamento_online=True,
                         expediente_id=expediente.id, unidade_id=unidade.id)
    db.session.add(prof)
    db.session.flush()
    servico = Servico(nome='Corte', empresa_id=empresa.id, ativo=True, agendamento_online=True,
                       duracao_horas=1, duracao_minutos=0)
    servico.profissionais_adicionais.append(prof)
    db.session.add(servico)
    db.session.commit()

    lead = make_lead(empresa, integracao)
    telefone = lead.external_thread_id
    g.empresa, g.empresa_id = empresa, empresa.id

    with patch('ai_attendance.orquestrador.classificar') as mock_classificar:
        mock_classificar.return_value = _resultado('BOOKING', servico_mencionado='Corte')
        textos = processar_mensagem(empresa, lead, telefone, 'quero um corte', 'tok')
        # nunca pergunta unidade (só existe uma) nem profissional (só existe um) — vai direto pra data
        assert any('dia' in t.lower() for t in textos)
        assert not any('unidade' in t.lower() for t in textos)


def test_site_pede_unidade_antes_de_listar_profissional(client):
    empresa = make_empresa()
    varginha, sjc, ana, renata, servico = _setup_duas_unidades(empresa)

    resp = client.get(f'/{empresa.slug}/agendar/{servico.id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'qual unidade' in html.lower()
    # não deve mostrar os cards de profissional antes de escolher a unidade
    # (a string 'profissional_id' sempre aparece no <script>, mesmo sem o formulário)
    assert 'pub-prof-card' not in html


def test_site_filtra_profissional_pela_unidade_escolhida(client):
    empresa = make_empresa()
    varginha, sjc, ana, renata, servico = _setup_duas_unidades(empresa)

    resp = client.get(f'/{empresa.slug}/agendar/{servico.id}?unidade_id={sjc.id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Renata Rosa' in html
    assert 'Ana Varginha' not in html  # escalada pra outra unidade nesse período — some da lista

    resp = client.get(f'/{empresa.slug}/agendar/{servico.id}?unidade_id={varginha.id}')
    html = resp.get_data(as_text=True)
    assert 'Ana Varginha' in html
    assert 'Renata Rosa' not in html
