"""Menu configurável do atendimento por IA — get-or-create + edição validada.

`intent` é sempre a chave interna fixa (INTENTS_MENU_IA); só `label`/`ordem`/
`ativo` podem vir de input do tenant."""
from models import db, INTENTS_MENU_IA, AtendimentoIAMenuConfig, AtendimentoIAMenuOpcao

_INTENTS_VALIDOS = {chave for chave, _ in INTENTS_MENU_IA}
_LABELS_DEFAULT = dict(INTENTS_MENU_IA)


def get_or_create_menu_config(empresa) -> AtendimentoIAMenuConfig:
    cfg = AtendimentoIAMenuConfig.query.filter_by(empresa_id=empresa.id).first()
    if cfg:
        return cfg
    cfg = AtendimentoIAMenuConfig(empresa_id=empresa.id)
    db.session.add(cfg)
    db.session.flush()
    for i, (intent, label) in enumerate(INTENTS_MENU_IA):
        db.session.add(AtendimentoIAMenuOpcao(
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


def menu_texto(empresa) -> str:
    """Texto do menu numerado enviado ao cliente."""
    cfg = get_or_create_menu_config(empresa)
    opcoes = opcoes_ativas(empresa)
    linhas = [cfg.titulo or 'Olá! 👋 Como posso ajudar?', '']
    for i, opcao in enumerate(opcoes, start=1):
        linhas.append(f'{i}️⃣ {opcao.label}')
    return '\n'.join(linhas)
