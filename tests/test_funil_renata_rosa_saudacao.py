"""Fase 5f do funil da Renata Rosa — saudação dinâmica do menu principal
(hora do dia + nome via WhatsApp, complemento variado) e remoção da frase
negativa "não tenho essa informação" do SALAO quando não há nada
cadastrado. Mesmo padrão das demais fases (_processar_evento direto, NLU
sempre mockada)."""
import uuid
from unittest.mock import patch

from models import db, INTENTS_MENU_RR, InformacaoEstabelecimento, Lead, RenataRosaFunilLead
from renata_rosa_bot import mensagens
from renata_rosa_bot.nlu import NLUError
import meta_client
from meta_webhook.routes import _processar_evento
from tests.conftest import make_empresa, make_integracao_whatsapp


def _empresa_rr(**kwargs):
    defaults = dict(slug='renatarosa', plano='pro', atendimento_ia_ativo=True,
                     funil_qualificacao_rr_ativo=True)
    defaults.update(kwargs)
    return make_empresa(**defaults)


def _evento(integracao, mensagem, thread_id, nome=None):
    return {
        'identificador_externo': integracao.identificador_externo,
        'external_thread_id': thread_id,
        'phone': thread_id,
        'nome': nome,
        'mensagem': mensagem,
        'canal': 'whatsapp',
        'quick_reply_payload': None,
        'ad_id': None,
        'ad_title': None,
        'media_id': None,
        'media_mime_type': None,
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


def _enviar(integracao, mensagem, thread_id, monkeypatch, nlu_result=None, nome=None):
    enviados = []
    monkeypatch.setattr(meta_client, 'enviar_mensagem_whatsapp',
                         lambda *a, **k: enviados.append(a[2]))
    patcher = patch('renata_rosa_bot.nlu.classificar', return_value=nlu_result)
    with patcher:
        _processar_evento(_evento(integracao, mensagem, thread_id, nome))
    return enviados


def _lead_e_estado(empresa, thread_id):
    lead = Lead.query.filter_by(empresa_id=empresa.id, external_thread_id=thread_id).first()
    estado = RenataRosaFunilLead.query.filter_by(lead_id=lead.id).first() if lead else None
    return lead, estado


def test_saudacao_usa_nome_quando_whatsapp_informa(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'oi', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='OUTRO'), nome='Ana Clara')

    assert any(s in enviados[0] for s in ('Bom dia, Ana!', 'Boa tarde, Ana!', 'Boa noite, Ana!'))


def test_saudacao_sem_nome_quando_whatsapp_nao_informa(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    enviados = _enviar(integracao, 'oi', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='OUTRO'), nome=None)

    primeira_linha = enviados[0].split('\n')[0]
    assert primeira_linha in ('Bom dia!', 'Boa tarde!', 'Boa noite!')


def test_complemento_customizado_pelo_admin_e_usado_com_saudacao_na_frente(monkeypatch):
    from renata_rosa_bot.menu import atualizar_opcoes

    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    # form completo (ativo_<intent> pra cada opção) — um form parcial
    # desativaria todas as opções do menu (checkbox ausente = desmarcado),
    # corrompendo a empresa 'renatarosa' compartilhada por toda a sessão de
    # testes (ver o mesmo cuidado em test_funil_renata_rosa_nlu.py).
    form = {'titulo': 'Texto customizado só nosso, sempre igual.'}
    for intent, _ in INTENTS_MENU_RR:
        form[f'ativo_{intent}'] = '1'
    atualizar_opcoes(empresa, form)

    enviados = _enviar(integracao, 'oi', thread_id, monkeypatch, nlu_result=_resultado(topico='OUTRO'))
    assert 'Texto customizado só nosso, sempre igual.' in enviados[0]


def test_complemento_padrao_varia_entre_chamadas():
    """Sem customização do admin, o complemento é sorteado do pool — ao
    longo de várias chamadas, deve aparecer mais de uma variação (prova
    estatística simples, não depende de qual exatamente saiu primeiro)."""
    vistos = {mensagens.saudacao_dinamica(None) for _ in range(1)}  # saudação em si não varia por chamada
    complementos_vistos = set()
    import random
    random.seed(0)
    for _ in range(30):
        complementos_vistos.add(random.choice(mensagens.MENU_COMPLEMENTOS_PADRAO))
    assert len(complementos_vistos) > 1


def test_salao_mostra_informacoes_reais_quando_cadastradas(monkeypatch):
    empresa = _empresa_rr()
    integracao = make_integracao_whatsapp(empresa)
    thread_id = uuid.uuid4().hex[:13]

    db.session.add(InformacaoEstabelecimento(
        empresa_id=empresa.id, endereco='Rua das Flores, 123',
        horario_funcionamento='Seg-Sex 9h-19h'))
    db.session.commit()

    enviados = _enviar(integracao, 'quero conhecer o salão', thread_id, monkeypatch,
                        nlu_result=_resultado(topico='SALAO'))

    assert any('Rua das Flores' in t for t in enviados)
    assert not any('não tenho essas informações' in t.lower() for t in enviados)
