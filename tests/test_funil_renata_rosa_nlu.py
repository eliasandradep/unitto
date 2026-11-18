"""Fase 5a do funil da Renata Rosa — motor com NLU real (ver
renata_rosa_bot/nlu.py e orquestrador.py). Mesmo padrão das fases
anteriores (_processar_evento direto, bypassa a camada HTTP do webhook),
mas agora mockando `renata_rosa_bot.nlu.classificar` em vez de simular
dígitos — a chamada real à Anthropic nunca acontece em teste."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilLead, User
from renata_rosa_bot.nlu import NLUError
import meta_client
from meta_webhook.routes import _processar_evento
from renata_rosa_bot.menu import atualizar_opcoes
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


def _resultado(topico='OUTRO', **overrides):
    base = {
        'topico': topico, 'quer_agendar': False, 'quer_humano': False, 'tem_reclamacao': False,
        'demonstrou_desinteresse': False, 'servico_mencionado': '', 'resultado_desejado': '',
        'prazo_mencionado': '', 'prazo_ate_15_dias': False, 'perguntou_valores': False,
        'perguntou_disponibilidade': False, 'pergunta_direta': '', 'resposta_ao_cliente': '',
    }
    base.update(overrides)
    return base


def _lead_e_estado(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first() if lead else None
    return lead, estado


def test_saudacao_livre_mostra_menu_principal(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'Oi, tudo bem?', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='OUTRO'))

    assert len(enviados) == 1
    assert 'Renata Rosa Beauty Concept' in enviados[0]
    assert '✨ Quero iluminar' in enviados[0]
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.status_comercial == 'novo_lead'


def test_topico_salao_mostra_info_e_pergunta_final(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'quero conhecer o salão', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='SALAO'))

    assert len(enviados) == 2
    assert 'combina mais' in enviados[1]
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.topico_ativo == 'SALAO'
    assert estado.status_comercial == 'em_atendimento_ia'


def test_pedido_humano_transfere_imediatamente(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'quero falar com uma especialista', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='HUMANO', quer_humano=True))

    assert enviados == ['Perfeito! 💕 Vou encaminhar nossa conversa para a equipe do Renata Rosa '
                         'Beauty Concept, que poderá te orientar sobre valores, disponibilidade e '
                         'os próximos passos. ✨']
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'
    assert estado.status_comercial == 'aguardando_atendimento_humano'


def test_reclamacao_transfere_mesmo_sem_pedir_humano(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Fui péssimo atendida da última vez', thread_id, monkeypatch,
            nlu_result=_resultado(topico='OUTRO', tem_reclamacao=True))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'


def test_intencao_de_agendar_forca_quente_e_transfere(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'Tem horário sexta?', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', quer_agendar=True))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'
    assert estado.classificacao == 'quente'
    assert estado.score_total == 30  # só pt_intencao_agendar, mesmo assim força quente
    assert 'QUENTE' in lead.notes


def test_servico_sem_fluxo_proprio_reconhece_e_oferece_encaminhar(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'queria saber sobre mechas', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas',
                                               resposta_ao_cliente='Que escolha maravilhosa! ✨'))

    assert enviados == ['Que escolha maravilhosa! ✨',
                         'Quer que eu encaminhe suas informações para nossa equipe conversar com '
                         'você sobre os próximos passos?']
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.topico_ativo == 'ILUMINAR'
    assert estado.pt_servico_especifico is True
    assert estado.servico_opcao_label == 'Mechas'
    assert lead.contato_etapa != 'transferido'  # ainda não transfere sozinho


def test_score_natural_quente_transfere_mesmo_sem_pedir_pra_agendar(monkeypatch):
    """Bug real pego no smoke test: só transferia quando havia pedido
    explícito de agendar (forcar_quente) — mas seção 5.2 exige transferir
    todo lead Quente, mesmo quando chegou lá só por acúmulo de pontos."""
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'quero mechas pra essa semana, quanto custa?', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas',
                                   resultado_desejado='ficar mais loira', prazo_mencionado='essa semana',
                                   prazo_ate_15_dias=True, perguntou_valores=True))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.score_total == 70  # 15+10+15+20+10, sem forcar_quente
    assert estado.classificacao == 'quente'
    assert lead.contato_etapa == 'transferido'
    assert estado.forcar_quente is False


def test_desinteresse_marca_status_sem_pressionar(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'só estou pesquisando por enquanto', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='OUTRO', demonstrou_desinteresse=True))

    assert enviados == ['Claro! 💕 Pode pesquisar com tranquilidade. Se quiser, posso te mostrar '
                         'algumas opções para você se inspirar quando quiser. 😊']
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.status_comercial == 'sem_interesse'
    assert lead.contato_etapa != 'transferido'


def test_reengaja_sozinha_apos_sem_interesse(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'só pesquisando', thread_id, monkeypatch,
            nlu_result=_resultado(topico='OUTRO', demonstrou_desinteresse=True))
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.status_comercial == 'sem_interesse'

    _enviar(integracao, 'na verdade quero saber sobre coloração', thread_id, monkeypatch,
            nlu_result=_resultado(topico='COR'))
    db.session.refresh(estado)
    assert estado.status_comercial == 'em_atendimento_ia'


def test_fallback_regex_nunca_deixa_sem_resposta_quando_nlu_falha(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'quero falar com atendente', thread_id, monkeypatch, nlu_erro=True)

    assert len(enviados) >= 1
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa == 'transferido'  # fallback regex reconheceu "atendente"


def test_cada_criterio_de_pontuacao_conta_uma_unica_vez_por_ciclo(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, 'quero mechas', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas'))
    _enviar(integracao, 'ainda mechas', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', servico_mencionado='Mechas'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.score_total == 15  # não dobrou por repetir o mesmo sinal


def test_menu_editavel_pelo_admin_reflete_no_texto_enviado(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    atualizar_opcoes(empresa, {'titulo': 'Bem-vinda ao novo texto de boas-vindas!'})

    enviados = _enviar(integracao, 'oi', thread_id, monkeypatch, nlu_result=_resultado(topico='OUTRO'))
    assert 'Bem-vinda ao novo texto de boas-vindas!' in enviados[0]


def test_isolamento_outro_tenant_nunca_aciona_nlu(monkeypatch):
    empresa = make_empresa(plano='pro', atendimento_ia_ativo=True)  # slug != 'renatarosa'
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    with patch('renata_rosa_bot.nlu.classificar') as mock_nlu:
        monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp', lambda *a, **k: None)
        with patch('meta_webhook.routes.processar_mensagem', return_value=['oi do motor genérico']):
            _processar_evento(_evento(integracao, 'Olá', thread_id))
        assert mock_nlu.called is False
