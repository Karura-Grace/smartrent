console.log("SmartRent loaded");

document.addEventListener('DOMContentLoaded', function () {

  const appContainer = document.getElementById('app-container');
  if (!appContainer) return;

  appContainer.innerHTML = `
    <!-- NAV -->
    <nav class="nav" id="navbar">
      <div class="nav-inner">
        <a href="#home" class="nav-logo">Smart<span>Rent</span></a>
        <ul class="nav-links" id="nav-links">
          <li><a href="#features" class="nav-link">Features</a></li>
          <li><a href="#how" class="nav-link">How It Works</a></li>
          <li><a href="#pricing" class="nav-link">Pricing</a></li>
        </ul>
        <div class="nav-actions">
          <a href="/login" class="nav-login">Log in</a>
          <a href="/register" class="nav-cta">Get Started</a>
        </div>
        <button class="nav-burger" id="nav-burger" aria-label="Toggle menu">
          <span></span><span></span><span></span>
        </button>
      </div>
    </nav>

    <!-- MOBILE DRAWER -->
    <div class="nav-drawer" id="nav-drawer">
      <button class="drawer-close" id="drawer-close" aria-label="Close menu">x</button>
      <div class="drawer-links">
        <a href="#features" class="drawer-link">Features</a>
        <a href="#how" class="drawer-link">How It Works</a>
        <a href="#pricing" class="drawer-link">Pricing</a>
      </div>
      <div class="drawer-auth">
        <a href="/login" class="drawer-login">Log in</a>
        <a href="/register" class="drawer-cta-btn">Get Started Free</a>
      </div>
    </div>

    <!-- HERO -->
    <section id="home" class="hero">
      <div class="hero-blob blob-1"></div>
      <div class="hero-blob blob-2"></div>
      <div class="hero-inner">
        <div class="hero-badge">
          <span class="badge-dot"></span>
          Property Management, Reimagined
        </div>
        <h1>Pay Rent Easily.<br><em>Manage Properties Smarter.</em></h1>
        <p>Manage rentals or pay rent with ease - all in one simple platform built for Kenya.</p>
        <div class="hero-btns">
          <a href="/register" class="btn-main">Start for free <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg></a>
          <a href="#features" class="btn-ghost">See what's inside</a>
        </div>
      </div>
      <div class="hero-visual">
        <img src="/static/images/sm.png" alt="SmartRent Dashboard" class="hero-img">
      </div>
    </section>

    <!-- FEATURES -->
    <section id="features" class="features">
      <div class="features-header">
        <div class="section-label">Features</div>
        <h2>Built for how <em>you</em> actually work.</h2>
        <p class="section-sub">No more chasing tenant, losing receipts, or juggling WhatsApp threads. SmartRent handles it all.</p>
      </div>
      <div class="features-grid" id="features-grid"></div>
    </section>

    <!-- HOW IT WORKS -->
    <section id="how" class="how">
      <div class="how-header">
        <div class="section-label">How It Works</div>
        <h2>Up and running in minutes.</h2>
      </div>
      <div class="how-steps" id="how-steps"></div>
    </section>

    <!-- PRICING -->
    <section id="pricing" class="pricing">
      <div class="pricing-header">
        <div class="section-label">Pricing</div>
        <h2>Pay as you grow.</h2>
        <p class="section-sub">Start free, scale when you're ready. No hidden fees, no lock-in.</p>
      </div>
      <div class="pricing-grid" id="pricing-grid"></div>
    </section>

    <!-- WHO IT'S FOR -->
    <section id="usecases" class="usecases">
      <div class="section-label">Who It's For</div>
      <h2>Built for every kind of landlord.</h2>
      <div class="usecases-grid" id="usecases-grid"></div>
    </section>

    <!-- CTA -->
    <section class="cta">
      <div class="cta-inner">
        <h2>Ready to manage smarter?</h2>
        <p>Join landlord and property managers across Kenya who've simplified their operations with SmartRent.</p>
        <a href="/register" class="btn-main">Create your free account <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg></a>
      </div>
    </section>

    <!-- FOOTER - slim -->
    <footer class="footer">
      <div class="footer-inner">
        <span class="footer-logo">Smart<em>Rent</em></span>
        <div class="footer-links-row">
          <a href="#features">Features</a>
          <a href="#pricing">Pricing</a>
          <a href="#">About</a>
          <a href="#">Privacy</a>
          <a href="#">Terms</a>
          <a href="#">Contact</a>
        </div>
        <span class="footer-copy">&copy; 2026 SmartRent</span>
      </div>
    </footer>
  `;

  // ---- DATA ----

  const svgIcons = {
    mpesa: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="3"/><path d="M2 10h20"/><path d="M6 15h4"/><path d="M14 15h4"/></svg>`,
    lease: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/></svg>`,
    maintenance: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`,
    tenant: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    reports: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><path d="M2 20h20"/></svg>`,
    alerts: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 1.12h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.73a16 16 0 0 0 6.29 6.29l.96-.96a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>`,
  };

  const features = [
    {
      iconKey: 'mpesa',
      iconClass: 'icon-purple',
      tag: 'Payments',
      tagClass: 'tag-purple',
      title: 'Rent via M-PESA, automatically.',
      desc: 'Tenants pay with a tap. You get an instant notification and a clean record - no calls, no drama, no guessing who\'s paid.'
    },
    {
      iconKey: 'lease',
      iconClass: 'icon-pink',
      tag: 'Leases',
      tagClass: 'tag-pink',
      title: 'Digital leases that sign themselves.',
      desc: 'Send, sign, and store leases in minutes. No printing, no scanning - everything lives in one place and is legally binding.'
    },
    {
      iconKey: 'maintenance',
      iconClass: 'icon-teal',
      tag: 'Maintenance',
      tagClass: 'tag-teal',
      title: 'Repairs tracked, not forgotten.',
      desc: 'Tenants log issues with photos. You assign, track, and close - no more forgotten leaking roofs or long back-and-forth texts.'
    },
    {
      iconKey: 'tenant',
      iconClass: 'icon-amber',
      tag: 'Tenants',
      tagClass: 'tag-amber',
      title: 'Know your tenant before they move in.',
      desc: 'Background checks, ID verification, and rental history - all in one smooth flow. Fill vacancies with confidence.'
    },
    {
      iconKey: 'reports',
      iconClass: 'icon-blue',
      tag: 'Reports',
      tagClass: 'tag-blue',
      title: 'Your money, always in view.',
      desc: 'See exactly what\'s collected, what\'s outstanding, and where your portfolio stands - updated in real time.'
    },
    {
      iconKey: 'alerts',
      iconClass: 'icon-green',
      tag: 'Alerts',
      tagClass: 'tag-green',
      title: 'Late rent reminders that actually work.',
      desc: 'Automated SMS nudges go out before rent is due. You stay the friendly landlord - SmartRent does the awkward part.'
    },
  ];

  const steps = [
    { num: '01', title: 'Create your account', desc: 'Sign up with email. No credit card needed.', color: '#6E3BFF', light: '#E7DDFF' },
    { num: '02', title: 'Add your properties', desc: 'List buildings and units with rent and availability.', color: '#0ea5e9', light: '#e0f2fe' },
    { num: '03', title: 'Connect M-PESA', desc: 'Link your account for automated collections.', color: '#16a34a', light: '#dcfce7' },
    { num: '04', title: 'Invite tenant', desc: 'They review, sign, and pay - all online.', color: '#de3163', light: '#fce7ef' },
    { num: '05', title: 'Track everything', desc: 'Monitor rent, arrears, and occupancy live.', color: '#d97706', light: '#fef3c7' },
  ];

  const checkIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`;

  const plans = [
    {
      name: 'Free',
      tagline: 'Perfect to get started',
      price: 'KES 0',
      period: '/ forever',
      features: [
        { text: 'Up to 5 properties', ok: true },
        { text: 'Basic tenant management', ok: true },
        { text: 'Manual rent tracking', ok: true },
        { text: 'Lease storage', ok: true },
        { text: 'Email support', ok: true },
        { text: 'M-PESA automation', ok: false },
        { text: 'Financial reports', ok: false },
      ],
      cta: 'Get started free',
      featured: false,
    },
    {
      name: 'Growth',
      tagline: 'For active landlord',
      price: 'KES 100',
      period: '/ unit / month',
      features: [
        { text: 'Unlimited properties', ok: true },
        { text: 'Automated M-PESA collection', ok: true },
        { text: 'Digital lease signing', ok: true },
        { text: 'Maintenance tracking', ok: true },
        { text: 'Financial reports & rent roll', ok: true },
        { text: 'Automated SMS reminders', ok: true },
        { text: 'Priority support', ok: true },
      ],
      cta: 'Start free trial',
      featured: true,
    },
    {
      name: 'Enterprise',
      tagline: 'For large portfolios',
      price: 'Custom',
      period: 'contact us',
      features: [
        { text: 'Everything in Growth', ok: true },
        { text: 'API access', ok: true },
        { text: 'White-label options', ok: true },
        { text: 'Dedicated account manager', ok: true },
        { text: 'Custom integrations', ok: true },
        { text: 'SLA guarantee', ok: true },
      ],
      cta: 'Talk to sales',
      featured: false,
    },
  ];

  const useCases = [
    { title: 'Individual Landlords', desc: 'A few units or many - track rent, leases & maintenance effortlessly.' },
    { title: 'Property Managers', desc: 'Centralize billing, communications & reporting across portfolios.' },
    { title: 'Real Estate Agencies', desc: 'Offer value-added management services with branded reports.' },
    { title: 'Diaspora Landlords', desc: 'Stay in control from abroad with real-time dashboards & alerts.' },
    { title: 'Homeowners with Rentals', desc: 'Turn extra rooms into income - handle payments & contracts.' },
    { title: 'Facility Managers', desc: 'Coordinate teams, log service requests & monitor SLAs.' },
  ];

  // ---- RENDER ----

  document.getElementById('features-grid').innerHTML = features.map(f => `
    <div class="feat-card">
      <div class="feat-icon ${f.iconClass}">${svgIcons[f.iconKey]}</div>
      <span class="feat-tag ${f.tagClass}">${f.tag}</span>
      <h3>${f.title}</h3>
      <p>${f.desc}</p>
    </div>
  `).join('');

  document.getElementById('how-steps').innerHTML = steps.map(s => `
    <div class="how-step">
      <div class="step-circle" style="background:${s.color}; border-color:${s.color}; color:#fff;">${s.num}</div>
      <div class="how-step-connector" style="background:${s.light};"></div>
      <div>
        <h4>${s.title}</h4>
        <p>${s.desc}</p>
      </div>
    </div>
  `).join('');

  document.getElementById('pricing-grid').innerHTML = plans.map(p => `
    <div class="p-card ${p.featured ? 'featured' : ''}">
      ${p.featured ? '<div class="p-badge">Most Popular</div>' : ''}
      <div class="p-name">${p.name}</div>
      <div class="p-tagline">${p.tagline}</div>
      <div class="p-price">${p.price} <span>${p.period}</span></div>
      <div class="p-divider"></div>
      <ul class="p-features">
        ${p.features.map(f => `
          <li class="${f.ok ? '' : 'muted'}">
            ${checkIcon}${f.text}
          </li>`).join('')}
      </ul>
      <a href="/register" class="p-cta ${p.featured ? 'p-cta-main' : ''}">${p.cta}</a>
    </div>
  `).join('');

  document.getElementById('usecases-grid').innerHTML = useCases.map(u => `
    <div class="uc-card">
      <h4>${u.title}</h4>
      <p>${u.desc}</p>
    </div>
  `).join('');

  // ---- NAV SCROLL ----
  const navbar = document.getElementById('navbar');
  window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 40);
  });

  // ---- ACTIVE NAV LINK ----
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav-link');
  const sectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        navLinks.forEach(l => l.classList.remove('active'));
        const active = document.querySelector(`.nav-link[href="#${entry.target.id}"]`);
        if (active) active.classList.add('active');
      }
    });
  }, { threshold: 0.4 });
  sections.forEach(s => sectionObserver.observe(s));

  // ---- MOBILE BURGER ----
  const burger = document.getElementById('nav-burger');
  const drawer = document.getElementById('nav-drawer');
  const drawerClose = document.getElementById('drawer-close');

  function openDrawer() {
    drawer.style.display = 'flex';
    // Force reflow then add open class for transition
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        drawer.classList.add('open');
      });
    });
    burger.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    drawer.classList.remove('open');
    burger.classList.remove('open');
    document.body.style.overflow = '';
    setTimeout(() => {
      if (!drawer.classList.contains('open')) {
        drawer.style.display = 'none';
      }
    }, 280);
  }

  burger.addEventListener('click', () => {
    if (drawer.classList.contains('open')) {
      closeDrawer();
    } else {
      openDrawer();
    }
  });

  drawerClose.addEventListener('click', closeDrawer);

  // Close drawer when a link is clicked
  drawer.querySelectorAll('.drawer-link, .drawer-login, .drawer-cta-btn').forEach(a => {
    a.addEventListener('click', closeDrawer);
  });

  // ---- SMOOTH SCROLL ----
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      const target = document.querySelector(a.getAttribute('href'));
      if (target) {
        e.preventDefault();
        closeDrawer();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // ---- FADE IN ON SCROLL ----
  const fadeEls = document.querySelectorAll('.feat-card, .how-step, .p-card, .uc-card');
  const fadeObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        fadeObserver.unobserve(e.target);
      }
    });
  }, { threshold: 0.1 });
  fadeEls.forEach(el => fadeObserver.observe(el));

  console.log("SmartRent ready.");
});
