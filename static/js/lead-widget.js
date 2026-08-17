(function () {
  'use strict';

  var script = document.currentScript;
  if (!script) return;

  var slug = script.getAttribute('data-slug');
  if (!slug) return;

  var origin;
  try {
    origin = new URL(script.src).origin;
  } catch (e) {
    return;
  }

  var PREFIX = 'unitto-lw-';

  function el(tag, className, attrs) {
    var e = document.createElement(tag);
    if (className) e.className = PREFIX + className;
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
      }
    }
    return e;
  }

  function injectStyle() {
    var style = document.createElement('style');
    style.textContent =
      '.' + PREFIX + 'btn{position:fixed;bottom:20px;right:20px;z-index:999999;' +
      'background:#0F766E;color:#fff;border:none;border-radius:999px;padding:14px 20px;' +
      'font:600 14px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.2);cursor:pointer;display:flex;align-items:center;gap:8px}' +
      '.' + PREFIX + 'btn:hover{background:#0d6259}' +
      '.' + PREFIX + 'panel{position:fixed;bottom:20px;right:20px;z-index:999999;width:300px;' +
      'max-width:calc(100vw - 40px);background:#fff;border-radius:12px;' +
      'box-shadow:0 8px 30px rgba(0,0,0,.25);font-family:-apple-system,BlinkMacSystemFont,' +
      '"Segoe UI",Roboto,Arial,sans-serif;overflow:hidden;display:none}' +
      '.' + PREFIX + 'panel.' + PREFIX + 'open{display:block}' +
      '.' + PREFIX + 'header{background:#0F766E;color:#fff;padding:14px 16px;' +
      'display:flex;justify-content:space-between;align-items:center;font-weight:600;font-size:14px}' +
      '.' + PREFIX + 'close{background:none;border:none;color:#fff;font-size:18px;' +
      'cursor:pointer;line-height:1;padding:0}' +
      '.' + PREFIX + 'body{padding:14px 16px}' +
      '.' + PREFIX + 'field{margin-bottom:10px}' +
      '.' + PREFIX + 'field label{display:block;font-size:12px;color:#374151;margin-bottom:4px;font-weight:500}' +
      '.' + PREFIX + 'field input,.' + PREFIX + 'field select,.' + PREFIX + 'field textarea{' +
      'width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #D1D5DB;' +
      'border-radius:6px;font-size:13px;font-family:inherit}' +
      '.' + PREFIX + 'field textarea{resize:vertical;min-height:50px}' +
      '.' + PREFIX + 'hp{position:absolute;left:-9999px;top:-9999px}' +
      '.' + PREFIX + 'submit{width:100%;background:#0F766E;color:#fff;border:none;' +
      'border-radius:6px;padding:10px;font-size:13px;font-weight:600;cursor:pointer;margin-top:4px}' +
      '.' + PREFIX + 'submit:hover{background:#0d6259}' +
      '.' + PREFIX + 'submit:disabled{opacity:.6;cursor:default}' +
      '.' + PREFIX + 'msg{font-size:13px;padding:4px 0;margin-top:6px}' +
      '.' + PREFIX + 'msg--erro{color:#B91C1C}' +
      '.' + PREFIX + 'msg--ok{color:#0F766E;font-weight:600;text-align:center;padding:20px 0}';
    document.head.appendChild(style);
  }

  function buildPanel() {
    var panel = el('div', 'panel');

    var header = el('div', 'header');
    var titulo = document.createElement('span');
    titulo.textContent = 'Fale conosco';
    var closeBtn = el('button', 'close', { type: 'button', 'aria-label': 'Fechar' });
    closeBtn.innerHTML = '&times;';
    header.appendChild(titulo);
    header.appendChild(closeBtn);

    var bodyEl = el('div', 'body');

    var form = document.createElement('form');

    var fNome = el('div', 'field');
    fNome.innerHTML = '<label>Nome*</label>';
    var inputNome = el('input', null, { type: 'text', name: 'nome', required: 'required' });
    fNome.appendChild(inputNome);

    var fTel = el('div', 'field');
    fTel.innerHTML = '<label>Telefone*</label>';
    var inputTel = el('input', null, { type: 'text', name: 'telefone', required: 'required' });
    fTel.appendChild(inputTel);

    var fServico = el('div', 'field');
    fServico.style.display = 'none';
    fServico.innerHTML = '<label>Serviço de interesse</label>';
    var selectServico = el('select', null, { name: 'servico' });
    fServico.appendChild(selectServico);

    var fMsg = el('div', 'field');
    fMsg.innerHTML = '<label>Mensagem</label>';
    var textareaMsg = el('textarea', null, { name: 'mensagem' });
    fMsg.appendChild(textareaMsg);

    var inputHoneypot = el('input', 'hp', {
      type: 'text', name: 'assunto', tabindex: '-1', autocomplete: 'off'
    });

    var submitBtn = el('button', 'submit', { type: 'submit' });
    submitBtn.textContent = 'Enviar';

    var feedback = document.createElement('div');

    form.appendChild(fNome);
    form.appendChild(fTel);
    form.appendChild(fServico);
    form.appendChild(fMsg);
    form.appendChild(inputHoneypot);
    form.appendChild(submitBtn);
    form.appendChild(feedback);

    bodyEl.appendChild(form);
    panel.appendChild(header);
    panel.appendChild(bodyEl);

    closeBtn.addEventListener('click', function () {
      panel.classList.remove(PREFIX + 'open');
    });

    fetch(origin + '/' + encodeURIComponent(slug) + '/servicos.json')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var servicos = data && data.servicos;
        if (!servicos || !servicos.length) return;
        servicos.forEach(function (nome) {
          var opt = document.createElement('option');
          opt.value = nome;
          opt.textContent = nome;
          selectServico.appendChild(opt);
        });
        fServico.style.display = '';
      })
      .catch(function () {});

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      submitBtn.disabled = true;
      feedback.innerHTML = '';

      var payload = new URLSearchParams({
        nome: inputNome.value,
        telefone: inputTel.value,
        servico: selectServico.value || '',
        mensagem: textareaMsg.value,
        assunto: inputHoneypot.value
      });

      fetch(origin + '/' + encodeURIComponent(slug) + '/lead-capture', {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
        body: payload
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.ok) {
            form.style.display = 'none';
            var ok = el('div', 'msg msg--ok');
            ok.textContent = 'Obrigado! Entraremos em contato em breve.';
            bodyEl.appendChild(ok);
            setTimeout(function () {
              panel.classList.remove(PREFIX + 'open');
            }, 4000);
          } else {
            var erro = el('div', 'msg msg--erro');
            erro.textContent = (data && data.erro) || 'Não foi possível enviar. Tente novamente.';
            feedback.innerHTML = '';
            feedback.appendChild(erro);
            submitBtn.disabled = false;
          }
        })
        .catch(function () {
          var erro = el('div', 'msg msg--erro');
          erro.textContent = 'Não foi possível enviar. Verifique sua conexão.';
          feedback.innerHTML = '';
          feedback.appendChild(erro);
          submitBtn.disabled = false;
        });
    });

    return panel;
  }

  function init() {
    injectStyle();

    var btn = el('button', 'btn', { type: 'button' });
    btn.textContent = 'Fale conosco';

    var panel = buildPanel();

    btn.addEventListener('click', function () {
      panel.classList.toggle(PREFIX + 'open');
    });

    document.body.appendChild(btn);
    document.body.appendChild(panel);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
