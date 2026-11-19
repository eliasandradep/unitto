"""Fase 5b do funil da Renata Rosa — fluxos completos de qualificação por
tópico de serviço (renata_rosa_bot/fluxos.py + orquestrador.py). Mesmo
padrão das demais fases (_processar_evento direto, NLU sempre mockada).

Usa ILUMINAR como representante da mecânica comum a ILUMINAR/COR/CORTE
(pergunta a pergunta -> fotos -> encaminha); TRATAMENTO tem casos próprios
(sem etapa de fotos, 1ª pergunta com alternativas numeradas)."""
import uuid
from unittest.mock import patch

from models import db, Lead, RenataRosaFunilLead, RenataRosaFunilFoto
from renata_rosa_bot import fluxos
from renata_rosa_bot.nlu import NLUError
import meta_client
from meta_webhook.routes import _processar_evento
from tests.conftest import make_empresa, make_integracao_whatsapp


def _empresa_rr(**kwargs):
    defaults = dict(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                     funil_qualificacao_rr_ativo=True)
    defaults.update(kwargs)
    return make_empresa(**defaults)


def _evento(integracao, mensagem, thread_id, media_id=None, media_mime_type=None):
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
        'media_id': media_id,
        'media_mime_type': media_mime_type,
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


def _enviar(integracao, mensagem, thread_id, monkeypatch, nlu_result=None, nlu_erro=False,
            media_id=None, media_mime_type=None):
    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    patcher = patch('renata_rosa_bot.nlu.classificar',
                     side_effect=NLUError('mock') if nlu_erro else None,
                     return_value=nlu_result)
    with patcher:
        _processar_evento(_evento(integracao, mensagem, thread_id, media_id, media_mime_type))
    return enviados


def _lead_e_estado(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first() if lead else None
    return lead, estado


def test_atalho_por_numero_entra_no_topico_sem_chamar_nlu(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    with patch('renata_rosa_bot.nlu.classificar') as mock_nlu:
        _processar_evento(_evento(integracao, '2', thread_id))
        assert mock_nlu.called is False

    assert len(enviados) == 2
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.topico_ativo == 'COR'  # opção 2 do menu (INTENTS_MENU_RR)
    assert estado.pergunta_idx == 0


def test_fluxo_iluminar_completo_ate_fotos_e_encaminha(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    total = fluxos.total_perguntas('ILUMINAR')
    _enviar(integracao, '1', thread_id, monkeypatch)  # entra pelo atalho de número
    for _ in range(total - 1):
        enviados = _enviar(integracao, 'resposta qualquer', thread_id, monkeypatch,
                            nlu_result=_resultado(topico='ILUMINAR'))
        assert len(enviados) == 1

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.pergunta_idx == total - 1

    # última pergunta de texto respondida -> etapa de fotos
    enviados = _enviar(integracao, 'pra semana que vem', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='ILUMINAR'))
    assert enviados == [
        'Se desejar, você pode nos enviar uma foto atual do seu cabelo e uma '
        'imagem de referência do resultado que gostaria de alcançar. 💕\n\n'
        'Usamos as fotos só como referência preliminar pra nossa especialista se '
        'preparar — elas ficam guardadas no seu cadastro e só a equipe autorizada '
        'tem acesso. O envio é totalmente opcional.\n\n'
        'Quando terminar (ou se preferir não enviar agora), é só me mandar '
        'qualquer mensagem que a gente continua. 😊'
    ]
    db.session.refresh(estado)
    assert estado.pergunta_idx == total

    # qualquer texto na etapa de fotos encaminha pra equipe
    enviados = _enviar(integracao, 'pode seguir sem foto', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='ILUMINAR'))
    assert len(enviados) == 1
    db.session.refresh(lead)
    assert lead.contato_etapa == 'transferido'


def test_fluxo_iluminar_recebe_foto_e_marca_pontuacao(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    total = fluxos.total_perguntas('ILUMINAR')
    _enviar(integracao, '1', thread_id, monkeypatch)
    for _ in range(total - 1):
        _enviar(integracao, 'resposta', thread_id, monkeypatch, nlu_result=_resultado(topico='ILUMINAR'))
    _enviar(integracao, 'ok', thread_id, monkeypatch, nlu_result=_resultado(topico='ILUMINAR'))  # etapa de fotos

    lead, estado = _lead_e_estado(empresa, thread_id)

    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'fake-bytes', 'image/jpeg')):
        enviados = _enviar(integracao, '', thread_id, monkeypatch, media_id='media-123',
                            media_mime_type='image/jpeg')
    assert enviados == ['Recebido! 💕 Pode mandar mais uma, se quiser, ou é só seguir quando terminar.']
    assert RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).count() == 1
    db.session.refresh(estado)
    assert estado.pt_referencia_foto is True

    # 2ª foto: grava, mas não reconhece de novo
    with patch('meta_client.baixar_midia_whatsapp', return_value=(b'fake-bytes-2', 'image/jpeg')):
        enviados = _enviar(integracao, '', thread_id, monkeypatch, media_id='media-456',
                            media_mime_type='image/jpeg')
    assert enviados == []
    assert RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).count() == 2

    # depois das fotos, qualquer texto encaminha
    enviados = _enviar(integracao, 'pronto', thread_id, monkeypatch, nlu_result=_resultado(topico='ILUMINAR'))
    assert len(enviados) == 1
    db.session.refresh(lead)
    assert lead.contato_etapa == 'transferido'


def test_tratamento_nao_tem_etapa_de_fotos(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    total = fluxos.total_perguntas('TRATAMENTO')
    assert total == 2
    _enviar(integracao, '3', thread_id, monkeypatch)  # opção 3 do menu principal
    enviados = _enviar(integracao, '1', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='TRATAMENTO'))  # responde a 1ª pergunta
    assert len(enviados) == 1

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.servico_opcao_label == 'Ressecamento'
    assert estado.pt_servico_especifico is True

    # última pergunta -> encaminha direto, sem pedir foto
    enviados = _enviar(integracao, 'quero fazer essa semana', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='TRATAMENTO'))
    assert len(enviados) == 1
    db.session.refresh(lead)
    assert lead.contato_etapa == 'transferido'


def test_interesse_forte_no_meio_do_fluxo_transfere_antes_de_terminar(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, '1', thread_id, monkeypatch)  # entra no fluxo ILUMINAR
    _enviar(integracao, 'ja tenho mechas', thread_id, monkeypatch, nlu_result=_resultado(topico='ILUMINAR'))

    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa != 'transferido'
    assert estado.pergunta_idx == 1

    _enviar(integracao, 'quero agendar logo', thread_id, monkeypatch,
            nlu_result=_resultado(topico='ILUMINAR', quer_agendar=True))

    db.session.refresh(lead)
    db.session.refresh(estado)
    assert lead.contato_etapa == 'transferido'
    assert estado.classificacao == 'quente'


def test_troca_de_topico_no_meio_do_fluxo_reinicia_pergunta_idx(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, '1', thread_id, monkeypatch)  # ILUMINAR
    _enviar(integracao, 'resposta', thread_id, monkeypatch, nlu_result=_resultado(topico='ILUMINAR'))
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert estado.topico_ativo == 'ILUMINAR'
    assert estado.pergunta_idx == 1

    enviados = _enviar(integracao, 'na verdade quero saber de coloração', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='COR'))
    db.session.refresh(estado)
    assert estado.topico_ativo == 'COR'
    assert estado.pergunta_idx == 0
    assert len(enviados) == 2  # intro + primeira pergunta do novo tópico


def test_desinteresse_no_meio_do_fluxo_interrompe_sem_transferir(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    _enviar(integracao, '1', thread_id, monkeypatch)
    enviados = _enviar(integracao, 'na verdade deixa pra lá', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='ILUMINAR', demonstrou_desinteresse=True))

    assert enviados == ['Claro! 💕 Pode pesquisar com tranquilidade. Se quiser, posso te mostrar '
                         'algumas opções para você se inspirar quando quiser. 😊']
    lead, estado = _lead_e_estado(empresa, thread_id)
    assert lead.contato_etapa != 'transferido'
    assert estado.status_comercial == 'sem_interesse'
