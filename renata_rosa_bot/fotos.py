"""RN07 — recebimento opcional de fotos via WhatsApp. Baixa a mídia da Cloud
API e grava em RenataRosaFunilFoto, vinculada ao Lead. `papel` é atribuído
por ordem de chegada no ciclo atual: 1ª foto = 'atual', 2ª = 'referencia',
demais = None (extra) — até o teto MAX_FOTOS_POR_LEAD."""
from models import db, RenataRosaFunilFoto

import meta_client

MAX_FOTOS_POR_LEAD = 4
MAX_TAMANHO_BYTES = 8 * 1024 * 1024  # teto defensivo — a Cloud API não documenta um limite confiável


def _proximo_papel(quantidade_atual):
    if quantidade_atual == 0:
        return 'atual'
    if quantidade_atual == 1:
        return 'referencia'
    return None


def limite_atingido(lead):
    return RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).count() >= MAX_FOTOS_POR_LEAD


def baixar_e_salvar(empresa, lead, media_id, mime_type_sugerido, token):
    """Baixa a mídia e grava — levanta RuntimeError em qualquer falha (quem
    chama decide a mensagem de erro pro cliente). Nunca grava além do teto
    nem mídia que não seja imagem/mime inesperadamente grande."""
    quantidade_atual = RenataRosaFunilFoto.query.filter_by(lead_id=lead.id).count()
    if quantidade_atual >= MAX_FOTOS_POR_LEAD:
        return None

    dados, mime = meta_client.baixar_midia_whatsapp(media_id, token)
    if len(dados) > MAX_TAMANHO_BYTES:
        raise RuntimeError(f'Mídia maior que o limite de {MAX_TAMANHO_BYTES} bytes.')

    foto = RenataRosaFunilFoto(
        lead_id=lead.id, empresa_id=empresa.id,
        papel=_proximo_papel(quantidade_atual),
        dados=dados, mime=mime or mime_type_sugerido or 'application/octet-stream',
        media_id_whatsapp=media_id,
    )
    db.session.add(foto)
    db.session.commit()
    return foto
