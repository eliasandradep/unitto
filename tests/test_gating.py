"""Gating: tem_atendimento_ia() / ia_disponivel() para cada combinação
plano x toggle x status — o requisito central de autorização no backend."""
import pytest

from ai_attendance.gating import ia_disponivel
from tests.conftest import make_empresa


@pytest.mark.parametrize('plano,ativo,esperado', [
    ('pro',   True,  True),
    ('pro',   False, False),
    ('black', True,  False),   # propositalmente fora — só 'pro' libera (decisão de produto)
    ('free',  True,  False),
    ('trial', True,  False),
    ('pro-anual', True, True),  # plano_familia remove o sufixo -anual
])
def test_tem_atendimento_ia_por_plano_e_toggle(plano, ativo, esperado):
    emp = make_empresa(plano=plano, atendimento_ia_ativo=ativo)
    assert emp.tem_atendimento_ia() is esperado


def test_ia_disponivel_false_se_empresa_suspensa():
    emp = make_empresa(plano='pro', atendimento_ia_ativo=True, status='suspensa')
    assert emp.tem_atendimento_ia() is True   # plano/toggle ok...
    assert ia_disponivel(emp) is False        # ...mas empresa inativa bloqueia no gate central


def test_ia_disponivel_true_para_pro_ativo():
    emp = make_empresa(plano='pro', atendimento_ia_ativo=True, status='ativa')
    assert ia_disponivel(emp) is True


def test_ia_disponivel_false_para_empresa_none():
    assert ia_disponivel(None) is False
