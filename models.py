from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

LEAD_STATUSES = [
    ('novo',           'Novo'),
    ('qualificado',    'Qualificado'),
    ('em_atendimento', 'Em atendimento'),
    ('convertido',     'Convertido'),
    ('perdido',        'Perdido'),
]

LEAD_SOURCES = [
    ('formulario', 'Formulário'),
    ('whatsapp',   'WhatsApp'),
    ('manual',     'Manual'),
]

AGENDAMENTO_STATUS = [
    ('agendado',   'Agendado'),
    ('confirmado', 'Confirmado'),
    ('concluido',  'Concluído'),
    ('cancelado',  'Cancelado'),
    ('faltou',     'Faltou'),
]

PERFIL_ACESSO = [
    ('leitura',       'Leitura',       'Visualiza apenas sua própria agenda'),
    ('pessoal',       'Pessoal',       'Gerencia seus próprios agendamentos e comissões'),
    ('profissional',  'Profissional',  'Agenda própria, comissões e acesso limitado'),
    ('atendente',     'Atendente',     'Visualiza todos os agendamentos'),
    ('recepcao',      'Recepção',      'Todos os agendamentos e financeiro limitado'),
    ('administrador', 'Administrador', 'Acesso completo ao sistema'),
]

FORMA_PAGAMENTO = [
    ('dinheiro',       'Dinheiro'),
    ('pix',            'PIX'),
    ('cartao_debito',  'Cartão de Débito'),
    ('cartao_credito', 'Cartão de Crédito'),
    ('transferencia',  'Transferência'),
    ('saldo_cliente',  'Saldo do cliente'),
]

DIAS_SEMANA = [
    (0, 'Domingo'), (1, 'Segunda-feira'), (2, 'Terça-feira'),
    (3, 'Quarta-feira'), (4, 'Quinta-feira'), (5, 'Sexta-feira'), (6, 'Sábado'),
]

DIAS_SEMANA_ABREV = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']

AI_PROVIDERS = [
    ('anthropic', 'Anthropic (Claude)'),
    ('openai',    'OpenAI (GPT)'),
    ('google',    'Google (Gemini)'),
]


# ── Studio (tenant) ──────────────────────────────────────────────────────────

class Studio(db.Model):
    __tablename__ = 'studios'
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(150), nullable=False)
    slug       = db.Column(db.String(80), unique=True, nullable=False)
    plano      = db.Column(db.String(20), default='trial')  # trial, basic, pro
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    configs    = db.relationship('StudioConfig', backref='studio',
                                  cascade='all, delete-orphan')

    def get_config(self, key, default=None):
        for c in self.configs:
            if c.key == key:
                return c.value
        return default

    def set_config(self, key, value):
        for c in self.configs:
            if c.key == key:
                c.value = value
                return
        self.configs.append(StudioConfig(studio_id=self.id, key=key, value=value))


class StudioConfig(db.Model):
    __tablename__ = 'studio_configs'
    id        = db.Column(db.Integer, primary_key=True)
    studio_id = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    key       = db.Column(db.String(50), nullable=False)
    value     = db.Column(db.Text)
    __table_args__ = (db.UniqueConstraint('studio_id', 'key', name='uq_studio_config'),)


# ── Usuários ─────────────────────────────────────────────────────────────────

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    studio_id     = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    username      = db.Column(db.String(50),  nullable=False)
    email         = db.Column(db.String(120), nullable=False)
    phone         = db.Column(db.String(20))
    password_hash = db.Column(db.String(256))
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    studio        = db.relationship('Studio', backref='users')

    __table_args__ = (
        db.UniqueConstraint('studio_id', 'username', name='uq_user_studio_username'),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# ── Leads ─────────────────────────────────────────────────────────────────────

class Lead(db.Model):
    __tablename__ = 'leads'
    id         = db.Column(db.Integer, primary_key=True)
    studio_id  = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    name       = db.Column(db.String(100))
    phone      = db.Column(db.String(20), nullable=False)
    email      = db.Column(db.String(120))
    source     = db.Column(db.String(20), default='manual')
    service    = db.Column(db.String(50))
    message    = db.Column(db.Text)
    status     = db.Column(db.String(20), default='novo')
    notes      = db.Column(db.Text)
    unit       = db.Column(db.String(30))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def status_label(self):
        return dict(LEAD_STATUSES).get(self.status, self.status)

    def source_label(self):
        return dict(LEAD_SOURCES).get(self.source, self.source)


# ── Unidades ──────────────────────────────────────────────────────────────────

class Unidade(db.Model):
    __tablename__ = 'unidades'
    id         = db.Column(db.Integer, primary_key=True)
    studio_id  = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome       = db.Column(db.String(100), nullable=False)
    cidade     = db.Column(db.String(80))
    estado     = db.Column(db.String(2))
    telefone   = db.Column(db.String(20))
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def label(self):
        if self.cidade and self.estado:
            return f'{self.nome} — {self.cidade}/{self.estado}'
        return self.nome


# ── Serviços e Categorias ─────────────────────────────────────────────────────

class Categoria(db.Model):
    __tablename__ = 'categorias'
    id         = db.Column(db.Integer, primary_key=True)
    studio_id  = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome       = db.Column(db.String(100), nullable=False)
    descricao  = db.Column(db.String(200))
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


servico_profissionais = db.Table(
    'servico_profissionais',
    db.Column('servico_id',      db.Integer, db.ForeignKey('servicos.id'),      primary_key=True),
    db.Column('profissional_id', db.Integer, db.ForeignKey('profissionais.id'), primary_key=True),
)

profissional_categorias = db.Table(
    'profissional_categorias',
    db.Column('profissional_id', db.Integer, db.ForeignKey('profissionais.id'), primary_key=True),
    db.Column('categoria_id',    db.Integer, db.ForeignKey('categorias.id'),    primary_key=True),
)


class Servico(db.Model):
    __tablename__ = 'servicos'
    id                  = db.Column(db.Integer, primary_key=True)
    studio_id           = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome                = db.Column(db.String(150), nullable=False)
    descricao           = db.Column(db.String(500))
    preco               = db.Column(db.Numeric(10, 2))
    duracao_horas       = db.Column(db.Integer, default=1)
    duracao_minutos     = db.Column(db.Integer, default=0)
    comissao_valor      = db.Column(db.Numeric(10, 2))
    comissao_tipo       = db.Column(db.String(1), default='%')
    recorrencia_dias    = db.Column(db.Integer, default=0)
    categoria_id        = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    agendamento_online  = db.Column(db.Boolean, default=False)
    exibir_preco_online = db.Column(db.Boolean, default=False)
    agendamentos_simult = db.Column(db.Boolean, default=False)
    restricao_horario   = db.Column(db.String(20), default='sempre')
    ativo               = db.Column(db.Boolean, default=True)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    categoria           = db.relationship('Categoria', backref='servicos')
    profissionais_adicionais = db.relationship('Profissional', secondary=servico_profissionais,
                                               backref='servicos_adicionais')


# ── Expedientes ───────────────────────────────────────────────────────────────

class Expediente(db.Model):
    __tablename__ = 'expedientes'
    id         = db.Column(db.Integer, primary_key=True)
    studio_id  = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome       = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dias       = db.relationship('ExpedienteDia', backref='expediente',
                                  cascade='all, delete-orphan')

    @property
    def dias_ativos(self):
        return sorted(self.dias, key=lambda d: d.dia_semana)


class ExpedienteDia(db.Model):
    __tablename__ = 'expediente_dias'
    __table_args__ = (db.UniqueConstraint('expediente_id', 'dia_semana', name='uq_expdia'),)
    id            = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=False)
    dia_semana    = db.Column(db.Integer, nullable=False)
    hora_inicio   = db.Column(db.Time, nullable=False)
    hora_fim      = db.Column(db.Time, nullable=False)
    almoco_inicio = db.Column(db.Time)
    almoco_fim    = db.Column(db.Time)


# ── Profissionais ─────────────────────────────────────────────────────────────

class Profissional(db.Model):
    __tablename__ = 'profissionais'
    id                  = db.Column(db.Integer, primary_key=True)
    studio_id           = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome                = db.Column(db.String(100), nullable=False)
    email               = db.Column(db.String(120))
    telefone            = db.Column(db.String(20))
    cargo               = db.Column(db.String(80))
    obs                 = db.Column(db.Text)
    perfil_acesso       = db.Column(db.String(20), default='profissional')
    agendamento_online  = db.Column(db.Boolean, default=True)
    agendamentos_simult = db.Column(db.Boolean, default=False)
    unidade_id          = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=True)
    expediente_id       = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=True)
    categoria_id        = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    ativo               = db.Column(db.Boolean, default=True)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    unidade             = db.relationship('Unidade', backref='profissionais')
    expediente          = db.relationship('Expediente', backref='profissionais_vinculados',
                                          foreign_keys=[expediente_id])
    _categoria_legado   = db.relationship('Categoria', foreign_keys=[categoria_id],
                                          backref='profissionais_legado')
    categorias          = db.relationship('Categoria', secondary='profissional_categorias',
                                          backref='profissionais')


class ComissaoProfissional(db.Model):
    __tablename__ = 'comissoes_profissionais'
    id              = db.Column(db.Integer, primary_key=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=False)
    servico_id      = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=False)
    comissao_valor  = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    comissao_tipo   = db.Column(db.String(1), default='%')
    profissional    = db.relationship('Profissional', backref='comissoes_custom')
    servico         = db.relationship('Servico', backref='comissoes_prof')
    __table_args__  = (
        db.UniqueConstraint('profissional_id', 'servico_id', name='uq_com_prof_svc'),
    )


# ── Clientes ──────────────────────────────────────────────────────────────────

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id               = db.Column(db.Integer, primary_key=True)
    studio_id        = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome             = db.Column(db.String(100), nullable=False)
    telefone         = db.Column(db.String(20),  nullable=False)
    email            = db.Column(db.String(120))
    cpf              = db.Column(db.String(14))
    aniversario      = db.Column(db.Date)
    sexo             = db.Column(db.String(10))
    bloqueado        = db.Column(db.Boolean, default=False)
    saldo            = db.Column(db.Numeric(10, 2), default=0)
    cep              = db.Column(db.String(9))
    endereco         = db.Column(db.String(150))
    numero           = db.Column(db.String(10))
    complemento      = db.Column(db.String(80))
    bairro           = db.Column(db.String(80))
    cidade           = db.Column(db.String(80))
    estado           = db.Column(db.String(2))
    descricao        = db.Column(db.Text)
    telefone_fixo    = db.Column(db.String(20))
    telefone_celular = db.Column(db.String(20))
    como_conheceu    = db.Column(db.String(150))
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Agenda ────────────────────────────────────────────────────────────────────

class Agendamento(db.Model):
    __tablename__ = 'agendamentos'
    id              = db.Column(db.Integer, primary_key=True)
    studio_id       = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome_cliente    = db.Column(db.String(100), nullable=False)
    telefone        = db.Column(db.String(20))
    cliente_id      = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=False)
    servico_id      = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=True)
    unidade_id      = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=True)
    data            = db.Column(db.Date, nullable=False)
    hora_inicio     = db.Column(db.Time, nullable=False)
    duracao_min     = db.Column(db.Integer, default=60)
    status          = db.Column(db.String(20), default='agendado')
    observacoes     = db.Column(db.Text)
    como_conheceu   = db.Column(db.String(100))
    lembrete_wa     = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    cliente      = db.relationship('Cliente',      backref='agendamentos')
    profissional = db.relationship('Profissional', backref='agendamentos')
    servico      = db.relationship('Servico',      backref='agendamentos')
    unidade      = db.relationship('Unidade',      backref='agendamentos')

    @property
    def hora_fim(self):
        from datetime import timedelta
        dt = datetime.combine(self.data, self.hora_inicio)
        return (dt + timedelta(minutes=self.duracao_min)).time()


class BloqueioAgenda(db.Model):
    __tablename__ = 'bloqueios_agenda'
    id              = db.Column(db.Integer, primary_key=True)
    studio_id       = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=True)
    data_inicio     = db.Column(db.Date, nullable=False)
    hora_inicio     = db.Column(db.Time, nullable=True)
    data_fim        = db.Column(db.Date, nullable=False)
    hora_fim        = db.Column(db.Time, nullable=True)
    dia_inteiro     = db.Column(db.Boolean, default=False)
    motivo          = db.Column(db.String(200))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    profissional    = db.relationship('Profissional', backref='bloqueios')


# ── Financeiro ────────────────────────────────────────────────────────────────

class Comanda(db.Model):
    __tablename__ = 'comandas'
    id              = db.Column(db.Integer, primary_key=True)
    studio_id       = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    codigo          = db.Column(db.Integer, nullable=False)
    data            = db.Column(db.Date, nullable=False)
    cliente_id      = db.Column(db.Integer, db.ForeignKey('clientes.id'),      nullable=True)
    nome_cliente    = db.Column(db.String(100))
    agendamento_id  = db.Column(db.Integer, db.ForeignKey('agendamentos.id'),  nullable=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=True)
    unidade_id      = db.Column(db.Integer, db.ForeignKey('unidades.id'),      nullable=True)
    desconto        = db.Column(db.Numeric(10, 2), default=0)
    observacoes     = db.Column(db.Text)
    status          = db.Column(db.String(10), default='aberta')
    saldo_ajustado  = db.Column(db.Numeric(10, 2), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cliente      = db.relationship('Cliente',      backref='comandas')
    agendamento  = db.relationship('Agendamento',  backref=db.backref('comanda', uselist=False))
    profissional = db.relationship('Profissional', backref='comandas')
    unidade      = db.relationship('Unidade',      backref='comandas')
    itens        = db.relationship('ComandaItem',      backref='comanda', cascade='all, delete-orphan')
    pagamentos   = db.relationship('PagamentoComanda', backref='comanda', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('studio_id', 'codigo', name='uq_comanda_studio_codigo'),
    )

    @property
    def valor_total(self):
        from decimal import Decimal
        return sum((i.valor or 0) * (i.quantidade or 1) for i in self.itens) or Decimal('0')

    @property
    def valor_pago(self):
        from decimal import Decimal
        return sum(p.valor or 0 for p in self.pagamentos) or Decimal('0')

    @property
    def saldo(self):
        return self.valor_total - (self.desconto or 0) - self.valor_pago


class ComandaItem(db.Model):
    __tablename__ = 'comanda_itens'
    id                   = db.Column(db.Integer, primary_key=True)
    comanda_id           = db.Column(db.Integer, db.ForeignKey('comandas.id'), nullable=False)
    servico_id           = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=True)
    descricao            = db.Column(db.String(150), nullable=False)
    valor                = db.Column(db.Numeric(10, 2), nullable=False)
    quantidade           = db.Column(db.Integer, default=1)
    venda_pacote_item_id = db.Column(db.Integer, db.ForeignKey('venda_pacote_itens.id'), nullable=True)
    servico              = db.relationship('Servico', backref='comanda_itens')


class PagamentoComanda(db.Model):
    __tablename__ = 'pagamentos_comanda'
    id              = db.Column(db.Integer, primary_key=True)
    comanda_id      = db.Column(db.Integer, db.ForeignKey('comandas.id'), nullable=False)
    forma_pagamento = db.Column(db.String(20), nullable=False)
    valor           = db.Column(db.Numeric(10, 2), nullable=False)
    parcelas        = db.Column(db.Integer, default=1)
    data_pagamento  = db.Column(db.Date)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)


# ── Pacotes ───────────────────────────────────────────────────────────────────

class Pacote(db.Model):
    __tablename__ = 'pacotes'
    id         = db.Column(db.Integer, primary_key=True)
    studio_id  = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    nome       = db.Column(db.String(150), nullable=False)
    descricao  = db.Column(db.String(500))
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    itens      = db.relationship('PacoteItem', backref='pacote', cascade='all, delete-orphan')

    @property
    def valor_total(self):
        from decimal import Decimal
        return sum((i.valor_unitario or Decimal('0')) * (i.quantidade or 1) for i in self.itens) or Decimal('0')


class PacoteItem(db.Model):
    __tablename__ = 'pacote_itens'
    id             = db.Column(db.Integer, primary_key=True)
    pacote_id      = db.Column(db.Integer, db.ForeignKey('pacotes.id'), nullable=False)
    servico_id     = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=False)
    quantidade     = db.Column(db.Integer, default=1, nullable=False)
    valor_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    servico        = db.relationship('Servico', backref='pacote_itens')


class VendaPacote(db.Model):
    __tablename__ = 'vendas_pacote'
    id           = db.Column(db.Integer, primary_key=True)
    studio_id    = db.Column(db.Integer, db.ForeignKey('studios.id'), nullable=False)
    pacote_id    = db.Column(db.Integer, db.ForeignKey('pacotes.id'), nullable=True)
    cliente_id   = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    nome_cliente = db.Column(db.String(100))
    comanda_id   = db.Column(db.Integer, db.ForeignKey('comandas.id'), nullable=True)
    data_venda   = db.Column(db.Date, nullable=False)
    nome_pacote  = db.Column(db.String(150))
    valor_total  = db.Column(db.Numeric(10, 2), nullable=False)
    status       = db.Column(db.String(20), default='ativo')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    pacote       = db.relationship('Pacote', backref='vendas')
    cliente      = db.relationship('Cliente', backref='vendas_pacote')
    comanda      = db.relationship('Comanda', backref=db.backref('venda_pacote', uselist=False),
                                   foreign_keys=[comanda_id])
    itens        = db.relationship('VendaPacoteItem', backref='venda', cascade='all, delete-orphan')

    @property
    def sessoes_total(self):
        return sum(i.quantidade_total for i in self.itens)

    @property
    def sessoes_usadas(self):
        return sum(i.quantidade_usada for i in self.itens)

    @property
    def sessoes_restantes(self):
        return self.sessoes_total - self.sessoes_usadas


class VendaPacoteItem(db.Model):
    __tablename__ = 'venda_pacote_itens'
    id               = db.Column(db.Integer, primary_key=True)
    venda_pacote_id  = db.Column(db.Integer, db.ForeignKey('vendas_pacote.id'), nullable=False)
    pacote_item_id   = db.Column(db.Integer, db.ForeignKey('pacote_itens.id'), nullable=True)
    servico_id       = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=True)
    descricao        = db.Column(db.String(150), nullable=False)
    quantidade_total = db.Column(db.Integer, default=1, nullable=False)
    quantidade_usada = db.Column(db.Integer, default=0, nullable=False)
    servico          = db.relationship('Servico', backref='venda_pacote_itens')
    pacote_item      = db.relationship('PacoteItem', backref='venda_itens')
    comanda_usos     = db.relationship('ComandaItem', backref='venda_pacote_item',
                                       foreign_keys='ComandaItem.venda_pacote_item_id')

    @property
    def quantidade_restante(self):
        return self.quantidade_total - self.quantidade_usada
