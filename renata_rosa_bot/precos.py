"""RN05 — referência de investimento. O valor em R$ nunca é hardcoded: sempre
lido de Servico.preco em tempo real (se a salonista mudar o preço no catálogo,
a próxima resposta do bot já reflete). Só a regra de qual Servico corresponde
a qual opção do menu RN02 é hardcoded, por palavra-chave."""
import re

from models import Servico

_SERVICO_KEYWORDS = {
    1: ['mecha', 'loiro'],             # Loiro com mechas
    2: ['iluminad', 'morena'],         # Morena iluminada
    3: ['retoque'],                    # Retoque de mechas
    4: ['corre', 'coloraç', 'coloraca', 'mudan'],  # Mudança ou correção de cor
}


def buscar_servico(empresa, servico_opcao_idx):
    """Retorna o primeiro Servico ativo da empresa cujo nome contenha alguma
    palavra-chave da opção escolhida em RN02, ou None (opção 5/sem catálogo
    compatível — nunca inventa um serviço)."""
    keywords = _SERVICO_KEYWORDS.get(servico_opcao_idx)
    if not keywords:
        return None
    servicos = Servico.query.filter_by(empresa_id=empresa.id, ativo=True).all()
    for servico in servicos:
        nome_lower = (servico.nome or '').lower()
        if any(re.search(kw, nome_lower) for kw in keywords):
            return servico
    return None


def texto_investimento(empresa, servico_opcao_idx):
    servico = buscar_servico(empresa, servico_opcao_idx)
    if servico and servico.preco:
        valor = f'{servico.preco:.2f}'.replace('.', ',')
        return (f'Para você ter uma ideia, nossos serviços de {servico.nome} '
                f'possuem valores a partir de R$ {valor}.')
    return 'O valor exato depende de uma avaliação presencial com a nossa especialista.'
