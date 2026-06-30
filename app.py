import os
from flask import Flask, render_template
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'unitto-dev-secret-2025')

_db_url = os.getenv('DATABASE_URL', 'sqlite:///unitto.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI']        = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ── DB + Auth ────────────────────────────────────────────────────────────────
from models import db, User, Setting, Empresa
from themes import get_theme_css

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin.login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ── Blueprints ───────────────────────────────────────────────────────────────
from admin import admin_bp
app.register_blueprint(admin_bp)

from saas_admin import saas_bp
app.register_blueprint(saas_bp)

from signup import signup_bp
app.register_blueprint(signup_bp)

from billing import billing_bp
app.register_blueprint(billing_bp)

from admin.tenant import register_tenant_auto_fill
register_tenant_auto_fill(app, db)

# ── Schema migrations ─────────────────────────────────────────────────────────
def _safe_add_col(table, col, defn):
    from sqlalchemy import inspect, text
    try:
        cols = {c['name'] for c in inspect(db.engine).get_columns(table)}
        if col not in cols:
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {defn}'))
    except Exception:
        pass


def _migrate_settings_schema():
    """Migra settings de chave-PK global para (id, empresa_id, key) por tenant."""
    from sqlalchemy import inspect as _insp, text
    try:
        cols = {c['name'] for c in _insp(db.engine).get_columns('settings')}
        if 'id' in cols:
            return
        _pg = 'postgresql' in db.engine.url.drivername
        with db.engine.begin() as conn:
            if _pg:
                conn.execute(text('ALTER TABLE settings RENAME TO settings_old'))
                conn.execute(text('''
                    CREATE TABLE settings (
                        id SERIAL PRIMARY KEY,
                        empresa_id INTEGER REFERENCES empresas(id),
                        key VARCHAR(50) NOT NULL,
                        value VARCHAR(200),
                        CONSTRAINT uq_setting_empresa_key UNIQUE(empresa_id, key)
                    )
                '''))
                conn.execute(text(
                    'INSERT INTO settings (key, value) SELECT key, value FROM settings_old'
                ))
                conn.execute(text('DROP TABLE settings_old'))
            else:
                conn.execute(text('''
                    CREATE TABLE settings_new (
                        id INTEGER PRIMARY KEY,
                        empresa_id INTEGER REFERENCES empresas(id),
                        key VARCHAR(50) NOT NULL,
                        value VARCHAR(200),
                        UNIQUE(empresa_id, key)
                    )
                '''))
                conn.execute(text(
                    'INSERT INTO settings_new (key, value) SELECT key, value FROM settings'
                ))
                conn.execute(text('DROP TABLE settings'))
                conn.execute(text('ALTER TABLE settings_new RENAME TO settings'))
    except Exception:
        pass


def _migrate_expedientes():
    from sqlalchemy import inspect as _insp, text
    _pg = 'postgresql' in db.engine.url.drivername
    try:
        cols = {c['name'] for c in _insp(db.engine).get_columns('expedientes')}
        if 'profissional_id' in cols:
            with db.engine.begin() as conn:
                if _pg:
                    conn.execute(text('DROP TABLE IF EXISTS expediente_dias'))
                    conn.execute(text('DROP TABLE IF EXISTS expedientes CASCADE'))
                else:
                    conn.execute(text('DROP TABLE IF EXISTS expediente_dias'))
                    conn.execute(text('DROP TABLE IF EXISTS expedientes'))
    except Exception:
        pass
    try:
        from sqlalchemy import inspect as _insp2
        cols = {c['name'] for c in _insp2(db.engine).get_columns('expediente_dias')}
        needed = {'id', 'expediente_id', 'dia_semana', 'hora_inicio', 'hora_fim'}
        if not needed.issubset(cols):
            with db.engine.begin() as conn:
                conn.execute(text('DROP TABLE IF EXISTS expediente_dias'))
    except Exception:
        pass


def _seed_empresa():
    if db.session.query(Empresa.id).first():
        emp = Empresa.query.order_by(Empresa.id).first()
        try:
            for u in User.query.filter(User.empresa_id.is_(None)).all():
                u.empresa_id = emp.id
            db.session.commit()
        except Exception:
            db.session.rollback()
        return
    emp = Empresa(
        nome='Renata Rosa Beauty Concept',
        slug='renatarosa',
        plano='pro',
        status='ativa',
    )
    db.session.add(emp)
    db.session.flush()
    for u in User.query.all():
        u.empresa_id = emp.id
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _seed_unidades():
    from models import Unidade
    if db.session.query(Unidade.id).first():
        return
    for nome, cidade, estado in [
        ('Varginha',            'Varginha',            'MG'),
        ('São José dos Campos', 'São José dos Campos', 'SP'),
    ]:
        db.session.add(Unidade(nome=nome, cidade=cidade, estado=estado, ativo=True))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _seed_servicos():
    from models import Categoria, Servico
    if db.session.query(Servico.id).first():
        return
    import csv as _csv
    import re as _re
    from decimal import Decimal

    csv_path = os.path.join(os.path.dirname(__file__), 'servicos.csv')
    if not os.path.exists(csv_path):
        return

    def _br_decimal(s):
        try:
            return Decimal(s.strip().replace('.', '').replace(',', '.'))
        except Exception:
            return Decimal('0')

    def _parse_tempo(s):
        h = _re.search(r'(\d+)h', s)
        m = _re.search(r'(\d+)min', s)
        horas   = int(h.group(1)) if h else 0
        minutos = int(m.group(1)) if m else 0
        return (horas or 1, minutos) if (horas == 0 and minutos == 0) else (horas, minutos)

    with open(csv_path, encoding='utf-8') as f:
        rows = list(_csv.DictReader(f, delimiter=';'))

    seen = {}
    for r in rows:
        key = r['Nome'].strip().lower()
        com = _br_decimal(r['Comissão'])
        if key not in seen or com > _br_decimal(seen[key]['Comissão']):
            seen[key] = r

    cat_cache = {}
    for r in seen.values():
        nome_cat = r['Categoria'].strip()
        if nome_cat not in cat_cache:
            cat = Categoria.query.filter(
                db.func.lower(Categoria.nome) == nome_cat.lower()
            ).first()
            if cat is None:
                cat = Categoria(nome=nome_cat, ativo=True)
                db.session.add(cat)
                db.session.flush()
            cat_cache[nome_cat] = cat

        preco   = _br_decimal(r['Preço'])
        com_val = _br_decimal(r['Comissão'])
        h, m    = _parse_tempo(r['Tempo'])
        svc = Servico(
            nome            = r['Nome'].strip(),
            preco           = preco if preco > 0 else None,
            duracao_horas   = h,
            duracao_minutos = m,
            comissao_valor  = com_val if com_val > 0 else None,
            comissao_tipo   = '%',
            categoria_id    = cat_cache[nome_cat].id,
            ativo           = True,
        )
        db.session.add(svc)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _seed_planos():
    from models import Plano
    from decimal import Decimal
    planos_data = [
        dict(slug='lite',  nome='Básico',       preco_mensal=Decimal('38'),  preco_anual_mensal=Decimal('38'),  max_profissionais=1,  max_wa_mes=100,  max_simultaneos=2,  tem_relatorios=False, ordem=1),
        dict(slug='plus',  nome='Essencial',     preco_mensal=Decimal('68'),  preco_anual_mensal=Decimal('68'),  max_profissionais=5,  max_wa_mes=500,  max_simultaneos=5,  tem_relatorios=True,  ordem=2),
        dict(slug='pro',   nome='Avançado',      preco_mensal=Decimal('120'), preco_anual_mensal=Decimal('120'), max_profissionais=15, max_wa_mes=2000, max_simultaneos=10, tem_relatorios=True,  ordem=3),
        dict(slug='black', nome='Profissional',  preco_mensal=Decimal('210'), preco_anual_mensal=Decimal('210'), max_profissionais=50, max_wa_mes=10000,max_simultaneos=30, tem_relatorios=True,  ordem=4),
    ]
    changed = False
    for pd in planos_data:
        p = Plano.query.filter_by(slug=pd['slug']).first()
        if p:
            for k, v in pd.items():
                if k != 'slug' and getattr(p, k) != v:
                    setattr(p, k, v)
                    changed = True
        else:
            db.session.add(Plano(**pd, ativo=True))
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _backfill_empresa_id():
    from sqlalchemy import text
    emp = Empresa.query.order_by(Empresa.id).first()
    if not emp:
        return
    tables = [
        'leads', 'categorias', 'unidades', 'expedientes', 'profissionais',
        'servicos', 'agendamentos', 'bloqueios_agenda', 'clientes', 'comandas',
        'pacotes', 'vendas_pacote', 'recebimentos_clientes', 'contas_pagar', 'contas_receber',
    ]
    try:
        with db.engine.begin() as conn:
            for t in tables:
                conn.execute(
                    text(f'UPDATE {t} SET empresa_id = :eid WHERE empresa_id IS NULL'),
                    {'eid': emp.id}
                )
    except Exception:
        pass


with app.app_context():
    _migrate_expedientes()
    _migrate_settings_schema()
    db.create_all()
    _pg = 'postgresql' in db.engine.url.drivername
    _safe_add_col('profissionais', 'obs',                 'TEXT')
    _safe_add_col('profissionais', 'perfil_acesso',       "VARCHAR(20) DEFAULT 'profissional'")
    _safe_add_col('profissionais', 'agendamento_online',
                  'BOOLEAN DEFAULT TRUE'  if _pg else 'INTEGER DEFAULT 1')
    _safe_add_col('profissionais', 'agendamentos_simult',
                  'BOOLEAN DEFAULT FALSE' if _pg else 'INTEGER DEFAULT 0')
    _safe_add_col('profissionais', 'unidade_id',
                  'INTEGER REFERENCES unidades(id)'    if _pg else 'INTEGER')
    _safe_add_col('profissionais', 'expediente_id',
                  'INTEGER REFERENCES expedientes(id)' if _pg else 'INTEGER')
    _safe_add_col('agendamentos',  'unidade_id',      'INTEGER REFERENCES unidades(id)')
    _safe_add_col('clientes',      'saldo',           'NUMERIC(10,2) DEFAULT 0')
    _safe_add_col('comandas',      'saldo_ajustado',  'NUMERIC(10,2)')
    _safe_add_col('comanda_itens', 'venda_pacote_item_id',
                  'INTEGER REFERENCES venda_pacote_itens(id)' if _pg else 'INTEGER')
    _safe_add_col('comanda_itens', 'profissional_id',
                  'INTEGER REFERENCES profissionais(id)' if _pg else 'INTEGER')
    _safe_add_col('comanda_itens', 'comissao_valor',     'NUMERIC(10,2)')
    _safe_add_col('comanda_itens', 'comissao_tipo',      "VARCHAR(1) DEFAULT '%'")
    _safe_add_col('comanda_itens', 'comissao_paga',
                  'BOOLEAN DEFAULT FALSE' if _pg else 'INTEGER DEFAULT 0')
    _safe_add_col('comanda_itens', 'comissao_data_pag',  'DATE')
    _safe_add_col('comanda_itens', 'comissao_forma_pag', 'VARCHAR(30)')
    _safe_add_col('agendamentos',  'lembrete_enviado',
                  'BOOLEAN DEFAULT FALSE' if _pg else 'INTEGER DEFAULT 0')
    _safe_add_col('users',         'is_admin',
                  'BOOLEAN DEFAULT FALSE' if _pg else 'INTEGER DEFAULT 0')
    _safe_add_col('users',         'empresa_id',
                  'INTEGER REFERENCES empresas(id)' if _pg else 'INTEGER')
    _safe_add_col('users',         'role',
                  "VARCHAR(20) DEFAULT 'empresa_admin'")
    _fk_emp = 'INTEGER REFERENCES empresas(id)' if _pg else 'INTEGER'
    _safe_add_col('leads',                'empresa_id', _fk_emp)
    _safe_add_col('categorias',           'empresa_id', _fk_emp)
    _safe_add_col('unidades',             'empresa_id', _fk_emp)
    _safe_add_col('expedientes',          'empresa_id', _fk_emp)
    _safe_add_col('profissionais',        'empresa_id', _fk_emp)
    _safe_add_col('servicos',             'empresa_id', _fk_emp)
    _safe_add_col('agendamentos',         'empresa_id', _fk_emp)
    _safe_add_col('bloqueios_agenda',     'empresa_id', _fk_emp)
    _safe_add_col('clientes',             'empresa_id', _fk_emp)
    _safe_add_col('comandas',             'empresa_id', _fk_emp)
    _safe_add_col('pacotes',              'empresa_id', _fk_emp)
    _safe_add_col('vendas_pacote',        'empresa_id', _fk_emp)
    _safe_add_col('recebimentos_clientes','empresa_id', _fk_emp)
    _safe_add_col('contas_pagar',         'empresa_id', _fk_emp)
    _safe_add_col('contas_receber',       'empresa_id', _fk_emp)
    _seed_unidades()
    _seed_empresa()
    _backfill_empresa_id()
    _seed_servicos()
    _seed_planos()
    try:
        first = User.query.order_by(User.id).first()
        if first and not first.is_admin:
            first.is_admin = True
            db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        from sqlalchemy import text as _text
        with db.engine.begin() as _conn:
            _conn.execute(_text(
                "UPDATE users SET role = 'empresa_admin' WHERE role IS NULL OR role = ''"
            ))
    except Exception:
        pass


# ── Context processor ─────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    try:
        s = Setting.query.filter_by(key='active_theme', empresa_id=None).first()
        theme_key = s.value if s else 'default'
        theme_css = get_theme_css(theme_key)
    except Exception:
        theme_css = ''
    return {'theme_css': theme_css}


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('landing.html')


@app.route('/ping')
def ping():
    return 'ok', 200


if __name__ == '__main__':
    app.run(debug=True, port=5001)
