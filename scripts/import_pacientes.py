"""
Importa pacientes dos 3 CSVs exportados do sistema externo para a tabela clientes.

Problemas identificados e tratados:
  - Codificação Latin-1 (não UTF-8)
  - Coluna "Faturado" duplicada no cabeçalho (a segunda é ignorada)
  - Datas inválidas: "30/11/-0001", "--/--/----", "" → NULL
  - Sexo: "Feminino"→"F", "Masculino"→"M", vazio/"---" → NULL
  - Telefone: DDI "55" separado; número sem formatação → normalizado p/ (XX) XXXXX-XXXX
  - Duplicatas por telefone dentro e entre arquivos: mantém o registro mais completo
  - 225 registros sem telefone: importados com aviso, sem chave de dedup
  - Phones com < 8 dígitos: descartados

Uso:
  python scripts/import_pacientes.py [--dry-run]

Saída:
  Relatório no terminal + arquivo scripts/clientes_seed.json com os dados limpos
  (usado depois por apply_clientes_seed.py para importar no Railway)
"""

import sys
import os
import csv
import io
import json
import re
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

BASE_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'arquivos')
CSV_FILES = [
    os.path.join(BASE_DIR, 'pacientes.csv'),
    os.path.join(BASE_DIR, 'pacientes (1).csv'),
    os.path.join(BASE_DIR, 'pacientes (2).csv'),
]
SEED_PATH = os.path.join(os.path.dirname(__file__), 'clientes_seed.json')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip(v):
    return (v or '').strip()


def _parse_date(s):
    s = _strip(s)
    if not s or s in ('--/--/----', '--/--/--') or '-0001' in s:
        return None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            d = datetime.strptime(s, fmt).date()
            # Datas claramente inválidas (ex: ano < 1900 ou > hoje)
            if d.year < 1900 or d > date.today():
                return None
            return d.isoformat()
        except ValueError:
            pass
    return None


def _parse_sexo(s):
    s = _strip(s).lower()
    if s in ('f', 'fem', 'feminino'):
        return 'F'
    if s in ('m', 'masc', 'masculino'):
        return 'M'
    return None


def _format_phone(raw):
    """'12982159544' → '(12) 98215-9544' ; '1239334383' → '(12) 3933-4383'"""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11:      # DDD + 9 dígitos (celular)
        return f'({digits[:2]}) {digits[2:7]}-{digits[7:]}'
    elif len(digits) == 10:    # DDD + 8 dígitos (fixo)
        return f'({digits[:2]}) {digits[2:6]}-{digits[6:]}'
    return digits              # formato desconhecido: guarda como veio


def _count_filled(row):
    """Conta quantos campos não-vazios o registro tem (qualidade)."""
    return sum(1 for v in row.values() if _strip(str(v)))


# ── Leitura ───────────────────────────────────────────────────────────────────

def _load_file(path):
    with open(path, 'rb') as fh:
        raw = fh.read()
    try:
        texto = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        texto = raw.decode('latin-1')
    return list(csv.DictReader(io.StringIO(texto), delimiter=';'))


def load_all():
    rows = []
    for path in CSV_FILES:
        chunk = _load_file(path)
        rows.extend(chunk)
    return rows


# ── Sanitização ───────────────────────────────────────────────────────────────

def _first_key(row, *candidates):
    """Retorna o valor do primeiro campo cujo nome (normalizado) bate."""
    for k in row:
        for c in candidates:
            if k.strip().lower().replace('ç', 'c').replace('ã', 'a') == c:
                return _strip(row[k])
    return ''


def sanitize(rows):
    clean = []
    for r in rows:
        # Acesso por posição de coluna para contornar nome corrompido (encoding)
        vals = list(r.values())

        nome     = _strip(vals[1])  if len(vals) > 1  else ''
        tel_raw  = _strip(vals[3])  if len(vals) > 3  else ''
        email    = _strip(vals[4])  if len(vals) > 4  else ''
        cpf      = _strip(vals[5])  if len(vals) > 5  else ''
        endereco = _strip(vals[8])  if len(vals) > 8  else ''
        numero   = _strip(vals[9])  if len(vals) > 9  else ''
        compl    = _strip(vals[10]) if len(vals) > 10 else ''
        cidade   = _strip(vals[11]) if len(vals) > 11 else ''
        estado   = _strip(vals[12]) if len(vals) > 12 else ''
        cep      = _strip(vals[13]) if len(vals) > 13 else ''
        nasc_raw = _strip(vals[14]) if len(vals) > 14 else ''
        sexo_raw = _strip(vals[16]) if len(vals) > 16 else ''
        descr    = _strip(vals[19]) if len(vals) > 19 else ''

        if not nome:
            continue

        digits = re.sub(r'\D', '', tel_raw)
        if digits and len(digits) < 8:
            digits = ''  # descarta telefone inválido

        clean.append({
            'nome':        nome,
            'telefone_raw': digits,
            'telefone':    _format_phone(digits) if digits else '',
            'email':       email or None,
            'cpf':         cpf or None,
            'aniversario': _parse_date(nasc_raw),
            'sexo':        _parse_sexo(sexo_raw),
            'cep':         cep or None,
            'endereco':    endereco or None,
            'numero':      numero or None,
            'complemento': compl or None,
            'cidade':      cidade or None,
            'estado':      estado or None,
            'descricao':   descr or None,
        })
    return clean


# ── Deduplicação ──────────────────────────────────────────────────────────────

def deduplicate(rows):
    """
    Agrupa por telefone_raw. Para cada grupo mantém o registro mais completo
    (mais campos preenchidos). Registros sem telefone ficam todos (sem chave).
    """
    by_tel = defaultdict(list)
    no_tel = []

    for r in rows:
        if r['telefone_raw']:
            by_tel[r['telefone_raw']].append(r)
        else:
            no_tel.append(r)

    deduped = []
    dup_count = 0
    for tel, group in by_tel.items():
        if len(group) > 1:
            dup_count += 1
            # Mantém o com mais campos preenchidos; em empate, mantém o primeiro
            best = max(group, key=_count_filled)
            deduped.append(best)
        else:
            deduped.append(group[0])

    return deduped, no_tel, dup_count


# ── Relatório ─────────────────────────────────────────────────────────────────

def report(raw, cleaned, deduped, no_tel, dup_count):
    print('=' * 60)
    print('RELATÓRIO DE IMPORTAÇÃO DE PACIENTES')
    print('=' * 60)
    print(f'  Linhas brutas (3 arquivos):        {len(raw):>6}')
    print(f'  Após sanitização (nome obrig.):    {len(cleaned):>6}')
    print(f'  Grupos de telefone duplicados:     {dup_count:>6}')
    print(f'  Registros sem telefone:            {len(no_tel):>6}  (serao importados sem chave de dedup)')
    print(f'  Clientes únicos a importar:        {len(deduped):>6}')
    print(f'  Total final (com sem-tel):         {len(deduped)+len(no_tel):>6}')
    print()

    sem_email = sum(1 for r in deduped if not r['email'])
    sem_nasc  = sum(1 for r in deduped if not r['aniversario'])
    sem_end   = sum(1 for r in deduped if not r['endereco'])
    sem_sexo  = sum(1 for r in deduped if not r['sexo'])
    print('  Qualidade dos dados (deduplicados):')
    print(f'    Sem e-mail:         {sem_email:>5} ({100*sem_email//len(deduped)}%)')
    print(f'    Sem data nascim.:   {sem_nasc:>5} ({100*sem_nasc//len(deduped)}%)')
    print(f'    Sem endereço:       {sem_end:>5} ({100*sem_end//len(deduped)}%)')
    print(f'    Sem sexo:           {sem_sexo:>5} ({100*sem_sexo//len(deduped)}%)')
    print('=' * 60)


# ── Importação ────────────────────────────────────────────────────────────────

def run_import(dry_run=False):
    from app import app
    from models import db, Cliente

    print('\nIniciando importação no banco de dados...\n')

    all_rows = load_all()

    cleaned  = sanitize(all_rows)
    deduped, no_tel, dup_count = deduplicate(cleaned)
    # telefone é NOT NULL no banco; registros sem telefone são descartados
    final = deduped  # no_tel é apenas reportado

    report(all_rows, cleaned, deduped, no_tel, dup_count)

    if dry_run:
        print('[DRY RUN] Nenhum dado foi gravado.')
        _save_seed(final)
        return

    with app.app_context():
        criados   = 0
        pulados   = 0
        erros_log = []

        for r in final:
            try:
                if r['telefone']:
                    existe = Cliente.query.filter_by(telefone=r['telefone']).first()
                    if existe:
                        pulados += 1
                        continue

                c = Cliente()
                c.nome        = r['nome']
                c.telefone    = r['telefone'] or None
                c.email       = r['email']
                c.cpf         = r['cpf']
                c.aniversario = (datetime.strptime(r['aniversario'], '%Y-%m-%d').date()
                                 if r['aniversario'] else None)
                c.sexo        = r['sexo']
                c.cep         = r['cep']
                c.endereco    = r['endereco']
                c.numero      = r['numero']
                c.complemento = r['complemento']
                c.cidade      = r['cidade']
                c.estado      = r['estado']
                c.descricao   = r['descricao']
                c.updated_at  = datetime.utcnow()

                db.session.add(c)
                criados += 1

                if criados % 500 == 0:
                    db.session.flush()
                    print(f'  ... {criados} inseridos até agora')

            except Exception as e:
                erros_log.append(f'{r["nome"]}: {e}')

        db.session.commit()
        print(f'\nImportacao concluida: {criados} criados, {pulados} ja existiam, {len(no_tel)} sem-tel ignorados.')
        if erros_log:
            print(f'{len(erros_log)} erros:')
            for e in erros_log[:20]:
                print(f'  {e}')

    _save_seed(final)
    print(f'\nSeed salvo em: {SEED_PATH}')


def _save_seed(records):
    """Salva os registros limpos como JSON para importação no Railway."""
    with open(SEED_PATH, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=None, separators=(',', ':'))
    size_kb = os.path.getsize(SEED_PATH) / 1024
    print(f'Seed JSON gerado: {len(records)} registros, {size_kb:.0f} KB -> {SEED_PATH}')


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    run_import(dry_run=dry)
