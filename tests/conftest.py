"""Setup de testes — SQLite em arquivo temporário (não :memory:, pra evitar o
gotcha de cada conexão do pool virar um banco novo em branco). Anthropic nunca
é chamada de verdade: os testes que passam pelo NLU mockam
ai_attendance.nlu.classificar diretamente.
"""
import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DB_PATH = os.path.join(tempfile.gettempdir(), f'unitto_test_{uuid.uuid4().hex}.db')
os.environ['DATABASE_URL'] = f'sqlite:///{_DB_PATH}'
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('BASE_DOMAIN', 'unitto.com.br')
os.environ.setdefault('META_APP_SECRET', 'test-meta-app-secret')
os.environ.setdefault('META_TOKEN_ENCRYPTION_KEY', 'zGX2s6Yt4qk8xW3vB1nJcQ7fH9dP0mR5uL6oT2eA4iY=')
os.environ.setdefault('ANTHROPIC_API_KEY', '')  # propositalmente vazia — testes nunca devem chamar a API real

import pytest
from datetime import date, time, timedelta

from app import app as flask_app
from models import (db, Empresa, Servico, Profissional, Expediente, ExpedienteDia,
                     IntegracaoMeta, Lead)
from crypto_utils import encrypt_token


@pytest.fixture(autouse=True)
def app_context():
    with flask_app.app_context():
        yield flask_app
        db.session.rollback()


@pytest.fixture
def client():
    return flask_app.test_client()


_contador = [0]


def _slug_unico(prefixo):
    _contador[0] += 1
    return f'{prefixo}-{_contador[0]}-{uuid.uuid4().hex[:6]}'


def make_empresa(plano='pro', atendimento_ia_ativo=True, status='ativa', nome='Empresa Teste'):
    emp = Empresa(nome=nome, slug=_slug_unico('empresa'), plano=plano, status=status,
                  atendimento_ia_ativo=atendimento_ia_ativo)
    db.session.add(emp)
    db.session.commit()
    return emp


def make_integracao_whatsapp(empresa, identificador_externo=None):
    integ = IntegracaoMeta(
        empresa_id=empresa.id, canal='whatsapp',
        identificador_externo=identificador_externo or _slug_unico('phoneid'),
        numero_whatsapp='5511999990000',
        access_token_enc=encrypt_token('fake-token'),
        status='conectado',
    )
    db.session.add(integ)
    db.session.commit()
    return integ


def make_booking_setup(empresa, nome_servico='Corte', preco=100, duracao_min=60):
    expediente = Expediente(nome='Padrão', empresa_id=empresa.id)
    db.session.add(expediente)
    db.session.flush()
    for dow in range(7):
        db.session.add(ExpedienteDia(expediente_id=expediente.id, dia_semana=dow,
                                      hora_inicio=time(8, 0), hora_fim=time(18, 0)))
    db.session.flush()

    profissional = Profissional(nome='Profissional Teste', empresa_id=empresa.id,
                                 ativo=True, agendamento_online=True, expediente_id=expediente.id)
    db.session.add(profissional)
    db.session.flush()

    servico = Servico(nome=nome_servico, empresa_id=empresa.id, ativo=True, agendamento_online=True,
                       exibir_preco_online=True, preco=preco,
                       duracao_horas=duracao_min // 60, duracao_minutos=duracao_min % 60)
    servico.profissionais_adicionais.append(profissional)
    db.session.add(servico)
    db.session.commit()
    return servico, profissional


def make_lead(empresa, integracao, external_thread_id='5511988887777', name='Cliente Teste'):
    lead = Lead(empresa_id=empresa.id, integracao_id=integracao.id, name=name,
                external_thread_id=external_thread_id, phone=external_thread_id, source='whatsapp_meta')
    db.session.add(lead)
    db.session.commit()
    return lead


def proxima_segunda():
    """Primeira segunda-feira (isoweekday 1) a partir de amanhã — evita testes
    que dependem de dia útil frágeis rodando sempre num dia da semana fixo."""
    d = date.today() + timedelta(days=1)
    while d.isoweekday() != 1:
        d += timedelta(days=1)
    return d
