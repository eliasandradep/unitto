"""Ponto único de checagem de elegibilidade do funil bespoke da Renata Rosa."""

RENATA_ROSA_SLUG = 'renatarosa'


def funil_ativo(empresa) -> bool:
    """True somente para o tenant Renata Rosa, ativo, com o toggle ligado.

    O check de slug é redundante com o toggle de propósito: este módulo é
    100% hardcoded pra esse negócio (textos, preços, perguntas) — mesmo que
    `funil_qualificacao_rr_ativo` seja ligado por engano em outro tenant
    (migração, cópia de dados, erro no admin), o funil nunca roda fora da
    Renata Rosa."""
    return (bool(empresa) and empresa.slug == RENATA_ROSA_SLUG
            and empresa.is_ativa()
            and bool(getattr(empresa, 'funil_qualificacao_rr_ativo', False)))
