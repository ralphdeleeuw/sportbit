    // ui.js — Gedeelde UI-bouwstenen: toasts, bevestigingsdialoog, sync-balk,
    // pull-to-refresh en de lokale (offline) cache van de Gist.

    // ── Toasts ────────────────────────────────────────────────────────────
    // Vervangt alert(): korte melding onderaan, optioneel met actieknop
    // (bijv. "Ongedaan maken").
    function showToast(msg, { type = 'info', duration = 4000, actionLabel = '', onAction = null } = {}) {
      let wrap = document.getElementById('toast-wrap');
      if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'toast-wrap';
        wrap.className = 'toast-wrap';
        document.body.appendChild(wrap);
      }
      const t = document.createElement('div');
      t.className = `toast toast-${type}`;
      t.setAttribute('role', 'status');
      const span = document.createElement('span');
      span.className = 'toast-msg';
      span.textContent = msg;
      t.appendChild(span);
      let done = false;
      const close = () => {
        if (done) return;
        done = true;
        t.classList.add('toast-out');
        setTimeout(() => t.remove(), 250);
      };
      if (actionLabel && onAction) {
        const b = document.createElement('button');
        b.className = 'toast-action';
        b.textContent = actionLabel;
        b.onclick = () => { close(); onAction(); };
        t.appendChild(b);
      }
      t.addEventListener('click', e => { if (e.target === t || e.target === span) close(); });
      wrap.appendChild(t);
      setTimeout(close, duration);
      return close;
    }

    // ── Bevestigen ────────────────────────────────────────────────────────
    // Vervangt confirm(): bottom-sheet met twee knoppen. Geeft een Promise<boolean>.
    function askConfirm(msg, okLabel = 'OK', { danger = false } = {}) {
      return new Promise(resolve => {
        const ov = document.createElement('div');
        ov.className = 'sheet-overlay';
        ov.innerHTML = `<div class="sheet" role="dialog" aria-modal="true">
          <div class="sheet-msg"></div>
          <div class="sheet-actions">
            <button class="workflow-btn sheet-cancel">Annuleren</button>
            <button class="workflow-btn ${danger ? 'danger' : 'info'} sheet-ok"></button>
          </div>
        </div>`;
        ov.querySelector('.sheet-msg').textContent = msg;
        ov.querySelector('.sheet-ok').textContent = okLabel;
        const finish = v => { ov.remove(); resolve(v); };
        ov.querySelector('.sheet-ok').onclick = () => finish(true);
        ov.querySelector('.sheet-cancel').onclick = () => finish(false);
        ov.addEventListener('click', e => { if (e.target === ov) finish(false); });
        document.body.appendChild(ov);
      });
    }

    // ── Sync-balk ─────────────────────────────────────────────────────────
    // Eén smalle balk bovenaan, zichtbaar op elke tab, met alle lopende
    // workflows. pollWorkflowRun() houdt hem bij.
    const _syncJobs = new Map(); // workflowFile → {label, text, state}

    function syncBarUpdate(key, label, text, state = 'running') {
      _syncJobs.set(key, { label, text, state });
      _renderSyncBar();
      if (state !== 'running') {
        setTimeout(() => {
          const j = _syncJobs.get(key);
          if (j && j.state === state) { _syncJobs.delete(key); _renderSyncBar(); }
        }, state === 'ok' ? 4000 : 10000);
      }
    }

    function _renderSyncBar() {
      let bar = document.getElementById('sync-bar');
      if (!bar) {
        bar = document.createElement('div');
        bar.id = 'sync-bar';
        bar.className = 'sync-bar';
        bar.onclick = () => switchTab('acties');
        document.body.appendChild(bar);
      }
      if (_syncJobs.size === 0) { bar.classList.remove('show'); return; }
      const jobs = [..._syncJobs.values()];
      const worst = jobs.some(j => j.state === 'fail') ? 'fail' : jobs.some(j => j.state === 'running') ? 'running' : 'ok';
      bar.className = `sync-bar show sync-${worst}`;
      bar.innerHTML = jobs.map(j =>
        `<span class="sync-job">${j.state === 'running' ? '<span class="sync-spin"></span>' : ''}${escapeHtml(j.label)} · ${escapeHtml(j.text)}</span>`
      ).join('');
    }

    // ── Offline-banner ────────────────────────────────────────────────────
    function setOfflineBanner(updatedAt) {
      let b = document.getElementById('offline-banner');
      if (!updatedAt) { if (b) b.remove(); return; }
      if (!b) {
        b = document.createElement('div');
        b.id = 'offline-banner';
        b.className = 'offline-banner';
        b.onclick = () => loadData();
        document.body.appendChild(b);
      }
      b.textContent = `📴 Offline — data van ${relTime(updatedAt)} · tik om opnieuw te proberen`;
    }

    // ── Pull-to-refresh ───────────────────────────────────────────────────
    // Alleen op de Vandaag- en Schema-tab; trek omlaag vanaf de bovenkant.
    function initPullToRefresh() {
      const THRESHOLD = 70;
      let startY = null, pulling = false, dist = 0;
      let ind = document.getElementById('ptr-indicator');
      if (!ind) {
        ind = document.createElement('div');
        ind.id = 'ptr-indicator';
        ind.className = 'ptr-indicator';
        ind.textContent = '↓ Trek om te verversen';
        document.body.appendChild(ind);
      }
      const screen = () => document.querySelector('.tab-screen.active');
      const allowed = () => ['today', 'schema'].includes(_activeTab);
      document.addEventListener('touchstart', e => {
        const s = screen();
        if (!allowed() || !s || s.scrollTop > 0 || window.scrollY > 0) { startY = null; return; }
        startY = e.touches[0].clientY; pulling = false; dist = 0;
      }, { passive: true });
      document.addEventListener('touchmove', e => {
        if (startY == null) return;
        dist = e.touches[0].clientY - startY;
        if (dist <= 0) { ind.classList.remove('show'); return; }
        pulling = true;
        ind.classList.add('show');
        ind.style.transform = `translate(-50%, ${Math.min(dist, THRESHOLD + 20) - 40}px)`;
        ind.textContent = dist > THRESHOLD ? '↻ Loslaten om te verversen' : '↓ Trek om te verversen';
      }, { passive: true });
      document.addEventListener('touchend', async () => {
        if (startY == null || !pulling) { startY = null; return; }
        const go = dist > THRESHOLD;
        startY = null; pulling = false;
        if (!go) { ind.classList.remove('show'); return; }
        ind.textContent = '↻ Verversen…';
        try { await loadData(); } finally {
          ind.classList.remove('show');
          ind.style.transform = '';
        }
      });
    }

    // ── Lokale Gist-cache (IndexedDB) ─────────────────────────────────────
    // De Gist kan > 1 MB zijn; localStorage is daarvoor te krap. Bewaard wordt
    // alleen wat de app nodig heeft: updated_at + per bestand de inhoud.
    const _IDB_NAME = 'sportbit';
    const _IDB_STORE = 'gist';

    function _idb() {
      return new Promise((resolve, reject) => {
        if (!('indexedDB' in window)) { reject(new Error('geen IndexedDB')); return; }
        const req = indexedDB.open(_IDB_NAME, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(_IDB_STORE);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }

    async function gistCacheGet(gistId) {
      try {
        const db = await _idb();
        return await new Promise(resolve => {
          const r = db.transaction(_IDB_STORE).objectStore(_IDB_STORE).get(gistId);
          r.onsuccess = () => resolve(r.result || null);
          r.onerror = () => resolve(null);
        });
      } catch { return null; }
    }

    async function gistCacheSet(gistId, gist) {
      try {
        const slim = { updated_at: gist.updated_at, files: {} };
        for (const [name, f] of Object.entries(gist.files || {})) {
          if (f && typeof f.content === 'string') slim.files[name] = { filename: name, content: f.content };
        }
        const db = await _idb();
        db.transaction(_IDB_STORE, 'readwrite').objectStore(_IDB_STORE).put(slim, gistId);
      } catch (e) { console.warn('Gist-cache opslaan mislukt:', e); }
    }
