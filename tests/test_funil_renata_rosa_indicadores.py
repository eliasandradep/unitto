"""Fase 4 do funil da Renata Rosa — RN18 (indicadores comerciais).
Testes de agregação usam RenataRosaFunilLead/RenataRosaFunilStatusHistorico
fabricados direto (calcular_indicadores só lê o banco); o vínculo manual de
agendamento (RN18 #8/9/10) é testado via rota admin de verdade."""
import uuid
from datetime import date, datetime, time, timedelta

from models import (db, Lead, RenataRosaFunilLead, RenataRosaFunilStatusHistorico,
                     Cliente, Profissional, Servico, Agendamento, Comanda, PagamentoComanda, User)
from renata_rosa_bot.indicadores import calcular_indicadores
from tests.conftest import make_empresa


def _empresa_rr(**kwargs):
    defaults = dict(slug='renatarosa', plano='pro', funil_qualificacao_rr_ativo=True)
    defaults.update(kwargs)
    return make_empresa(**defaults)


def _lead_simples(empresa, source='whatsapp_meta', nome='Cliente', phone=None):
    phone = phone or uuid.uuid4().hex[:13]
    lead = Lead(empresa_id=empresa.id, name=nome, phone=phone,
                external_thread_id=phone, source=source)
    db.session.add(lead)
    db.session.commit()
    return lead


def _funil(empresa, lead, **kwargs):
    estado = RenataRosaFunilLead(lead_id=lead.id, empresa_id=empresa.id, **kwargs)
    db.session.add(estado)
    db.session.commit()
    return estado


def _historico(estado, status_anterior, status_novo, quando):
    h = RenataRosaFunilStatusHistorico(funil_lead_id=estado.id, status_anterior=status_anterior,
                                        status_novo=status_novo)
    db.session.add(h)
    db.session.flush()
    RenataRosaFunilStatusHistorico.query.filter_by(id=h.id).update({'criado_em': quando})
    db.session.commit()


def test_contagens_basicas_por_origem_servico_e_classificacao():
    empresa = make_empresa()
    l1 = _lead_simples(empresa, source='whatsapp_meta')
    _funil(empresa, l1, servico_opcao_label='Loiro com mechas', classificacao='quente')
    l2 = _lead_simples(empresa, source='whatsapp_meta')
    _funil(empresa, l2, servico_opcao_label='Morena iluminada', classificacao='morno')
    l3 = _lead_simples(empresa, source='instagram')
    _funil(empresa, l3, servico_opcao_label='Loiro com mechas', classificacao=None)  # não concluiu

    ind = calcular_indicadores(empresa)
    assert ind['total_leads'] == 3
    assert ind['leads_por_servico'] == {'Loiro com mechas': 2, 'Morena iluminada': 1}
    assert ind['leads_por_classificacao'] == {'quente': 1, 'morno': 1}
    assert ind['taxa_conclusao_questionario'] == round(100 * 2 / 3, 1)


def test_taxa_transferencia_e_conversao_em_agendamento_via_historico():
    empresa = make_empresa()
    agora = datetime.utcnow()

    l1 = _lead_simples(empresa)
    e1 = _funil(empresa, l1, classificacao='quente', status_comercial='aguardando_atendimento_humano')
    _historico(e1, 'em_qualificacao', 'aguardando_atendimento_humano', agora)

    l2 = _lead_simples(empresa)
    e2 = _funil(empresa, l2, classificacao='morno', status_comercial='agendamento_confirmado')
    _historico(e2, 'em_qualificacao', 'aguardando_atendimento_humano', agora)
    _historico(e2, 'aguardando_atendimento_humano', 'agendamento_confirmado', agora)

    l3 = _lead_simples(empresa)
    _funil(empresa, l3, classificacao='frio', status_comercial='concluido')  # nunca transferido

    ind = calcular_indicadores(empresa)
    assert ind['taxa_transferencia_humana'] == round(100 * 2 / 3, 1)  # l1 e l2 passaram por aguardando_humano
    assert ind['taxa_conversao_agendamento'] == round(100 * 1 / 3, 1)  # só l2 chegou a agendamento_confirmado


def test_tempo_medio_de_resposta_proxy():
    empresa = make_empresa()
    agora = datetime.utcnow()

    l1 = _lead_simples(empresa)
    e1 = _funil(empresa, l1)
    _historico(e1, 'em_qualificacao', 'aguardando_atendimento_humano', agora)
    _historico(e1, 'aguardando_atendimento_humano', 'em_atendimento_humano', agora + timedelta(minutes=30))

    l2 = _lead_simples(empresa)
    e2 = _funil(empresa, l2)
    _historico(e2, 'em_qualificacao', 'aguardando_atendimento_humano', agora)
    _historico(e2, 'aguardando_atendimento_humano', 'perdido', agora + timedelta(minutes=90))

    l3 = _lead_simples(empresa)  # nunca foi transferido -> não entra na média
    _funil(empresa, l3)

    ind = calcular_indicadores(empresa)
    assert ind['tempo_medio_resposta_minutos'] == 60.0  # média de 30 e 90


def test_sem_nenhum_lead_nao_quebra_e_tempo_e_none():
    empresa = make_empresa()
    ind = calcular_indicadores(empresa)
    assert ind['total_leads'] == 0
    assert ind['tempo_medio_resposta_minutos'] is None
    assert ind['taxa_conclusao_questionario'] == 0.0


def _criar_agendamento_e_comanda(empresa, cliente, status_agendamento='concluido',
                                  status_comanda='fechada', valor_pago=250):
    expediente = None
    profissional = Profissional(nome='Profissional Teste', empresa_id=empresa.id, ativo=True)
    db.session.add(profissional)
    db.session.flush()
    servico = Servico(nome='Retoque de Mechas', empresa_id=empresa.id, ativo=True, preco=250)
    db.session.add(servico)
    db.session.flush()

    ag = Agendamento(nome_cliente=cliente.nome, telefone=cliente.telefone, cliente_id=cliente.id,
                      profissional_id=profissional.id, servico_id=servico.id,
                      data=date.today(), hora_inicio=time(10, 0), duracao_min=60,
                      status=status_agendamento, empresa_id=empresa.id)
    db.session.add(ag)
    db.session.commit()

    codigo = int(uuid.uuid4().int % 1_000_000)
    comanda = Comanda(codigo=codigo, data=date.today(), cliente_id=cliente.id, agendamento_id=ag.id,
                       status=status_comanda, empresa_id=empresa.id)
    db.session.add(comanda)
    db.session.commit()
    if valor_pago:
        db.session.add(PagamentoComanda(comanda_id=comanda.id, forma_pagamento='dinheiro',
                                         valor=valor_pago, data_pagamento=date.today()))
        db.session.commit()
    return ag, comanda


def test_comparecimento_contratacao_e_receita_com_agendamento_vinculado():
    empresa = make_empresa()
    cliente = Cliente(nome='Cliente Vinculado', telefone='5511999990001', empresa_id=empresa.id)
    db.session.add(cliente)
    db.session.commit()

    l1 = _lead_simples(empresa, source='whatsapp_meta')
    ag1, _ = _criar_agendamento_e_comanda(empresa, cliente, status_agendamento='concluido')
    e1 = _funil(empresa, l1, servico_opcao_label='Retoque de Mechas',
                agendamento_vinculado_id=ag1.id)

    cliente2 = Cliente(nome='Cliente Faltou', telefone='5511999990002', empresa_id=empresa.id)
    db.session.add(cliente2)
    db.session.commit()
    l2 = _lead_simples(empresa, source='instagram')
    ag2, _ = _criar_agendamento_e_comanda(empresa, cliente2, status_agendamento='faltou',
                                           status_comanda='aberta', valor_pago=None)
    e2 = _funil(empresa, l2, servico_opcao_label='Retoque de Mechas',
                agendamento_vinculado_id=ag2.id)

    l3 = _lead_simples(empresa)  # sem vínculo nenhum
    _funil(empresa, l3)

    ind = calcular_indicadores(empresa)
    assert ind['taxa_comparecimento'] == 50.0  # 1 concluído, 1 faltou -> 1/(1+1)
    assert ind['taxa_contratacao_efetiva'] == round(100 * 1 / 3, 1)
    assert ind['receita_total'] == 250.0
    assert ind['receita_por_origem'] == {'WhatsApp (auto)': 250.0}
    assert ind['receita_por_servico'] == {'Retoque de Mechas': 250.0}


def test_vincular_agendamento_via_admin_com_sucesso_e_com_rejeicao(client):
    empresa = _empresa_rr()
    cliente = Cliente(nome='Cliente Teste', telefone='5511999990003', empresa_id=empresa.id)
    db.session.add(cliente)
    db.session.commit()
    ag, _ = _criar_agendamento_e_comanda(empresa, cliente)

    lead = _lead_simples(empresa, phone='5511999990003')
    estado = _funil(empresa, lead)

    outra_empresa = make_empresa()
    outro_cliente = Cliente(nome='Outro', telefone='5511999990004', empresa_id=outra_empresa.id)
    db.session.add(outro_cliente)
    db.session.commit()
    ag_de_outro_tenant, _ = _criar_agendamento_e_comanda(outra_empresa, outro_cliente)

    username = f'admin{uuid.uuid4().hex[:10]}'
    user = User(name='Admin', username=username, email=f'{username}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)

    # Rejeita agendamento de outro tenant.
    client.post(f'/admin/leads/{lead.id}', data={
        'action': 'vincular_agendamento', 'agendamento_id': str(ag_de_outro_tenant.id),
    }, follow_redirects=True)
    db.session.refresh(estado)
    assert estado.agendamento_vinculado_id is None

    # Aceita o agendamento certo (mesmo tenant, mesmo cliente do telefone do lead).
    client.post(f'/admin/leads/{lead.id}', data={
        'action': 'vincular_agendamento', 'agendamento_id': str(ag.id),
    }, follow_redirects=True)
    db.session.refresh(estado)
    assert estado.agendamento_vinculado_id == ag.id

    client.post(f'/admin/leads/{lead.id}', data={'action': 'desvincular_agendamento'},
                follow_redirects=True)
    db.session.refresh(estado)
    assert estado.agendamento_vinculado_id is None


def test_motivo_nao_conversao_salvo_via_admin_aparece_nos_indicadores(client):
    empresa = _empresa_rr()
    nome_unico = f'Lead Sem Interesse {uuid.uuid4().hex[:8]}'
    lead = _lead_simples(empresa, nome=nome_unico)
    estado = _funil(empresa, lead)

    username = f'admin{uuid.uuid4().hex[:10]}'
    user = User(name='Admin', username=username, email=f'{username}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)

    client.post(f'/admin/leads/{lead.id}', data={
        'action': 'update_status_comercial', 'status_comercial': 'perdido',
        'motivo': 'Achou o preço alto',
    }, follow_redirects=True)

    ind = calcular_indicadores(empresa)
    entradas = [m for m in ind['motivos_nao_conversao'] if m['nome'] == nome_unico]
    assert len(entradas) == 1
    assert entradas[0]['motivo'] == 'Achou o preço alto'


def test_isolamento_outro_tenant_nunca_ve_a_secao_de_indicadores(client):
    empresa_rr = _empresa_rr()
    outra_empresa = make_empresa()

    username = f'admin{uuid.uuid4().hex[:10]}'
    user = User(name='Admin', username=username, email=f'{username}@teste.com',
                empresa_id=outra_empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()
    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)

    resp = client.get('/admin/dashboard')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Indicadores comerciais' not in body
