"""Informações do estabelecimento (endereço, horário, pagamento) — intent
INFORMATION. Textos livres cadastrados pelo tenant; nunca inventados pela IA."""
from models import db, InformacaoEstabelecimento


def get_or_create_info(empresa) -> InformacaoEstabelecimento:
    info = InformacaoEstabelecimento.query.filter_by(empresa_id=empresa.id).first()
    if info:
        return info
    info = InformacaoEstabelecimento(empresa_id=empresa.id)
    db.session.add(info)
    db.session.commit()
    return info


def atualizar_info(empresa, form):
    info = get_or_create_info(empresa)
    info.endereco               = (form.get('endereco') or '').strip() or None
    info.cidade                 = (form.get('cidade') or '').strip() or None
    info.estado                 = (form.get('estado') or '').strip()[:2].upper() or None
    info.cep                    = (form.get('cep') or '').strip() or None
    info.horario_funcionamento  = (form.get('horario_funcionamento') or '').strip() or None
    info.formas_pagamento_texto = (form.get('formas_pagamento_texto') or '').strip() or None
    info.observacoes            = (form.get('observacoes') or '').strip() or None
    db.session.commit()


def texto_informacoes(empresa) -> str:
    """Monta o texto de resposta do intent INFORMATION a partir de dados reais
    cadastrados. Nunca inclui nada que não esteja no cadastro."""
    info = InformacaoEstabelecimento.query.filter_by(empresa_id=empresa.id).first()
    if not info or not any([info.endereco, info.horario_funcionamento,
                             info.formas_pagamento_texto, info.observacoes]):
        return ('Ainda não tenho essas informações cadastradas por aqui. '
                'Posso te transferir para um atendente, se preferir.')

    partes = []
    if info.endereco:
        cidade_uf = ', '.join(x for x in [info.cidade, info.estado] if x)
        partes.append(f'📍 {info.endereco}' + (f' — {cidade_uf}' if cidade_uf else ''))
    if info.horario_funcionamento:
        partes.append(f'🕒 Horário de funcionamento:\n{info.horario_funcionamento}')
    if info.formas_pagamento_texto:
        partes.append(f'💳 Formas de pagamento: {info.formas_pagamento_texto}')
    if info.observacoes:
        partes.append(info.observacoes)
    return '\n\n'.join(partes)
