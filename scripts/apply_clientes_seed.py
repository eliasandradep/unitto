"""
Aplica o seed de clientes gerado por import_pacientes.py no banco configurado
pelo DATABASE_URL (local SQLite ou Railway PostgreSQL).

Uso:
  python scripts/apply_clientes_seed.py [--dry-run]

No Railway:
  railway run python scripts/apply_clientes_seed.py
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

SEED_PATH = os.path.join(os.path.dirname(__file__), 'clientes_seed.json')


def run(dry_run=False):
    from app import app
    from models import db, Cliente

    if not os.path.exists(SEED_PATH):
        print(f'ERRO: seed não encontrado em {SEED_PATH}')
        print('Execute primeiro: python scripts/import_pacientes.py --dry-run')
        sys.exit(1)

    with open(SEED_PATH, encoding='utf-8') as f:
        records = json.load(f)

    print(f'Seed carregado: {len(records)} registros')
    print(f'Banco: {os.getenv("DATABASE_URL", "sqlite:///studio.db (local)")}')

    if dry_run:
        print('[DRY RUN] Nenhum dado será gravado.')
        return

    with app.app_context():
        criados = 0
        pulados = 0
        erros   = []

        for r in records:
            try:
                tel = r.get('telefone') or None
                if tel:
                    if Cliente.query.filter_by(telefone=tel).first():
                        pulados += 1
                        continue

                c = Cliente()
                c.nome        = r['nome']
                c.telefone    = tel
                c.email       = r.get('email')
                c.cpf         = r.get('cpf')
                c.aniversario = (datetime.strptime(r['aniversario'], '%Y-%m-%d').date()
                                 if r.get('aniversario') else None)
                c.sexo        = r.get('sexo')
                c.cep         = r.get('cep')
                c.endereco    = r.get('endereco')
                c.numero      = r.get('numero')
                c.complemento = r.get('complemento')
                c.cidade      = r.get('cidade')
                c.estado      = r.get('estado')
                c.descricao   = r.get('descricao')
                c.updated_at  = datetime.utcnow()

                db.session.add(c)
                criados += 1

                if criados % 500 == 0:
                    db.session.flush()
                    print(f'  ... {criados} inseridos')

            except Exception as e:
                erros.append(f'{r.get("nome", "?")} → {e}')

        db.session.commit()
        print(f'\nConcluído: {criados} criados, {pulados} já existiam.')
        if erros:
            print(f'{len(erros)} erro(s):')
            for e in erros[:20]:
                print(f'  {e}')


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    run(dry_run=dry)
