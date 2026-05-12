/* ============================================================
   RENATA ROSA BEAUTY CONCEPT — main.js
   ============================================================ */

// ── Google Reviews ───────────────────────────────────────────
function starsHtml(rating) {
  return Array.from({ length: 5 }, (_, i) =>
    `<span style="opacity:${i < rating ? 1 : 0.25}">★</span>`
  ).join('');
}

async function loadReviews() {
  const grid   = document.getElementById('reviewsGrid');
  const ratingEl = document.getElementById('googleRating');
  if (!grid) return;

  try {
    const res  = await fetch('/api/reviews');
    const data = await res.json();

    if (data.error || !data.reviews?.length) {
      grid.innerHTML = '<p class="reviews__loading">Nenhuma avaliação disponível no momento.</p>';
      return;
    }

    // Rating summary
    if (ratingEl && data.rating) {
      ratingEl.innerHTML = `
        <span class="rating__score">${data.rating.toFixed(1)}</span>
        <div>
          <div class="rating__stars">${starsHtml(Math.round(data.rating))}</div>
          <div class="rating__total">${data.total} avaliações no Google</div>
        </div>`;
    }

    // Review cards
    grid.innerHTML = data.reviews.map(r => {
      const initial = r.author ? r.author[0].toUpperCase() : '?';
      const avatar  = r.photo
        ? `<img src="${r.photo}" alt="${r.author}" class="author__photo" onerror="this.outerHTML='<div class=\\'author__avatar\\'>${initial}</div>'" />`
        : `<div class="author__avatar">${initial}</div>`;

      return `
        <div class="depoimento__card reveal">
          <div class="depoimento__stars">${starsHtml(r.rating)}</div>
          <p class="depoimento__text">"${r.text}"</p>
          <div class="depoimento__author">
            ${avatar}
            <div>
              <strong>${r.author}</strong>
              <span>${r.time}</span>
            </div>
          </div>
        </div>`;
    }).join('');

    // Re-trigger scroll reveal on new cards
    grid.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

  } catch {
    grid.innerHTML = '<p class="reviews__loading">Não foi possível carregar as avaliações.</p>';
  }
}

loadReviews();

// ── FAQ accordion ────────────────────────────────────────────
document.querySelectorAll('.faq__question').forEach(btn => {
  btn.addEventListener('click', () => {
    const answer   = btn.nextElementSibling;
    const expanded = btn.getAttribute('aria-expanded') === 'true';

    // Fecha todos
    document.querySelectorAll('.faq__question').forEach(b => {
      b.setAttribute('aria-expanded', 'false');
      b.nextElementSibling.classList.remove('open');
    });

    // Abre o clicado (se estava fechado)
    if (!expanded) {
      btn.setAttribute('aria-expanded', 'true');
      answer.classList.add('open');
    }
  });
});

// ── Navbar: scroll behavior ──────────────────────────────────
const navbar = document.getElementById('navbar');
window.addEventListener('scroll', () => {
  navbar.classList.toggle('scrolled', window.scrollY > 40);
});

// ── Hamburger menu ───────────────────────────────────────────
const hamburger = document.getElementById('hamburger');
const mobileMenu = document.getElementById('mobileMenu');

hamburger.addEventListener('click', () => {
  mobileMenu.classList.toggle('open');
});

mobileMenu.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => mobileMenu.classList.remove('open'));
});

// ── Counter animation ────────────────────────────────────────
function animateCounter(el, target, duration = 1800) {
  let start = 0;
  const step = Math.ceil(target / (duration / 16));
  const timer = setInterval(() => {
    start += step;
    if (start >= target) {
      el.textContent = target;
      clearInterval(timer);
    } else {
      el.textContent = start;
    }
  }, 16);
}

const countersObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const el = entry.target;
      const target = parseInt(el.dataset.target, 10);
      animateCounter(el, target);
      countersObserver.unobserve(el);
    }
  });
}, { threshold: 0.5 });

document.querySelectorAll('.numbers__value').forEach(el => {
  countersObserver.observe(el);
});


// ── Video cover — play on click ──────────────────────────────
const videoCover = document.getElementById('videoCover');
const heroVideo  = document.getElementById('heroVideo');
if (videoCover && heroVideo) {
  videoCover.addEventListener('click', () => {
    videoCover.style.transition = 'opacity .35s';
    videoCover.style.opacity    = '0';
    setTimeout(() => { videoCover.style.display = 'none'; }, 350);
    heroVideo.controls = true;
    heroVideo.play();
  });
}

// ── Contact form (rodapé) ─────────────────────────────────────
const SERVICO_LABELS = {
  mechas:      'Mechas / Balayage',
  correcao:    'Correção de Cor',
  coloracao:   'Coloração Global',
  reconstrucao:'Reconstrução Capilar',
  corte:       'Corte Feminino',
  outro:       'Outro',
};

async function saveLead(data) {
  try {
    const res  = await fetch('/api/contato', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const json = await res.json();
    return json.lead_id || null;
  } catch { return null; }
}

function updateLead(id, data) {
  fetch(`/api/contato/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).catch(() => {});
}

function openWhatsApp(nome, telefone, servico, mensagem) {
  const label = SERVICO_LABELS[servico] || servico;
  const text  = `Olá Renata! Me chamo *${nome}* e tenho interesse em: *${label}*.\n\n${mensagem ? 'Sobre meu cabelo: ' + mensagem + '\n\n' : ''}Meu contato: ${telefone}`;
  window.open(`https://wa.me/5512997235385?text=${encodeURIComponent(text)}`, '_blank', 'noopener');
}

const contactForm = document.getElementById('contactForm');
if (contactForm) {
  contactForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const nome     = contactForm.nome.value.trim();
    const telefone = contactForm.telefone.value.trim();
    const servico  = contactForm.servico.value;
    const mensagem = contactForm.mensagem?.value.trim() || '';
    if (!nome || !telefone || !servico) {
      alert('Por favor, preencha nome, WhatsApp e serviço de interesse.');
      return;
    }
    saveLead({ nome, telefone, servico, mensagem });
    openWhatsApp(nome, telefone, servico, mensagem);
    contactForm.reset();
  });
}

// Funil multi-etapa movido para funil.js

// ── Scroll-reveal (Intersection Observer) ───────────────────
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

document.querySelectorAll(`
  .servico__card,
  .depoimento__card,
  .diferencial__item,
  .processo__step,
  .portfolio__item
`).forEach(el => {
  el.classList.add('reveal');
  revealObserver.observe(el);
});

// ── Fade-in CSS injected dynamically ─────────────────────────
const style = document.createElement('style');
style.textContent = `
  .reveal {
    opacity: 0;
    transform: translateY(24px);
    transition: opacity .6s ease, transform .6s ease;
  }
  .reveal.visible {
    opacity: 1;
    transform: none;
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: scale(.97); }
    to   { opacity: 1; transform: scale(1); }
  }
`;
document.head.appendChild(style);
