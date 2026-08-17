from datetime import date, time

from flask import render_template, request, redirect, url_for, jsonify, abort, flash, g

from models import db, Servico, Agendamento, Lead
from admin.tenant import tq

from . import public_bp
from .availability import eligible_profissionais, get_available_slots


def _agendamento_online_disponivel(empresa):
    """Página pública de agendamento exige tenant ativo E plano Avançado/Profissional."""
    return empresa.is_ativa() and empresa.tem_agendamento_online()


@public_bp.route('/<slug>')
def vitrine(slug):
    empresa = g.empresa
    servicos = []
    motivo_indisponivel = None
    if not empresa.is_ativa():
        motivo_indisponivel = 'inativa'
    elif not empresa.tem_agendamento_online():
        motivo_indisponivel = 'plano'
    else:
        servicos = tq(Servico).filter_by(ativo=True, agendamento_online=True).order_by(Servico.nome).all()
    return render_template('public/vitrine.html', empresa=empresa, servicos=servicos,
                            motivo_indisponivel=motivo_indisponivel)


@public_bp.route('/<slug>/agendar/<int:servico_id>')
def agendar(slug, servico_id):
    if not _agendamento_online_disponivel(g.empresa):
        abort(404)
    servico = tq(Servico).filter_by(id=servico_id, ativo=True, agendamento_online=True).first()
    if not servico:
        abort(404)
    profissionais = eligible_profissionais(servico)
    return render_template('public/agendar.html', empresa=g.empresa, servico=servico,
                            profissionais=profissionais, hoje=date.today().isoformat())


@public_bp.route('/<slug>/agendar/<int:servico_id>/slots')
def slots_json(slug, servico_id):
    if not _agendamento_online_disponivel(g.empresa):
        abort(404)
    servico = tq(Servico).filter_by(id=servico_id, ativo=True, agendamento_online=True).first()
    if not servico:
        abort(404)

    profissional_id = request.args.get('profissional_id', type=int)
    profissional = next((p for p in eligible_profissionais(servico) if p.id == profissional_id), None)
    if not profissional:
        return jsonify(slots=[])

    try:
        data_sel = date.fromisoformat(request.args.get('data', ''))
    except ValueError:
        return jsonify(slots=[])
    if data_sel < date.today():
        return jsonify(slots=[])

    slots = get_available_slots(profissional.id, servico, data_sel)
    return jsonify(slots=[s.strftime('%H:%M') for s in slots])


@public_bp.route('/<slug>/agendar/<int:servico_id>', methods=['POST'])
def agendar_submit(slug, servico_id):
    if not _agendamento_online_disponivel(g.empresa):
        abort(404)
    servico = tq(Servico).filter_by(id=servico_id, ativo=True, agendamento_online=True).first()
    if not servico:
        abort(404)

    profissional_id = request.form.get('profissional_id', type=int)
    nome_cliente = request.form.get('nome_cliente', '').strip()
    telefone = request.form.get('telefone', '').strip()

    profissional = next((p for p in eligible_profissionais(servico) if p.id == profissional_id), None)

    erro = None
    if not profissional:
        erro = 'Profissional inválido para este serviço.'
    elif not nome_cliente:
        erro = 'Informe seu nome.'
    elif not telefone:
        erro = 'Informe um telefone para contato.'

    data_val = None
    hora_val = None
    if not erro:
        try:
            data_val = date.fromisoformat(request.form.get('data', ''))
        except ValueError:
            erro = 'Data inválida.'
    if not erro and data_val < date.today():
        erro = 'Data inválida.'
    if not erro:
        try:
            h, m = map(int, request.form.get('hora_inicio', '').split(':'))
            hora_val = time(h, m)
        except Exception:
            erro = 'Horário inválido.'

    if not erro:
        disponiveis = get_available_slots(profissional.id, servico, data_val)
        if hora_val not in disponiveis:
            erro = 'Esse horário não está mais disponível. Escolha outro.'

    if erro:
        flash(erro, 'error')
        return redirect(url_for('public.agendar', slug=slug, servico_id=servico_id))

    duracao_min = max(15, (servico.duracao_horas or 0) * 60 + (servico.duracao_minutos or 0))
    agendamento = Agendamento(
        nome_cliente=nome_cliente,
        telefone=telefone,
        profissional_id=profissional.id,
        servico_id=servico.id,
        servicos_lista=[servico],
        unidade_id=profissional.unidade_id,
        data=data_val,
        hora_inicio=hora_val,
        duracao_min=duracao_min,
        status='agendado',
        como_conheceu='Agendamento online',
        empresa_id=g.empresa.id,
    )
    db.session.add(agendamento)
    db.session.commit()
    return redirect(url_for('public.confirmado', slug=slug, agendamento_id=agendamento.id))


@public_bp.route('/<slug>/confirmado/<int:agendamento_id>')
def confirmado(slug, agendamento_id):
    agendamento = tq(Agendamento).filter_by(id=agendamento_id).first()
    if not agendamento:
        abort(404)
    return render_template('public/confirmado.html', empresa=g.empresa, agendamento=agendamento)


@public_bp.route('/<slug>/servicos.json')
def servicos_json(slug):
    """Lista de serviços para popular o <select> do widget de captura de leads
    (static/js/lead-widget.js), embutido no site externo do cliente."""
    empresa = g.empresa
    nomes = []
    if empresa.is_ativa():
        nomes = [s.nome for s in tq(Servico).filter_by(ativo=True, agendamento_online=True)
                 .order_by(Servico.nome).all()]
    resp = jsonify(servicos=nomes)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


@public_bp.route('/<slug>/lead-capture', methods=['POST'])
def lead_capture(slug):
    """Cria um Lead a partir do site externo do cliente — via widget (fetch,
    Accept: application/json) ou via um <form> cru apontando o action pra cá
    (navegação normal, sem CORS envolvido)."""
    empresa = g.empresa
    quer_json = 'application/json' in (request.headers.get('Accept') or '')

    def _responder(ok, erro=None, status=200):
        if quer_json:
            resp = jsonify(ok=ok, erro=erro)
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp, status
        redirect_to = request.form.get('_redirect', '').strip()
        if ok:
            if redirect_to.startswith(('http://', 'https://')):
                return redirect(redirect_to)
            return redirect(url_for('public.lead_capture_obrigado', slug=slug))
        flash(erro or 'Não foi possível enviar. Tente novamente.', 'error')
        return redirect(redirect_to if redirect_to.startswith(('http://', 'https://'))
                         else request.referrer or url_for('public.vitrine', slug=slug))

    if not empresa.is_ativa():
        return _responder(False, 'Indisponível no momento.', 404)

    # honeypot anti-spam: campo invisível no widget — bot preenche, humano não
    if (request.form.get('assunto') or '').strip():
        return _responder(True)  # finge sucesso, não grava nada

    nome     = request.form.get('nome', '').strip()
    telefone = request.form.get('telefone', '').strip()
    if not nome or not telefone:
        return _responder(False, 'Preencha nome e telefone.', 400)

    lead = Lead(
        name=nome, phone=telefone,
        service=request.form.get('servico', '').strip() or None,
        message=request.form.get('mensagem', '').strip() or None,
        source='site', status='novo', empresa_id=empresa.id,
    )
    db.session.add(lead)
    db.session.commit()
    return _responder(True)


@public_bp.route('/<slug>/lead-capture/obrigado')
def lead_capture_obrigado(slug):
    return render_template('public/lead_obrigado.html', empresa=g.empresa)
