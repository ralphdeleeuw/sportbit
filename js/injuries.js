    // injuries.js — Blessures: registreren, verloop, beter/erger melden.
    // ── Blessures ─────────────────────────────────────────────
    // Opgeslagen in health_input.json (sleutel "injuries") — dezelfde bron die álle
    // AI-coaches lezen (WOD-plan, herstel-advies, Open Gym, thuistraining, hardlopen).
    // INJURY_SEVERITIES / INJURY_STATUSES staan bovenaan het bestand: de eerste render
    // draait al voordat dit blok is uitgevoerd.

    function _normaliseInjury(raw, idx) {
      if (typeof raw === 'string') {
        return { id: `inj-${idx}`, area: raw.trim(), description: '', severity: '',
                 status: 'actief', since: '', avoid: [], notes: '' };
      }
      if (!raw || typeof raw !== 'object') return null;
      const avoid = Array.isArray(raw.avoid)
        ? raw.avoid.filter(Boolean).map(String)
        : (raw.avoid ? String(raw.avoid).split(',').map(s => s.trim()).filter(Boolean) : []);
      return {
        id: String(raw.id || `inj-${idx}`),
        area: String(raw.area || '').trim(),
        description: String(raw.description || '').trim(),
        severity: INJURY_SEVERITIES.includes(raw.severity) ? raw.severity : '',
        status: INJURY_STATUSES.includes(raw.status) ? raw.status : 'actief',
        since: String(raw.since || ''),
        avoid,
        notes: String(raw.notes || '').trim(),
        worsened_on: String(raw.worsened_on || ''),
        worsened_note: String(raw.worsened_note || '').trim(),
        improved_on: String(raw.improved_on || ''),
        improved_note: String(raw.improved_note || '').trim(),
        history: _normaliseInjuryHistory(raw),
      };
    }

    // Verergerd telt alleen zolang de blessure niet (deels) hersteld is
    function _isWorsened(inj) {
      return !!inj.worsened_on && inj.status === 'actief';
    }

    // Verloop: lijst met {date, type: 'erger'|'beter', note, severity}. Oudere
    // blessures zonder history krijgen een afgeleid verloop uit worsened_on/improved_on.
    function _normaliseInjuryHistory(raw) {
      const hist = Array.isArray(raw.history)
        ? raw.history
            .filter(h => h && h.date && (h.type === 'erger' || h.type === 'beter'))
            .map(h => ({ date: String(h.date), type: h.type,
                         note: String(h.note || '').trim(), severity: String(h.severity || '') }))
        : [];
      if (hist.length) return hist;
      const derived = [];
      if (raw.worsened_on) derived.push({ date: String(raw.worsened_on), type: 'erger', note: String(raw.worsened_note || '').trim(), severity: '' });
      if (raw.improved_on) derived.push({ date: String(raw.improved_on), type: 'beter', note: String(raw.improved_note || '').trim(), severity: '' });
      return derived.sort((a, b) => a.date.localeCompare(b.date));
    }

    function _renderInjuryHistory(inj) {
      if (!inj.history.length) return '';
      const items = [...inj.history].reverse().map(h => {
        const icon = h.type === 'erger' ? '⬆' : '⬇';
        const label = h.type === 'erger' ? 'Erger' : 'Beter';
        const sev = h.severity ? ` → ${escapeHtml(h.severity)}` : '';
        const note = h.note ? ` — ${escapeHtml(h.note)}` : '';
        return `<li class="injury-hist-${h.type}"><span class="injury-hist-tag">${icon} ${label}</span> ${escapeHtml(h.date)}${sev}${note}</li>`;
      }).join('');
      return `<details class="injury-history"><summary>Verloop (${inj.history.length})</summary><ul>${items}</ul></details>`;
    }

    function getInjuries() {
      const raw = healthInput?.injuries;
      if (!raw) return [];
      const items = typeof raw === 'string'
        ? raw.split(/[;\n]/).map(s => s.trim()).filter(Boolean)
        : (Array.isArray(raw) ? raw : [raw]);
      return items.map(_normaliseInjury).filter(x => x && (x.area || x.description));
    }

    function renderInjuriesCard() {
      const injuries = getInjuries();
      const active = injuries.filter(i => i.status !== 'hersteld');

      let rows = '';
      if (injuries.length === 0) {
        rows = `<div class="injury-empty">Geen blessures geregistreerd — de coaches trainen je zonder beperkingen.</div>`;
      } else {
        rows = injuries.map(inj => {
          const meta = [];
          if (inj.severity) meta.push(inj.severity);
          if (inj.since) meta.push(`sinds ${inj.since}`);
          if (inj.worsened_on) meta.push(`verergerd op ${inj.worsened_on}${inj.worsened_note ? `: ${inj.worsened_note}` : ''}`);
          if (inj.improved_on) meta.push(`verbeterd op ${inj.improved_on}${inj.improved_note ? `: ${inj.improved_note}` : ''}`);
          if (inj.avoid.length) meta.push(`vermijden: ${inj.avoid.join(', ')}`);
          const opts = INJURY_STATUSES.map(s =>
            `<option value="${s}"${s === inj.status ? ' selected' : ''}>${s}</option>`).join('');
          const worsenBtn = inj.status !== 'hersteld'
            ? `<button class="injury-better" onclick="markInjuryImproved('${escapeHtml(inj.id)}')" title="Klachten verminderd">⬇ Beter</button>
               <button class="injury-worse" onclick="markInjuryWorsened('${escapeHtml(inj.id)}')" title="Klachten verergerd">⬆ Erger</button>`
            : '';
          return `<div class="injury-row${inj.status === 'hersteld' ? ' injury-resolved' : ''}${_isWorsened(inj) ? ' injury-worsened' : ''}">
            <div class="injury-main">
              <div class="injury-area">${escapeHtml(inj.area)}</div>
              ${inj.description ? `<div class="injury-desc">${escapeHtml(inj.description)}</div>` : ''}
              ${meta.length ? `<div class="injury-meta">${escapeHtml(meta.join(' · '))}</div>` : ''}
              ${_renderInjuryHistory(inj)}
            </div>
            <div class="injury-actions">
              ${worsenBtn}
              <select class="injury-status" onchange="setInjuryStatus('${escapeHtml(inj.id)}', this.value)">${opts}</select>
              <button class="injury-del" onclick="removeInjury('${escapeHtml(inj.id)}')" title="Verwijderen">✕</button>
            </div>
          </div>`;
        }).join('');
      }

      const sevOpts = ['<option value="">ernst…</option>']
        .concat(INJURY_SEVERITIES.map(s => `<option value="${s}">${s}</option>`)).join('');

      return `<div class="workflow-card" id="injuriesCard">
        <div class="workflow-title">🩹 Blessures${active.length ? ` <span class="injury-badge">${active.length}</span>` : ''}</div>
        <div class="workflow-desc">Wordt automatisch meegegeven aan álle AI-coaches: WOD-uitvoeringsplan, herstel-advies, Open Gym, thuistraining, hardloopschema en hardloop-review. Zet op <em>hersteld</em> om een blessure te bewaren als historie zonder dat de coaches er nog rekening mee houden.</div>
        <div class="injury-list">${rows}</div>
        <div class="injury-form">
          <input type="text" id="injuryArea" class="config-input" placeholder="Lichaamsdeel (bijv. linkerschouder)">
          <input type="text" id="injuryDesc" class="config-input" placeholder="Klacht (bijv. pijn bij overhead druk)">
          <div class="injury-form-row">
            <select id="injurySeverity" class="config-input injury-select">${sevOpts}</select>
            <input type="date" id="injurySince" class="config-input injury-select">
          </div>
          <input type="text" id="injuryAvoid" class="config-input" placeholder="Bewegingen vermijden, komma-gescheiden (optioneel)">
          <div class="workflow-footer">
            <button class="workflow-btn danger" onclick="addInjury()">+ Blessure toevoegen</button>
            <span id="injuryStatus" class="workflow-status"></span>
          </div>
        </div>
      </div>`;
    }

    function _refreshInjuriesCard(msg, color) {
      const card = document.getElementById('injuriesCard');
      if (card) card.outerHTML = renderInjuriesCard();
      const st = document.getElementById('injuryStatus');
      if (st && msg) {
        st.textContent = msg;
        st.style.color = color || '#00c853';
        setTimeout(() => { const e2 = document.getElementById('injuryStatus'); if (e2) e2.textContent = ''; }, 4000);
      }
    }

    async function _saveInjuries(list, msg) {
      const statusEl = document.getElementById('injuryStatus');
      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.style.color = 'var(--muted)'; }
      try {
        await _patchHealthInput({ injuries: list });
        _refreshInjuriesCard(msg || '✓ Opgeslagen');
      } catch(e) {
        if (statusEl) { statusEl.textContent = `Fout: ${e.message}`; statusEl.style.color = 'var(--accent2)'; }
        console.error(e);
      }
    }

    async function addInjury() {
      const area = (document.getElementById('injuryArea')?.value || '').trim();
      const desc = (document.getElementById('injuryDesc')?.value || '').trim();
      if (!area && !desc) {
        const st = document.getElementById('injuryStatus');
        if (st) { st.textContent = 'Vul minimaal een lichaamsdeel in'; st.style.color = 'var(--accent2)'; }
        return;
      }
      const avoid = (document.getElementById('injuryAvoid')?.value || '')
        .split(',').map(s => s.trim()).filter(Boolean);
      const entry = {
        id: String(Date.now()),
        area: area || desc,
        description: area ? desc : '',
        severity: document.getElementById('injurySeverity')?.value || '',
        status: 'actief',
        since: document.getElementById('injurySince')?.value || new Date().toISOString().slice(0, 10),
        avoid,
        notes: '',
      };
      await _saveInjuries([...getInjuries(), entry], '✓ Blessure toegevoegd — coaches houden hier rekening mee');
    }

    async function setInjuryStatus(id, status) {
      const list = getInjuries().map(i => i.id === id ? { ...i, status } : i);
      await _saveInjuries(list, status === 'hersteld' ? '✓ Gemarkeerd als hersteld' : '✓ Status bijgewerkt');
    }

    function _todayLocal() {
      const d = new Date();
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }

    async function markInjuryImproved(id) {
      const inj = getInjuries().find(i => i.id === id);
      if (!inj) return;
      const note = prompt(`Klachten "${inj.area}" verminderd — wat merk je? (optioneel)`, '');
      if (note === null) return;  // geannuleerd
      // Ernst één stap omlaag (minimaal licht), status herstellend, verergering vervalt
      const idx = INJURY_SEVERITIES.indexOf(inj.severity);
      const severity = idx > 0 ? INJURY_SEVERITIES[idx - 1] : 'licht';
      const list = getInjuries().map(i => i.id === id
        ? { ...i, status: 'herstellend', severity, improved_on: _todayLocal(), improved_note: note.trim(),
            worsened_on: '', worsened_note: '',
            history: [...i.history, { date: _todayLocal(), type: 'beter', note: note.trim(), severity }] }
        : i);
      await _saveInjuries(list, `✓ Verbetering gemeld — ernst nu ${severity}, status herstellend`);
    }

    async function markInjuryWorsened(id) {
      const inj = getInjuries().find(i => i.id === id);
      if (!inj) return;
      const note = prompt(`Klachten "${inj.area}" verergerd — wat merk je? (optioneel)`, '');
      if (note === null) return;  // geannuleerd
      const today = _todayLocal();
      // Ernst één stap omhoog (geen ernst → matig)
      const idx = INJURY_SEVERITIES.indexOf(inj.severity);
      const severity = INJURY_SEVERITIES[Math.min(idx < 0 ? 1 : idx + 1, INJURY_SEVERITIES.length - 1)];
      const list = getInjuries().map(i => i.id === id
        ? { ...i, status: 'actief', severity, worsened_on: today, worsened_note: note.trim(),
            improved_on: '', improved_note: '',
            history: [...i.history, { date: today, type: 'erger', note: note.trim(), severity }] }
        : i);
      await _saveInjuries(list, `✓ Verergerd gemeld — ernst nu ${severity}, coaches schalen verder terug`);
    }

    async function removeInjury(id) {
      const before = getInjuries();
      const inj = before.find(i => i.id === id);
      if (!inj) return;
      if (!(await askConfirm(`"${inj.area}" verwijderen?`, 'Verwijderen', { danger: true }))) return;
      await _saveInjuries(before.filter(i => i.id !== id), '✓ Verwijderd');
      showToast(`"${inj.area}" verwijderd`, {
        duration: 7000, actionLabel: 'Ongedaan maken',
        onAction: () => _saveInjuries([...getInjuries().filter(i => i.id !== id), inj], '✓ Teruggezet'),
      });
    }

