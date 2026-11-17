"""Funil de qualificação de leads bespoke da Renata Rosa (renata_rosa_bot/) —
isolado do motor genérico ai_attendance/. Cobre: isolamento (nenhum outro
tenant aciona o módulo novo, mesmo com o flag ligado por engano), ativação
(troca o motor genérico pelo bespoke pra esse tenant), os três caminhos de
classificação (quente/morno/frio), as regras de transferência forçada por
RN08, "já sou cliente", escape hatch de atendente, 2 respostas não
reconhecidas, reset por "menu", o teto de pontuação do fluxo simplificado, e
que RN05 nunca inventa valor.

Usa _processar_evento diretamente (mesmo padrão de test_handoff_reativacao.py)
— bypassa a camada HTTP/assinatura do webhook, que já é testada em
test_webhook_routing.py."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilLead, Servico, User
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
    }


def _enviar(integracao, mensagem, thread_id, monkeypatch):
    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    _processar_evento(_evento(integracao, mensagem, thread_id))
    return enviados


def _lead_e_estado(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first() if lead else None
    return lead, estado


def test_isolamento_outro_tenant_nunca_aciona_o_funil_bespoke(monkeypatch):
    """Mesmo com o flag ligado por engano, sem o slug exato 'renatarosa' o
    motor genérico continua rodando normalmente — prova o gate duplo (D1)."""
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True,
                            funil_qualificacao_rr_ativo=True)  # slug != 'renatarosa'
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    with patch('meta_webhook.routes.processar_mensagem', return_value=['oi do motor genérico']) as mock_generico:
        monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp', lambda *a, **k: None)
        _processar_evento(_evento(integracao, 'Olá', thread_id))
        assert mock_generico.called is True

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado is None  # nenhuma linha de estado do funil bespoke foi criada


def test_ativacao_troca_motor_generico_pelo_bespoke(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    with patch('meta_webhook.routes.processar_mensagem') as mock_generico:
        enviados = _enviar(integracao, 'Olá', thread_id, monkeypatch)
        assert mock_generico.called is False  # motor genérico nunca é chamado pra esse tenant

    assert len(enviados) == 1
    assert 'Renata Rosa Beauty Concept' in enviados[0]
    assert '1. ✨ Mechas' in enviados[0]

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado is not None
    assert estado.estado == 'menu_principal'


def test_caminho_quente_transfere_e_grava_resumo(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)                # menu
    _enviar(integracao, '1', thread_id, monkeypatch)                  # mechas/coloração
    _enviar(integracao, '1', thread_id, monkeypatch)                  # loiro com mechas (clareza=10)
    _enviar(integracao, '1', thread_id, monkeypatch)                  # nesta semana (25)
    _enviar(integracao, '2', thread_id, monkeypatch)                  # já tenho mechas (histórico, sem score)
    _enviar(integracao, '1', thread_id, monkeypatch)                  # dentro do orçamento (25)
    _enviar(integracao, '1', thread_id, monkeypatch)                  # sim, avaliação (10)
    enviados = _enviar(integracao, '1', thread_id, monkeypatch)       # sim, quer agendar (30) -> 100 = QUENTE

    assert enviados == ['Perfeito! 💕 Já tenho as informações necessárias para te ajudar com sua transformação!\n\n'
                         'Vou encaminhar seu atendimento para nossa equipe, que vai verificar os '
                         'melhores horários e te ajudar com os próximos passos. ✨']

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'
    assert lead.status == 'qualificado'
    assert estado.score_total == 100
    assert estado.classificacao == 'quente'
    assert estado.estado == 'concluido'
    assert 'QUENTE' in lead.notes
    assert 'score 100/100' in lead.notes


def test_caminho_morno_nao_transfere(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '2', thread_id, monkeypatch)   # coloração
    _enviar(integracao, '1', thread_id, monkeypatch)   # loiro com mechas (clareza=10)
    _enviar(integracao, '2', thread_id, monkeypatch)   # próximos 15 dias (20)
    _enviar(integracao, '3', thread_id, monkeypatch)   # histórico (sem score)
    _enviar(integracao, '1', thread_id, monkeypatch)   # dentro do orçamento (25)
    _enviar(integracao, '3', thread_id, monkeypatch)   # não quer avaliação (0)
    enviados = _enviar(integracao, '3', thread_id, monkeypatch)  # não quer agendar (0) -> score 55 = MORNO

    assert enviados == ['Combinado! 💕 Fico à disposição pra tirar qualquer dúvida sobre nossos '
                         'serviços ou falar com uma de nossas especialistas quando quiser. Você '
                         'também pode retomar seu agendamento a qualquer momento — é só me chamar! 😊']

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa != 'transferido'
    assert estado.score_total == 55
    assert estado.classificacao == 'morno'
    assert estado.estado == 'concluido'


def test_rn08_forca_transferencia_mesmo_com_classificacao_fria(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)
    _enviar(integracao, '5', thread_id, monkeypatch)   # "ainda não sei" (clareza=5)
    _enviar(integracao, '4', thread_id, monkeypatch)   # só pesquisando (0)
    _enviar(integracao, '1', thread_id, monkeypatch)
    _enviar(integracao, '3', thread_id, monkeypatch)   # fora do orçamento (0)
    _enviar(integracao, '3', thread_id, monkeypatch)   # não quer avaliação (0)
    enviados = _enviar(integracao, '2', thread_id, monkeypatch)  # quer conversar antes -> força transferência

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.score_total == 17  # 5 (clareza) + 0 + 0 + 0 + 12 (agendamento opção 2) — bem abaixo de 40
    assert estado.classificacao == 'frio'
    assert lead.contato_etapa == 'transferido'  # mas RN08 opção 1/2 transfere de qualquer jeito
    assert enviados == [
        'Perfeito! 💕 Já tenho as informações necessárias para te ajudar com sua transformação!\n\n'
        'Vou encaminhar seu atendimento para nossa equipe, que vai verificar os '
        'melhores horários e te ajudar com os próximos passos. ✨'
    ]


def test_ja_sou_cliente_transfere_direto_sem_pontuacao(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    enviados = _enviar(integracao, '4', thread_id, monkeypatch)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.status == 'cliente_existente'
    assert lead.contato_etapa == 'transferido'
    assert estado.score_total is None
    assert enviados == ['Claro! 💕 Vou te encaminhar para nossa equipe para continuar seu atendimento.']


def test_escape_hatch_atendente_em_qualquer_etapa(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)   # agora está em 'prazo'
    enviados = _enviar(integracao, 'quero falar com um atendente', thread_id, monkeypatch)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'
    assert enviados == ['Claro! 💕 Vou te encaminhar para nossa equipe para continuar seu atendimento.']


def test_duas_respostas_nao_entendidas_transfere(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)       # tipo_transformacao
    primeira = _enviar(integracao, 'xablau', thread_id, monkeypatch)
    assert primeira[0] == 'Não entendi 😅 Digite o número de uma das opções acima.'

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa != 'transferido'
    assert estado.contador_nao_entendido == 1

    segunda = _enviar(integracao, 'zzz', thread_id, monkeypatch)
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'
    assert segunda == ['Vou te encaminhar pra nossa equipe pra te ajudar melhor! 💕']


def test_menu_reseta_o_funil_no_meio_do_caminho(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)   # está em 'prazo'
    enviados = _enviar(integracao, 'menu', thread_id, monkeypatch)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.estado == 'menu_principal'
    assert estado.fluxo is None
    assert estado.prazo_opcao is None
    assert '1. ✨ Mechas' in enviados[0]


def test_fluxo_simplificado_pula_perguntas_e_nunca_atinge_quente(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '3', thread_id, monkeypatch)   # corte/tratamento/escova
    _enviar(integracao, '1', thread_id, monkeypatch)   # prazo: nesta semana (25)
    enviados = _enviar(integracao, '1', thread_id, monkeypatch)  # quer agendar (30) -> transfere, score 65

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.fluxo == 'corte_tratamento'
    assert estado.investimento_opcao is None
    assert estado.avaliacao_opcao is None
    assert estado.score_total == 65
    assert estado.classificacao == 'morno'  # nunca QUENTE nesse sub-fluxo (teto é 65 < 70)
    assert lead.contato_etapa == 'transferido'  # RN08 opção 1 ainda força transferência


def test_rn05_nunca_inventa_valor(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)

    servico = Servico(nome='Retoque de Mechas', empresa_id=empresa.id, ativo=True, preco=350)
    db.session.add(servico)
    db.session.commit()

    thread_id_com_preco = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id_com_preco, monkeypatch)
    _enviar(integracao, '1', thread_id_com_preco, monkeypatch)          # mechas/coloração -> tipo_transformacao
    _enviar(integracao, '3', thread_id_com_preco, monkeypatch)          # retoque de mechas -> casa com o Servico -> prazo
    _enviar(integracao, '1', thread_id_com_preco, monkeypatch)          # prazo -> historico_cabelo
    texto_investimento = _enviar(integracao, '1', thread_id_com_preco, monkeypatch)[0]  # historico -> texto de investimento
    assert 'R$ 350,00' in texto_investimento

    thread_id_sem_preco = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id_sem_preco, monkeypatch)
    _enviar(integracao, '1', thread_id_sem_preco, monkeypatch)
    _enviar(integracao, '2', thread_id_sem_preco, monkeypatch)          # morena iluminada -> sem Servico cadastrado
    _enviar(integracao, '1', thread_id_sem_preco, monkeypatch)
    texto_sem_preco = _enviar(integracao, '1', thread_id_sem_preco, monkeypatch)[0]
    assert 'R$' not in texto_sem_preco
    assert 'avaliação' in texto_sem_preco


def test_delete_lead_com_funil_rr_nao_viola_fk(monkeypatch, client):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]
    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '1', thread_id, monkeypatch)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado is not None
    lead_id, estado_id = lead.id, estado.id

    username = f'admin{uuid.uuid4().hex[:10]}'
    user = User(name='Admin', username=username, email=f'{username}@teste.com',
                empresa_id=empresa.id, role='empresa_admin')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()

    client.post('/admin/login', data={'email': user.email, 'password': 'senha123'}, follow_redirects=True)
    resp = client.post(f'/admin/leads/{lead_id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    db.session.expunge_all()  # senão db.session.get() tenta refresh de PK já deletada
    assert db.session.get(Lead, lead_id) is None
    assert db.session.get(RenataRosaFunilLead, estado_id) is None


def test_reativacao_apos_handoff_reinicia_do_zero(monkeypatch):
    from datetime import datetime, timedelta
    from meta_webhook.routes import HANDOFF_REATIVACAO_HORAS

    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Olá', thread_id, monkeypatch)
    _enviar(integracao, '4', thread_id, monkeypatch)  # já cliente -> transfere, estado='concluido'

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'
    assert estado.estado == 'concluido'

    horas = HANDOFF_REATIVACAO_HORAS + 0.5
    Lead.query.filter_by(id=lead.id).update(
        {'updated_at': datetime.utcnow() - timedelta(hours=horas)})
    db.session.commit()

    enviados = _enviar(integracao, 'Oi de novo', thread_id, monkeypatch)

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa != 'transferido'
    assert estado.estado == 'menu_principal'
    assert estado.fluxo is None
    assert '1. ✨ Mechas' in enviados[0]
