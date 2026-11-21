    // main.js — Opstartcode — laadt als laatste, nadat alle functies bestaan.
    // ── Tab system ────────────────────────────────────────────
    let _activeTab = localStorage.getItem('sb_tab') || 'today';

    function switchTab(tabId) {
      _activeTab = tabId;
      localStorage.setItem('sb_tab', tabId);
      document.querySelectorAll('.tab-screen').forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
      const screen = document.getElementById('tab-' + tabId);
      if (screen) { screen.classList.add('active'); screen.scrollTop = 0; }
    }

    // Activate saved tab on load (before data loads)
    switchTab(_activeTab);

    // ── Migrate legacy localStorage keys (SportBit → Huppa) ──
    ['gist_id', 'github_token', 'push_subscribed'].forEach(k => {
      const old = localStorage.getItem(`sportbit_${k}`);
      if (old && !localStorage.getItem(`huppa_${k}`)) {
        localStorage.setItem(`huppa_${k}`, old);
        localStorage.removeItem(`sportbit_${k}`);
      }
    });

    // ── Load saved Gist ID ────────────────────────────────────
    const savedGistId = localStorage.getItem('huppa_gist_id');
    if (savedGistId) {
      document.getElementById('gistId').value = savedGistId;
      loadData();
    } else {
      const todayEl = document.getElementById('today-content');
      if (todayEl) todayEl.innerHTML = `<div class="empty-state"><p>Ga naar <strong>Acties</strong> om je Gist ID en GitHub token in te stellen.</p></div>`;
    }

    // Load saved token
    const savedToken = localStorage.getItem('huppa_github_token');
    if (savedToken) document.getElementById('githubToken').value = savedToken;

    document.getElementById('githubToken').addEventListener('change', () => {
      const t = document.getElementById('githubToken').value.trim();
      if (t) localStorage.setItem('huppa_github_token', t);
    });

    // Render Acties tab so config inputs are always accessible regardless of data state
    renderActiesTab(null);

    // Pull-to-refresh op Vandaag/Schema
    initPullToRefresh();
