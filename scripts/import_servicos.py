"""
Importação sanitizada de serviços a partir de servicos.csv.

Regras de sanitização aplicadas:
- strip() em todos os campos de texto
- Duplicatas (mesmo nome, case-insensitive): mantida a linha com comissão maior
- Preço e comissão: formato PT-BR (1.234,56 → 1234.56)
- Tempo: parser de "1h30min", "45min", "2h" → (duracao_horas, duracao_minutos)
- Comissão 0 → não define comissão_valor (deixa NULL)
- Categorias criadas automaticamente se não existirem
- Serviços já existentes (mesmo nome, case-insensitive) são ignorados (idempotente)
"""

import sys
import os
import csv
import re
import io
from decimal import Decimal

# Garante que consegue importar os módulos do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import app
from models import db, Categoria, Servico


def parse_br_decimal(s: str) -> Decimal:
    """'2.990,00' → Decimal('2990.00')"""
    cleaned = s.strip().replace('.', '').replace(',', '.')
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal('0')


def parse_tempo(s: str):
    """
    '1h30min' → (1, 30)
    '45min'   → (0, 45)
    '2h'      → (2, 0)
    '15min'   → (0, 15)
    """
    s = s.strip()
    h_match  = re.search(r'(\d+)h', s)
    m_match  = re.search(r'(\d+)min', s)
    horas    = int(h_match.group(1)) if h_match else 0
    minutos  = int(m_match.group(1)) if m_match else 0
    if horas == 0 and minutos == 0:
        horas = 1
    return horas, minutos


def load_csv(path: str):
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        return list(reader)


def deduplicate(rows):
    """Mantém, entre duplicatas por nome, a linha com maior comissão."""
    seen = {}
    for r in rows:
        key = r['Nome'].strip().lower()
        com = parse_br_decimal(r['Comissão'])
        if key not in seen or com > parse_br_decimal(seen[key]['Comissão']):
            seen[key] = r
    return list(seen.values())


def sanitize(rows):
    clean = []
    for r in rows:
        clean.append({
            'nome':       r['Nome'].strip(),
            'categoria':  r['Categoria'].strip(),
            'preco':      parse_br_decimal(r['Preço']),
            'comissao':   parse_br_decimal(r['Comissão']),
            'tempo':      parse_tempo(r['Tempo']),
        })
    return clean


def run_import(dry_run=False):
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'servicos.csv')
    rows_raw = load_csv(csv_path)
    print(f'Linhas no CSV: {len(rows_raw)}')

    # Identificar duplicatas antes de remover
    from collections import defaultdict
    by_name = defaultdict(list)
    for r in rows_raw:
        by_name[r['Nome'].strip().lower()].append(r)
    dupes = {k: v for k, v in by_name.items() if len(v) > 1}
    if dupes:
        print('\n[DUPLICATAS DETECTADAS]')
        for name, group in dupes.items():
            for r in group:
                print(f'  Código {r["Código"]:>5}: "{r["Nome"]}" | comissão={r["Comissão"]}')
        print()

    rows_dedup = deduplicate(rows_raw)
    print(f'Após deduplicação: {len(rows_dedup)} serviços')

    rows = sanitize(rows_dedup)

    with app.app_context():
        # --- Garante categorias ---
        cat_names = sorted(set(r['categoria'] for r in rows))
        cat_map = {}
        for nome in cat_names:
            cat = Categoria.query.filter(
                db.func.lower(Categoria.nome) == nome.lower()
            ).first()
            if cat is None:
                if not dry_run:
                    cat = Categoria(nome=nome, ativo=True)
                    db.session.add(cat)
                    db.session.flush()
                print(f'  [CAT NOVA] {nome}')
            else:
                print(f'  [CAT OK]   {nome} (id={cat.id})')
            cat_map[nome.lower()] = cat

        if not dry_run:
            db.session.flush()

        # --- Importa serviços ---
        criados = 0
        ignorados = 0
        for r in rows:
            nome_lower = r['nome'].lower()
            exists = Servico.query.filter(
                db.func.lower(Servico.nome) == nome_lower
            ).first()
            if exists:
                ignorados += 1
                continue

            cat = cat_map.get(r['categoria'].lower())
            horas, minutos = r['tempo']
            comissao = r['comissao'] if r['comissao'] > 0 else None

            if not dry_run:
                svc = Servico(
                    nome=r['nome'],
                    preco=r['preco'] if r['preco'] > 0 else None,
                    duracao_horas=horas,
                    duracao_minutos=minutos,
                    comissao_valor=comissao,
                    comissao_tipo='%',
                    categoria_id=cat.id if cat else None,
                    ativo=True,
                )
                db.session.add(svc)
            criados += 1

        if not dry_run:
            db.session.commit()
            print(f'\nImportação concluída: {criados} criados, {ignorados} ignorados (já existiam).')
        else:
            print(f'\n[DRY RUN] Seriam criados: {criados}, ignorados: {ignorados}.')


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    run_import(dry_run=dry)
