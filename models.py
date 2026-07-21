from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

LEAD_STATUSES = [
    ('novo',            'Novo'),
    ('qualificado',     'Qualificado'),
    ('em_atendimento',  'Em atendimento'),
    ('convertido',      'Convertido'),
    ('perdido',         'Perdido'),
]

LEAD_SOURCES = [
    ('formulario', 'Formulário'),
    ('whatsapp',   'WhatsApp'),
    ('chat',       'Chat do Site'),
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
    ('leitura',      'Leitura',       'Visualiza apenas sua própria agenda'),
    ('pessoal',      'Pessoal',       'Gerencia seus próprios agendamentos e comissões'),
    ('profissional', 'Profissional',  'Agenda própria, comissões e acesso limitado'),
    ('atendente',    'Atendente',     'Visualiza todos os agendamentos'),
    ('recepcao',     'Recepção',      'Todos os agendamentos e financeiro limitado'),
    ('administrador','Administrador', 'Acesso completo ao sistema'),
]


class Empresa(db.Model):
    """Representa um tenant (salão/empresa) do SaaS."""
    __tablename__ = 'empresas'
    id            = db.Column(db.Integer, primary_key=True)
    nome          = db.Column(db.String(150), nullable=False)
    slug          = db.Column(db.String(80),  unique=True, nullable=False)
    plano         = db.Column(db.String(20),  default='trial')   # trial | free | basic | pro
    status        = db.Column(db.String(20),  default='ativa')   # ativa | suspensa | cancelada
    trial_ends_at = db.Column(db.Date,        nullable=True)
    telefone      = db.Column(db.String(20))
    email         = db.Column(db.String(120))
    logo_url      = db.Column(db.String(250))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_ativa(self):
        from datetime import date
        if self.status != 'ativa':
            return False
        if self.plano == 'trial' and self.trial_ends_at:
            return date.today() <= self.trial_ends_at
        return True

    @property
    def dias_trial_restantes(self):
        from datetime import date
        if self.plano == 'trial' and self.trial_ends_at:
            return max(0, (self.trial_ends_at - date.today()).days)
        return None


class Plano(db.Model):
    """Plano de assinatura disponível no SaaS."""
    __tablename__ = 'planos'
    id                  = db.Column(db.Integer, primary_key=True)
    slug                = db.Column(db.String(20), unique=True, nullable=False)  # identificador único do plano
    nome                = db.Column(db.String(50), nullable=False)
    preco_mensal        = db.Column(db.Numeric(10, 2))  # legado, não usado — ver `preco`
    preco_anual_mensal  = db.Column(db.Numeric(10, 2))  # legado, não usado — ver `preco`
    max_profissionais   = db.Column(db.Integer, default=1)
    max_wa_mes          = db.Column(db.Integer, default=0)
    max_simultaneos     = db.Column(db.Integer, default=2)
    tem_relatorios      = db.Column(db.Boolean, default=True)
    stripe_price_mensal = db.Column(db.String(100))  # legado, não usado — ver `stripe_price_id`
    stripe_price_anual  = db.Column(db.String(100))  # legado, não usado — ver `stripe_price_id`
    ordem               = db.Column(db.Integer, default=0)
    ativo               = db.Column(db.Boolean, default=True)

    tipo                = db.Column(db.String(10), default='mensal')  # mensal|anual — cada linha é um plano independente
    preco               = db.Column(db.Numeric(10, 2))  # preço da linha (mensal: cobrança cheia; anual: equivalente mensal)
    stripe_price_id     = db.Column(db.String(100))
    destaque            = db.Column(db.Boolean, default=False)  # exibido como "Mais popular"

    @property
    def preco_anual_total(self):
        from decimal import Decimal
        if self.tipo != 'anual':
            return None
        return (self.preco or Decimal('0')) * 12


class PlanoItem(db.Model):
    """Item incluso exibido na listagem de um plano (ex: 'Link com seu logo')."""
    __tablename__ = 'plano_itens'
    id       = db.Column(db.Integer, primary_key=True)
    plano_id = db.Column(db.Integer, db.ForeignKey('planos.id'), nullable=False)
    texto    = db.Column(db.String(200), nullable=False)
    ordem    = db.Column(db.Integer, default=0)

    plano = db.relationship('Plano', backref=db.backref(
        'itens', order_by='PlanoItem.ordem', cascade='all, delete-orphan'))


class Assinatura(db.Model):
    """Assinatura ativa (ou histórica) de uma empresa."""
    __tablename__ = 'assinaturas'
    id                     = db.Column(db.Integer, primary_key=True)
    empresa_id             = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    plano_id               = db.Column(db.Integer, db.ForeignKey('planos.id'), nullable=False)
    status                 = db.Column(db.String(20), default='trial')  # trial|ativa|vencida|cancelada
    periodo                = db.Column(db.String(10), default='mensal')  # mensal|anual
    provider               = db.Column(db.String(20), default='stripe')  # stripe|infinitepay
    stripe_subscription_id = db.Column(db.String(100))
    stripe_customer_id     = db.Column(db.String(100))
    proximo_vencimento     = db.Column(db.Date)
    created_at             = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at             = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    empresa                = db.relationship('Empresa', backref=db.backref('assinatura', uselist=False))
    plano                  = db.relationship('Plano')


class CobrancaInfinitePay(db.Model):
    """Cobrança avulsa gerada via Checkout Integrado da InfinitePay (assinatura nova ou renovação)."""
    __tablename__ = 'cobrancas_infinitepay'
    id              = db.Column(db.Integer, primary_key=True)
    empresa_id      = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    plano_id        = db.Column(db.Integer, db.ForeignKey('planos.id'), nullable=False)
    order_nsu       = db.Column(db.String(64), unique=True, nullable=False)
    checkout_url    = db.Column(db.Text)
    valor_centavos  = db.Column(db.Integer)
    status          = db.Column(db.String(20), default='pendente')  # pendente|paga|expirada
    invoice_slug    = db.Column(db.String(100))
    transaction_nsu = db.Column(db.String(100))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at         = db.Column(db.DateTime)
    empresa         = db.relationship('Empresa')
    plano           = db.relationship('Plano')


ROLES = [
    ('saas_admin',    'SaaS Admin'),
    ('empresa_admin', 'Administrador'),
    ('recepcionista', 'Recepcionista'),
    ('profissional',  'Profissional'),
]


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    empresa_id    = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    name          = db.Column(db.String(100), nullable=False)
    username      = db.Column(db.String(50),  unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    phone         = db.Column(db.String(20))
    password_hash = db.Column(db.String(256))
    is_active     = db.Column(db.Boolean, default=True)
    is_admin      = db.Column(db.Boolean, default=False)
    # saas_admin | empresa_admin | recepcionista | profissional
    role          = db.Column(db.String(20), default='empresa_admin')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    empresa       = db.relationship('Empresa', backref='users', foreign_keys=[empresa_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, *roles):
        return self.role in roles


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token      = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False)

    user = db.relationship('User')

    def is_valid(self):
        return not self.used and self.expires_at > datetime.utcnow()


class Lead(db.Model):
    __tablename__ = 'leads'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100))
    phone      = db.Column(db.String(20), nullable=False)
    email      = db.Column(db.String(120))
    source     = db.Column(db.String(20),  default='manual')
    service    = db.Column(db.String(50))
    message    = db.Column(db.Text)
    status     = db.Column(db.String(20),  default='novo')
    notes      = db.Column(db.Text)
    unit       = db.Column(db.String(30))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)

    def status_label(self):
        return dict(LEAD_STATUSES).get(self.status, self.status)

    def source_label(self):
        return dict(LEAD_SOURCES).get(self.source, self.source)


class Setting(db.Model):
    __tablename__ = 'settings'
    id         = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    key        = db.Column(db.String(50), nullable=False)
    value      = db.Column(db.String(200))
    __table_args__ = (
        db.UniqueConstraint('empresa_id', 'key', name='uq_setting_empresa_key'),
    )


class PageView(db.Model):
    __tablename__ = 'page_views'
    id         = db.Column(db.Integer, primary_key=True)
    ip_hash    = db.Column(db.String(16))
    referrer   = db.Column(db.String(200))
    device     = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AnamneseCapilar(db.Model):
    __tablename__ = 'anamnese_capilar'
    id                     = db.Column(db.Integer, primary_key=True)
    cliente_id             = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False, unique=True)
    tipo                   = db.Column(db.String(80))
    caracteristica         = db.Column(db.String(80))
    pigmentacao            = db.Column(db.String(80))
    tipo_cabelo            = db.Column(db.String(80))
    comprimento            = db.Column(db.String(100))
    elasticidade           = db.Column(db.String(100))
    porosidade             = db.Column(db.String(100))
    volume                 = db.Column(db.String(100))
    espessura_fio          = db.Column(db.String(100))
    resistencia            = db.Column(db.String(100))
    condicao               = db.Column(db.Text)
    obs_condicao           = db.Column(db.Text)
    patologia              = db.Column(db.Text)
    obs_patologia          = db.Column(db.Text)
    tempo_surgiu           = db.Column(db.String(100))
    toma_medicamento       = db.Column(db.String(200))
    procurou_medico        = db.Column(db.String(3))
    diagnostico            = db.Column(db.String(200))
    antecedentes_alergicos = db.Column(db.Text)
    obs_antecedentes       = db.Column(db.Text)
    tratamentos_atuais     = db.Column(db.Text)
    medicamentos_3meses    = db.Column(db.Text)
    updated_at             = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cliente                = db.relationship('Cliente', backref=db.backref('anamnese_capilar', uselist=False))


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


class Categoria(db.Model):
    __tablename__ = 'categorias'
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    descricao  = db.Column(db.String(200))
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)


class Unidade(db.Model):
    __tablename__ = 'unidades'
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    cidade     = db.Column(db.String(80))
    estado     = db.Column(db.String(2))
    telefone   = db.Column(db.String(20))
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)

    def label(self):
        if self.cidade and self.estado:
            return f'{self.nome} — {self.cidade}/{self.estado}'
        return self.nome


class Profissional(db.Model):
    __tablename__ = 'profissionais'
    id                  = db.Column(db.Integer, primary_key=True)
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
    # categoria_id mantido para compatibilidade com coluna existente no banco
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    ativo        = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id   = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    unidade      = db.relationship('Unidade',      backref='profissionais')
    expediente   = db.relationship('Expediente',   backref='profissionais_vinculados',
                                   foreign_keys=[expediente_id])
    # relação legada (coluna única) — backref renomeado para não conflitar
    _categoria_legado = db.relationship('Categoria', foreign_keys=[categoria_id],
                                        backref='profissionais_legado')
    # relação M2M — backref 'profissionais' em Categoria
    categorias   = db.relationship('Categoria', secondary='profissional_categorias',
                                   backref='profissionais')


class Servico(db.Model):
    __tablename__ = 'servicos'
    id                       = db.Column(db.Integer, primary_key=True)
    nome                     = db.Column(db.String(150), nullable=False)
    descricao                = db.Column(db.String(500))
    imagem_url               = db.Column(db.String(300))
    preco                    = db.Column(db.Numeric(10, 2))
    duracao_horas            = db.Column(db.Integer,  default=1)
    duracao_minutos          = db.Column(db.Integer,  default=0)
    comissao_valor           = db.Column(db.Numeric(10, 2))
    comissao_tipo            = db.Column(db.String(1), default='%')
    recorrencia_dias         = db.Column(db.Integer,  default=0)
    categoria_id             = db.Column(db.Integer,  db.ForeignKey('categorias.id'))
    agendamento_online       = db.Column(db.Boolean,  default=False)
    exibir_preco_online      = db.Column(db.Boolean,  default=False)
    agendamentos_simult      = db.Column(db.Boolean,  default=False)
    restricao_horario        = db.Column(db.String(20), default='sempre')
    ativo                    = db.Column(db.Boolean,  default=True)
    created_at               = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at               = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    empresa_id               = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    categoria                = db.relationship('Categoria', backref='servicos')
    profissionais_adicionais = db.relationship('Profissional', secondary=servico_profissionais,
                                               backref='servicos_adicionais')

agendamento_servicos = db.Table(
    'agendamento_servicos',
    db.Column('agendamento_id', db.Integer, db.ForeignKey('agendamentos.id'), primary_key=True),
    db.Column('servico_id',     db.Integer, db.ForeignKey('servicos.id'),     primary_key=True),
    db.Column('ordem',          db.Integer, default=0),
)


class Agendamento(db.Model):
    __tablename__ = 'agendamentos'
    id              = db.Column(db.Integer, primary_key=True)
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
    lembrete_wa      = db.Column(db.Boolean, default=False)
    lembrete_enviado = db.Column(db.Boolean, default=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id       = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)

    venda_pacote_item_id = db.Column(db.Integer, db.ForeignKey('venda_pacote_itens.id'), nullable=True)

    cliente           = db.relationship('Cliente',          backref='agendamentos')
    profissional      = db.relationship('Profissional',     backref='agendamentos')
    servico           = db.relationship('Servico',          backref='agendamentos')
    unidade           = db.relationship('Unidade',          backref='agendamentos')
    venda_pacote_item = db.relationship('VendaPacoteItem',  backref='agendamentos_sessao', foreign_keys=[venda_pacote_item_id])
    servicos_lista    = db.relationship('Servico', secondary=agendamento_servicos,
                                        backref='agendamentos_lista')

    @property
    def hora_fim(self):
        from datetime import timedelta
        dt = datetime.combine(self.data, self.hora_inicio)
        return (dt + timedelta(minutes=self.duracao_min)).time()


class BloqueioAgenda(db.Model):
    __tablename__ = 'bloqueios_agenda'
    id              = db.Column(db.Integer, primary_key=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=True)
    data_inicio     = db.Column(db.Date, nullable=False)
    hora_inicio     = db.Column(db.Time, nullable=True)
    data_fim        = db.Column(db.Date, nullable=False)
    hora_fim        = db.Column(db.Time, nullable=True)
    dia_inteiro     = db.Column(db.Boolean, default=False)
    motivo          = db.Column(db.String(200))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id      = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    profissional    = db.relationship('Profissional', backref='bloqueios')


class EscalaProfissionalUnidade(db.Model):
    __tablename__ = 'escalas_profissional_unidade'
    id              = db.Column(db.Integer, primary_key=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=False)
    unidade_id      = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    data_inicio     = db.Column(db.Date, nullable=False)
    data_fim        = db.Column(db.Date, nullable=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    profissional    = db.relationship('Profissional', backref='escalas')
    unidade         = db.relationship('Unidade', backref='escalas')


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


DIAS_SEMANA = [
    (0, 'Domingo'), (1, 'Segunda-feira'), (2, 'Terça-feira'),
    (3, 'Quarta-feira'), (4, 'Quinta-feira'), (5, 'Sexta-feira'), (6, 'Sábado'),
]

DIAS_SEMANA_ABREV = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']


class Expediente(db.Model):
    __tablename__ = 'expedientes'
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
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
    dia_semana    = db.Column(db.Integer, nullable=False)  # 0=dom..6=sáb
    hora_inicio   = db.Column(db.Time, nullable=False)
    hora_fim      = db.Column(db.Time, nullable=False)
    almoco_inicio = db.Column(db.Time)
    almoco_fim    = db.Column(db.Time)


FORMA_PAGAMENTO = [
    ('dinheiro',       'Dinheiro'),
    ('pix',            'PIX'),
    ('cartao_debito',  'Cartão de Débito'),
    ('cartao_credito', 'Cartão de Crédito'),
    ('transferencia',  'Transferência'),
    ('saldo_cliente',  'Saldo do cliente'),
]


class FormaPagamento(db.Model):
    """Configuração de taxas por forma de pagamento (código em FORMA_PAGAMENTO)."""
    __tablename__ = 'formas_pagamento'
    id                   = db.Column(db.Integer, primary_key=True)
    empresa_id           = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    codigo               = db.Column(db.String(20), nullable=False)
    observacao           = db.Column(db.String(250))
    taxa_administracao   = db.Column(db.Numeric(8, 5), default=0)
    taxa_fixa            = db.Column(db.Numeric(10, 2), default=0)
    impostos             = db.Column(db.Numeric(8, 5), default=0)
    juros_antecipacao    = db.Column(db.Numeric(8, 5), default=0)
    prazo_liberacao      = db.Column(db.Integer, default=0)
    permite_parcelamento = db.Column(db.Boolean, default=True)
    max_parcelas         = db.Column(db.Integer, default=1)
    liberacao_automatica = db.Column(db.Boolean, default=False)
    descontar_taxas      = db.Column(db.Boolean, default=False)
    controle_caixa       = db.Column(db.Boolean, default=False)
    ativo                = db.Column(db.Boolean, default=True)
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('empresa_id', 'codigo', name='uq_forma_pag_empresa_codigo'),
    )

    @property
    def nome(self):
        return dict(FORMA_PAGAMENTO).get(self.codigo, self.codigo)


class Comanda(db.Model):
    __tablename__ = 'comandas'
    id              = db.Column(db.Integer, primary_key=True)
    codigo          = db.Column(db.Integer, unique=True, nullable=False)
    data            = db.Column(db.Date, nullable=False)
    cliente_id      = db.Column(db.Integer, db.ForeignKey('clientes.id'),      nullable=True)
    nome_cliente    = db.Column(db.String(100))
    agendamento_id  = db.Column(db.Integer, db.ForeignKey('agendamentos.id'),  nullable=True, unique=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=True)
    unidade_id      = db.Column(db.Integer, db.ForeignKey('unidades.id'),      nullable=True)
    desconto        = db.Column(db.Numeric(10, 2), default=0)
    observacoes     = db.Column(db.Text)
    status          = db.Column(db.String(10), default='aberta')
    saldo_ajustado  = db.Column(db.Numeric(10, 2), nullable=True)  # valor transferido ao saldo do cliente no fechamento
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    empresa_id      = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)

    cliente      = db.relationship('Cliente',      backref='comandas')
    agendamento  = db.relationship('Agendamento',  backref=db.backref('comanda', uselist=False))
    profissional = db.relationship('Profissional', backref='comandas')
    unidade      = db.relationship('Unidade',      backref='comandas')
    itens        = db.relationship('ComandaItem',      backref='comanda', cascade='all, delete-orphan')
    pagamentos   = db.relationship('PagamentoComanda', backref='comanda', cascade='all, delete-orphan')

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
    profissional_id      = db.Column(db.Integer, db.ForeignKey('profissionais.id'), nullable=True)
    descricao            = db.Column(db.String(150), nullable=False)
    valor                = db.Column(db.Numeric(10, 2), nullable=False)
    quantidade           = db.Column(db.Integer, default=1)
    comissao_valor       = db.Column(db.Numeric(10, 2), nullable=True)
    comissao_tipo        = db.Column(db.String(1), default='%')
    comissao_paga        = db.Column(db.Boolean, default=False)
    comissao_data_pag    = db.Column(db.Date)
    comissao_forma_pag   = db.Column(db.String(30))
    venda_pacote_item_id = db.Column(db.Integer, db.ForeignKey('venda_pacote_itens.id'), nullable=True)
    servico              = db.relationship('Servico', backref='comanda_itens')
    profissional         = db.relationship('Profissional', backref='comanda_itens')

    @property
    def taxa_descontada(self):
        """Parcela da taxa das formas de pagamento (com 'Descontar Taxas' ativo) atribuída
        a este item, rateada proporcionalmente ao valor do item dentro da comanda."""
        from decimal import Decimal
        comanda = self.comanda
        if not comanda or not comanda.pagamentos:
            return Decimal('0')
        subtotal = comanda.valor_total
        if not subtotal:
            return Decimal('0')

        total_taxa = Decimal('0')
        for pag in comanda.pagamentos:
            forma_cfg = FormaPagamento.query.filter_by(
                empresa_id=comanda.empresa_id,
                codigo=pag.forma_pagamento,
                descontar_taxas=True,
            ).first()
            if not forma_cfg:
                continue
            pct = (forma_cfg.taxa_administracao or 0) + (forma_cfg.impostos or 0) + (forma_cfg.juros_antecipacao or 0)
            total_taxa += (pag.valor or 0) * pct / 100 + (forma_cfg.taxa_fixa or 0)

        if total_taxa <= 0:
            return Decimal('0')
        item_valor = (self.valor or 0) * (self.quantidade or 1)
        return total_taxa * item_valor / subtotal

    @property
    def comissao_calculada(self):
        from decimal import Decimal
        if not self.comissao_valor:
            return Decimal('0')
        if self.comissao_tipo == 'R':
            return self.comissao_valor
        base = (self.valor or 0) * (self.quantidade or 1) - self.taxa_descontada
        if base < 0:
            base = Decimal('0')
        return base * self.comissao_valor / 100


class PagamentoComanda(db.Model):
    __tablename__ = 'pagamentos_comanda'
    id              = db.Column(db.Integer, primary_key=True)
    comanda_id      = db.Column(db.Integer, db.ForeignKey('comandas.id'), nullable=False)
    forma_pagamento = db.Column(db.String(20), nullable=False)
    valor           = db.Column(db.Numeric(10, 2), nullable=False)
    parcelas        = db.Column(db.Integer, default=1)
    data_pagamento  = db.Column(db.Date)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)


class RecebimentoCliente(db.Model):
    """Quitação de saldo devedor registrada diretamente no cadastro do cliente."""
    __tablename__ = 'recebimentos_clientes'
    id              = db.Column(db.Integer, primary_key=True)
    cliente_id      = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    valor           = db.Column(db.Numeric(10, 2), nullable=False)
    forma_pagamento = db.Column(db.String(30), nullable=False)
    data            = db.Column(db.Date, nullable=False)
    observacao      = db.Column(db.String(250))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id      = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    cliente         = db.relationship('Cliente', backref='recebimentos')


class ContaPagar(db.Model):
    __tablename__ = 'contas_pagar'
    id              = db.Column(db.Integer, primary_key=True)
    descricao       = db.Column(db.String(200), nullable=False)
    valor           = db.Column(db.Numeric(10, 2), nullable=False)
    vencimento      = db.Column(db.Date, nullable=False)
    categoria       = db.Column(db.String(100))
    fornecedor      = db.Column(db.String(100))
    status          = db.Column(db.String(20), default='pendente')  # pendente, pago, cancelado
    forma_pagamento = db.Column(db.String(30))
    data_pagamento  = db.Column(db.Date)
    observacoes     = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id      = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)


class ContaReceber(db.Model):
    __tablename__ = 'contas_receber'
    id               = db.Column(db.Integer, primary_key=True)
    descricao        = db.Column(db.String(200), nullable=False)
    valor            = db.Column(db.Numeric(10, 2), nullable=False)
    vencimento       = db.Column(db.Date, nullable=False)
    cliente_id       = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    comanda_id       = db.Column(db.Integer, db.ForeignKey('comandas.id'), nullable=True)
    status           = db.Column(db.String(20), default='pendente')  # pendente, recebido, cancelado
    forma_pagamento  = db.Column(db.String(30))
    data_recebimento = db.Column(db.Date)
    observacoes      = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id       = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    cliente          = db.relationship('Cliente', backref='contas_receber')
    comanda          = db.relationship('Comanda', backref='contas_receber', foreign_keys=[comanda_id])


class AnamneseCorporal(db.Model):
    __tablename__ = 'anamnese_corporal'
    id                            = db.Column(db.Integer, primary_key=True)
    cliente_id                    = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False, unique=True)
    motivo_visita                 = db.Column(db.String(200))
    tratamentos_anteriores        = db.Column(db.String(3))
    quais_tratamentos_anteriores  = db.Column(db.Text)
    resultados_tratamentos        = db.Column(db.Text)
    antecedentes_pessoais         = db.Column(db.Text)
    antecedentes_familiares       = db.Column(db.Text)
    antecedentes_alergicos        = db.Column(db.String(3))
    quais_antecedentes_alergicos  = db.Column(db.Text)
    antecedentes_cirurgicos       = db.Column(db.String(3))
    quais_antecedentes_cirurgicos = db.Column(db.Text)
    atividade_fisica              = db.Column(db.String(3))
    frequencia_atividade          = db.Column(db.String(100))
    horas_sono                    = db.Column(db.String(50))
    toma_alcool                   = db.Column(db.String(50))
    fuma                          = db.Column(db.String(3))
    preenchimento                 = db.Column(db.String(3))
    toma_sol                      = db.Column(db.String(50))
    roupas_apertadas              = db.Column(db.String(3))
    tipo_alimentacao              = db.Column(db.Text)
    muito_apetite                 = db.Column(db.String(3))
    intestino_preso               = db.Column(db.String(3))
    consumo_agua                  = db.Column(db.String(50))
    urina                         = db.Column(db.String(50))
    posicao_dia                   = db.Column(db.String(100))
    usa_diu                       = db.Column(db.String(3))
    gravidez                      = db.Column(db.String(3))
    menopausa                     = db.Column(db.String(3))
    num_gestacoes                 = db.Column(db.String(50))
    menstruacao_regular           = db.Column(db.String(3))
    uso_medicamentos              = db.Column(db.String(3))
    quais_remedios                = db.Column(db.String(200))
    updated_at                    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cliente                       = db.relationship('Cliente', backref=db.backref('anamnese_corporal', uselist=False))


class Cliente(db.Model):
    __tablename__ = 'clientes'
    id               = db.Column(db.Integer, primary_key=True)
    nome             = db.Column(db.String(100), nullable=False)
    telefone         = db.Column(db.String(20),  nullable=False)
    email            = db.Column(db.String(120))
    cpf              = db.Column(db.String(14))
    aniversario      = db.Column(db.Date)
    sexo             = db.Column(db.String(10))
    bloqueado        = db.Column(db.Boolean, default=False)
    saldo            = db.Column(db.Numeric(10, 2), default=0)  # >0 crédito, <0 dívida
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
    empresa_id       = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)


# ── Pacotes ───────────────────────────────────────────────────────────────────

class Pacote(db.Model):
    __tablename__ = 'pacotes'
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(150), nullable=False)
    descricao  = db.Column(db.String(500))
    ativo      = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
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
    pacote_id    = db.Column(db.Integer, db.ForeignKey('pacotes.id'), nullable=True)
    cliente_id   = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    nome_cliente = db.Column(db.String(100))
    comanda_id   = db.Column(db.Integer, db.ForeignKey('comandas.id'), nullable=True)
    data_venda   = db.Column(db.Date, nullable=False)
    nome_pacote  = db.Column(db.String(150))
    valor_total  = db.Column(db.Numeric(10, 2), nullable=False)
    status       = db.Column(db.String(20), default='ativo')  # ativo, concluido, cancelado
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    empresa_id   = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
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
