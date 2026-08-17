"""Comparação de telefones — compartilhada entre o webhook da Meta e o
atendimento por IA. Convenção já usada em todo o app: comparar só os últimos 8
dígitos, ignorando formatação/DDI (números vindos da Meta e cadastrados no
sistema raramente chegam no mesmo formato)."""
import re


def somente_digitos(texto):
    return re.sub(r'\D', '', texto or '')


def mesmo_telefone(a, b):
    """True se `a` e `b` batem nos últimos 8 dígitos (ignora formatação/DDI)."""
    da, db_ = somente_digitos(a)[-8:], somente_digitos(b)[-8:]
    if len(da) < 8 or len(db_) < 8:
        return False
    return da == db_
