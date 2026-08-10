"""Sincroniza gasto/impressões/cliques por anúncio a partir da Marketing API.
Chamado pelo job agendado (app.py) e pelo botão 'Sincronizar agora' (admin/routes.py).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from models import db, AnuncioMeta, InsightDiarioAnuncio
import meta_client
from crypto_utils import decrypt_token

JANELA_DIAS = 30  # cobre atraso de atribuição da Meta e permite sincronizar 1x/dia sem lacunas


def sincronizar_conta_ads(integ_ads):
    """Retorna a quantidade de linhas de insight recebidas da API nesta sincronização
    (não a quantidade de anúncios/dias distintos) — usado pra diagnóstico na UI, já que
    uma sincronização 'bem-sucedida' com 0 linhas costuma indicar problema do lado da
    Meta (permissão, access tier, conta sem gasto no período), não um bug local."""
    token = decrypt_token(integ_ads.access_token_enc)
    hoje = date.today()
    linhas = meta_client.buscar_insights_diarios(
        integ_ads.ad_account_id, token, hoje - timedelta(days=JANELA_DIAS), hoje)

    for linha in linhas:
        ad_id = linha.get('ad_id')
        if not ad_id:
            continue
        anuncio = AnuncioMeta.query.filter_by(empresa_id=integ_ads.empresa_id, ad_id=ad_id).first()
        if not anuncio:
            anuncio = AnuncioMeta(empresa_id=integ_ads.empresa_id, ad_id=ad_id)
            db.session.add(anuncio)
        anuncio.nome          = linha.get('ad_name') or anuncio.nome
        anuncio.campanha_id   = linha.get('campaign_id') or anuncio.campanha_id
        anuncio.campanha_nome = linha.get('campaign_name') or anuncio.campanha_nome
        anuncio.atualizado_em = datetime.utcnow()
        db.session.flush()  # garante anuncio.id pro insight abaixo

        dia = datetime.strptime(linha['date_start'], '%Y-%m-%d').date()
        insight = InsightDiarioAnuncio.query.filter_by(anuncio_id=anuncio.id, data=dia).first()
        if not insight:
            insight = InsightDiarioAnuncio(anuncio_id=anuncio.id, data=dia)
            db.session.add(insight)
        insight.gasto      = Decimal(linha.get('spend') or '0')
        insight.impressoes = int(linha.get('impressions') or 0)
        insight.cliques    = int(linha.get('clicks') or 0)

    integ_ads.ultima_sincronizacao = datetime.utcnow()
    db.session.commit()
    return len(linhas)
