"""Menu principal configurável do funil da Renata Rosa — get-or-create +
edição validada. Mesmo padrão de ai_attendance/menu.py (motor genérico),
tabela própria pra manter o isolamento.

`intent` é sempre a chave interna fixa (INTENTS_MENU_RR); só `label`/
`ordem`/`ativo` e o texto de boas-vindas (`titulo`) podem vir de input do
tenant. `titulo` funciona como o "complemento" da saudação dinâmica (ver
menu_texto) — quando o tenant customiza, esse texto é usado todo turno, só
com a saudação (hora do dia + nome, se houver) na frente."""
import random

from models import db, INTENTS_MENU_RR, RenataRosaMenuConfig, RenataRosaMenuOpcao

from . import mensagens

_INTENTS_VALIDOS = {chave for chave, _ in INTENTS_MENU_RR}


def get_or_create_menu_config(empresa) -> RenataRosaMenuConfig:
    cfg = RenataRosaMenuConfig.query.filter_by(empresa_id=empresa.id).first()
    if cfg:
        return cfg
    cfg = RenataRosaMenuConfig(empresa_id=empresa.id, titulo=mensagens.MENU_INTRO_PADRAO)
    db.session.add(cfg)
    db.session.flush()
    for i, (intent, label) in enumerate(INTENTS_MENU_RR):
        db.session.add(RenataRosaMenuOpcao(
            menu_config_id=cfg.id, intent=intent, label=label, ordem=i, ativo=True))
    db.session.commit()
    return cfg


def opcoes_ativas(empresa):
    """Lista as opções ativas do menu, na ordem configurada."""
    cfg = get_or_create_menu_config(empresa)
    return [o for o in sorted(cfg.opcoes, key=lambda o: o.ordem) if o.ativo]


def atualizar_opcoes(empresa, form):
    """Aplica edições vindas do form admin. `form` é um MultiDict do Flask
    (request.form). Só aceita `intent` que já exista na config — nunca cria/
    renomeia a chave interna a partir de input."""
    cfg = get_or_create_menu_config(empresa)
    titulo = (form.get('titulo') or '').strip()
    if titulo:
        cfg.titulo = titulo
    for opcao in cfg.opcoes:
        if opcao.intent not in _INTENTS_VALIDOS:
            continue  # defensivo — nunca deveria acontecer
        label = (form.get(f'label_{opcao.intent}') or '').strip()
        if label:
            opcao.label = label
        ordem_raw = form.get(f'ordem_{opcao.intent}', '').strip()
        if ordem_raw.isdigit():
            opcao.ordem = int(ordem_raw)
        opcao.ativo = f'ativo_{opcao.intent}' in form
    db.session.commit()


def menu_texto(empresa, lead=None) -> str:
    """Texto do menu numerado enviado ao cliente. Sempre começa com a
    saudação dinâmica (Bom dia/Boa tarde/Boa noite, com o nome quando o
    WhatsApp informar um — ver mensagens.saudacao_dinamica). O complemento é
    o texto customizado pelo tenant (`cfg.titulo`, se diferente do padrão)
    ou, por padrão, varia a cada chamada em vez de repetir sempre o mesmo
    parágrafo fixo (pedido do usuário)."""
    cfg = get_or_create_menu_config(empresa)
    opcoes = opcoes_ativas(empresa)
    saudacao = mensagens.saudacao_dinamica(lead)
    if cfg.titulo and cfg.titulo != mensagens.MENU_INTRO_PADRAO:
        complemento = cfg.titulo
    else:
        complemento = random.choice(mensagens.MENU_COMPLEMENTOS_PADRAO)
    linhas = [f'{saudacao}\n\n{complemento}', '']
    for i, opcao in enumerate(opcoes, start=1):
        linhas.append(f'{i}. {opcao.label}')
    return '\n'.join(linhas)
