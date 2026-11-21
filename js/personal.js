    // personal.js — Persoonlijke events: kaarten, bewerken, toevoegen en verwijderen.
    // ── Personal events ───────────────────────────────────────────────────

    // Wijst getrackte activiteiten 1-op-1 toe aan handmatige events op dezelfde dag wanneer
    // er meerdere events van hetzelfde type zijn, op basis van de dichtstbijzijnde starttijd.
    // Retourneert een Set van activity-id's voor dit event, of null als er niet
    // gepartitioneerd hoeft te worden (één event van dit type op de dag → toon alles).
    function assignedActivityIds(event) {
      const keywords = personalTypeKeywords[event.title] || null;
      if (!keywords) return null;
      const date = event.date;
      // Concurrerende events: zelfde datum, overlappende keywords.
      const group = personalEvents.filter(e => {
        if (e.date !== date) return false;
        const kw = personalTypeKeywords[e.title];
        return kw && kw.some(k => keywords.includes(k));
      });
      if (group.length <= 1) return null;

      // Bron kiezen zoals renderPersonalEventCard: intervals heeft voorrang.
      const ivActs = (((intervalsData?.activities || {}).by_date || {})[date] || [])
        .filter(a => keywords.some(k => (a.type || '').toLowerCase().includes(k)));
      let acts, idField;
      if (ivActs.length) { acts = ivActs; idField = 'intervals_id'; }
      else {
        acts = ((stravaData?.activities_by_date || {})[date] || [])
          .filter(a => keywords.some(k => (a.type || '').toLowerCase().includes(k)));
        idField = 'activity_id';
      }
      if (acts.length === 0) return new Set();

      const toMin = t => { if (!t) return null; const [h, m] = t.split(':').map(Number); return h * 60 + m; };
      // Deterministische volgorde (voor de tie-break en de fallback zonder tijden).
      const sortedGroup = [...group].sort((a, b) =>
        ((toMin(a.time) ?? Infinity) - (toMin(b.time) ?? Infinity)) || String(a.id).localeCompare(String(b.id)));
      const sortedActs = [...acts].sort((a, b) =>
        ((toMin(a.start_time) ?? Infinity) - (toMin(b.start_time) ?? Infinity)) || String(a[idField]).localeCompare(String(b[idField])));

      const assigned = new Set();
      sortedActs.forEach((act, i) => {
        const cands = sortedGroup.filter(e =>
          personalTypeKeywords[e.title].some(k => (act.type || '').toLowerCase().includes(k)));
        if (cands.length === 0) return;
        const at = toMin(act.start_time);
        let chosen;
        if (at == null || cands.every(e => toMin(e.time) == null)) {
          // Geen bruikbare tijden → verdeel deterministisch op index.
          chosen = cands[Math.min(i, cands.length - 1)];
        } else {
          chosen = cands.reduce((best, e) => {
            const d = Math.abs((toMin(e.time) ?? Infinity) - at);
            const bd = Math.abs((toMin(best.time) ?? Infinity) - at);
            return d < bd ? e : best;
          });
        }
        if (chosen.id === event.id) assigned.add(act[idField]);
      });
      return assigned;
    }

    function renderPersonalEventCard(event, delay) {
      const id = escapeHtml(event.id);
      const timeHtml = event.time ? `<span class="card-time" style="color:#4db8ff">${event.time}</span>` : '';
      const metaLabel = event.notes ? event.notes.split('\n')[0] : event.location;
      const locHtml  = metaLabel ? `<span> ${escapeHtml(metaLabel)}</span>` : '';
      const routeHtml = event.route ? `<div class="card-meta" style="margin-top:0.1rem"><span style="color:#7dd3fc">Route:</span> <span>${escapeHtml(event.route)}</span></div>` : '';
      const metaHtml = (timeHtml || locHtml) ? `<div class="card-meta">${timeHtml}${locHtml}</div>` : '';
      const deleteBtn = `<button class="personal-delete-btn" title="Verwijderen"
        onclick="event.stopPropagation();deletePersonalEvent('${id}',this)">✕</button>`;
      const editBtn = `<button class="personal-edit-btn" title="Wijzigen"
        onclick="togglePersonalEventEdit('${id}',event)">✎</button>`;
      const notesHtml = event.notes
        ? `<div class="card-wod"><div style="font-size:0.82rem;color:#b0ccf0;white-space:pre-wrap;line-height:1.6">${escapeHtml(event.notes)}</div></div>`
        : '';

      // Koppel workout data van intervals.icu/Strava als de datum vandaag of eerder is
      const todayStr = new Date().toISOString().slice(0, 10);
      let activityBlockHtml = '';
      if (event.date <= todayStr) {
        const keywords = personalTypeKeywords[event.title] || null;
        const allowIds = keywords ? assignedActivityIds(event) : null;
        const intervalsHtml = renderIntervalsBlock(event.date, null, keywords, null, allowIds);
        activityBlockHtml = intervalsHtml || renderStravaBlock(event.date, null, keywords, null, allowIds);
      }

      const hasContent = event.notes || activityBlockHtml;
      const hasWod = hasContent ? ' has-wod' : '';
      const clickAttr = hasContent ? ' onclick="toggleWod(this, event)"' : '';
      const chevron = hasContent ? `<div class="wod-chevron" style="color:#4db8ff">▾</div>` : '';
      const wodContent = hasContent
        ? `<div class="card-wod">${event.notes ? `<div style="font-size:0.82rem;color:#b0ccf0;white-space:pre-wrap;line-height:1.6">${escapeHtml(event.notes)}</div>` : ''}${activityBlockHtml}</div>`
        : '';

      return `
        <div class="card${hasWod}" data-event-id="${id}" style="animation-delay:${delay}s"${clickAttr}>
          <div class="card-dot dot-personal"></div>
          <div class="card-info">
            <div class="card-header">
              <div class="card-header-left">
                <div class="card-title">${escapeHtml(event.title)}</div>
                ${metaHtml}
                ${routeHtml}
              </div>
              <div class="card-right">
                <div class="card-date" style="color:#4db8ff">${formatDate(event.date)}</div>
                <div class="card-relative-day">${relativeDay(event.date)}</div>
                <div style="display:flex;gap:0.3rem;align-items:center">${editBtn}${deleteBtn}${chevron}</div>
              </div>
            </div>
            ${wodContent}
            ${buildPersonalEditPanel(event)}
          </div>
        </div>`;
    }

    function buildPersonalEditPanel(event) {
      const id = escapeHtml(event.id);
      const knownTypes = ['Hardlopen','Hiken','SUPpen','Zwemmen','Fietsen','Mountainbiken','Yoga','Gym','CrossFit'];
      const isCustom = !knownTypes.includes(event.title);
      const opts = [...knownTypes, 'Anders'].map(v => {
        const sel = (v === 'Anders' ? isCustom : event.title === v) ? ' selected' : '';
        return `<option value="${v}"${sel}>${v}</option>`;
      }).join('');
      return `
        <div id="personal-edit-${id}" class="personal-edit-panel" onclick="event.stopPropagation()" style="display:none">
          <div class="add-event-fields">
            <div class="add-event-row">
              <span class="add-event-label">Activiteit</span>
              <select class="add-event-input" id="editTitle-${id}" onchange="handleEditTitleChange(this,'${id}')">
                <option value="">— Kies type —</option>
                ${opts}
              </select>
            </div>
            <div class="add-event-row" id="editCustomRow-${id}" style="display:${isCustom ? 'flex' : 'none'}">
              <span class="add-event-label"></span>
              <input type="text" class="add-event-input" id="editTitleCustom-${id}" value="${isCustom ? escapeHtml(event.title) : ''}" placeholder="Eigen naam" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Datum</span>
              <input type="date" class="add-event-input" id="editDate-${id}" value="${escapeHtml(event.date)}" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Tijd</span>
              <input type="time" class="add-event-input" id="editTime-${id}" value="${escapeHtml(event.time || '')}" />
            </div>
            <div class="add-event-row" id="editRouteRow-${id}" style="display:${event.title === 'Mountainbiken' ? 'flex' : 'none'}">
              <span class="add-event-label">Route</span>
              <input type="text" class="add-event-input" id="editRoute-${id}" value="${escapeHtml(event.route || '')}" placeholder="Bijv. Veluwe Noord lus" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Locatie</span>
              <input type="text" class="add-event-input" id="editLocation-${id}" value="${escapeHtml(event.location || '')}" placeholder="Optioneel" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Notities</span>
              <textarea class="add-event-input" id="editNotes-${id}" rows="2" style="resize:vertical">${escapeHtml(event.notes || '')}</textarea>
            </div>
          </div>
          <div class="add-event-actions">
            <span class="add-event-status" id="editStatus-${id}"></span>
            <button class="add-event-cancel-btn" onclick="togglePersonalEventEdit('${id}',event)">Annuleren</button>
            <button class="add-event-save-btn" id="editSaveBtn-${id}" onclick="savePersonalEventEdit('${id}',this)">Opslaan</button>
          </div>
        </div>`;
    }

    function togglePersonalEventEdit(eventId, e) {
      if (e) { e.stopPropagation(); e.preventDefault(); }
      const card = e && e.target && e.target.closest('[data-event-id]');
      const panel = card ? card.querySelector('.personal-edit-panel')
                         : document.querySelector(`[data-event-id="${eventId}"] .personal-edit-panel`);
      if (!panel) return;
      const opening = panel.style.display === 'none';
      panel.style.display = opening ? 'block' : 'none';
      if (opening) requestAnimationFrame(() => panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    }

    function handleEditTitleChange(sel, eventId) {
      const card = sel.closest('[data-event-id]');
      const customRow = card ? card.querySelector(`#editCustomRow-${eventId}`) : document.getElementById('editCustomRow-' + eventId);
      if (customRow) customRow.style.display = sel.value === 'Anders' ? 'flex' : 'none';
      const routeRow = card ? card.querySelector(`#editRouteRow-${eventId}`) : document.getElementById('editRouteRow-' + eventId);
      if (routeRow) routeRow.style.display = sel.value === 'Mountainbiken' ? 'flex' : 'none';
    }

    async function savePersonalEventEdit(eventId, btn) {
      const token = document.getElementById('githubToken').value.trim();
      const card = btn && btn.closest('[data-event-id]');
      const q = id => card ? card.querySelector('#' + id) : document.getElementById(id);
      const statusEl = q('editStatus-'  + eventId);
      const saveBtn  = btn || q('editSaveBtn-' + eventId);

      if (!token) {
        if (statusEl) { statusEl.textContent = '⚠ Token nodig'; statusEl.className = 'add-event-status err'; }
        return;
      }

      const titleSel = q('editTitle-' + eventId);
      let title = titleSel ? titleSel.value : '';
      if (title === 'Anders') title = (q('editTitleCustom-' + eventId)?.value || '').trim();
      const date     = (q('editDate-'     + eventId)?.value || '').trim();
      const time     = (q('editTime-'     + eventId)?.value || '').trim();
      const route    = (q('editRoute-'    + eventId)?.value || '').trim();
      const location = (q('editLocation-' + eventId)?.value || '').trim();
      const notes    = (q('editNotes-'    + eventId)?.value || '').trim();

      if (!title) {
        if (statusEl) { statusEl.textContent = '⚠ Kies een activiteit'; statusEl.className = 'add-event-status err'; }
        return;
      }
      if (!date) {
        if (statusEl) { statusEl.textContent = '⚠ Kies een datum'; statusEl.className = 'add-event-status err'; }
        return;
      }

      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.className = 'add-event-status'; }
      if (saveBtn)  saveBtn.disabled = true;

      const idx = personalEvents.findIndex(e => e.id === eventId);
      if (idx === -1) {
        if (statusEl) { statusEl.textContent = '⚠ Event niet gevonden'; statusEl.className = 'add-event-status err'; }
        if (saveBtn) saveBtn.disabled = false;
        return;
      }

      const original = { ...personalEvents[idx] };
      const updated  = { id: eventId, title, date, created_at: original.created_at };
      if (time)     updated.time     = time;
      if (route)    updated.route    = route;
      if (location) updated.location = location;
      if (notes)    updated.notes    = notes;
      personalEvents[idx] = updated;

      try {
        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'personal_events.json': { content: JSON.stringify({ events: personalEvents }, null, 2) } } }),
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt: ${patch.status}`);

        if (statusEl) { statusEl.textContent = '✓ Opgeslagen'; statusEl.className = 'add-event-status ok'; }
        setTimeout(() => {
          rerenderUpcomingCards();
          document.querySelectorAll(`[data-event-id="${eventId}"]`).forEach(el => {
            if (!el.closest('#upcomingCards')) {
              const tmp = document.createElement('div');
              tmp.innerHTML = renderPersonalEventCard(updated, 0);
              el.replaceWith(tmp.firstElementChild);
            }
          });
        }, 500);

      } catch(err) {
        personalEvents[idx] = original;
        if (statusEl) { statusEl.textContent = `❌ ${err.message}`; statusEl.className = 'add-event-status err'; }
        if (saveBtn) saveBtn.disabled = false;
      }
    }

    function showAddEventForm() {
      const wrapper = document.getElementById('addEventFormWrapper');
      if (!wrapper) return;
      if (wrapper.innerHTML) { wrapper.innerHTML = ''; return; }
      const today = new Date().toISOString().slice(0, 10);
      wrapper.innerHTML = `
        <div class="add-event-form">
          <div class="add-event-form-title">Nieuw event toevoegen</div>
          <div class="add-event-fields">
            <div class="add-event-row">
              <span class="add-event-label">Activiteit</span>
              <select class="add-event-input" id="newEventTitle" onchange="handleEventTitleChange(this)">
                <option value="">— Kies type —</option>
                <option value="Hardlopen">Hardlopen</option>
                <option value="Hiken">Hiken</option>
                <option value="SUPpen">SUPpen</option>
                <option value="Zwemmen">Zwemmen</option>
                <option value="Fietsen">Fietsen</option>
                <option value="Mountainbiken">Mountainbiken</option>
                <option value="Yoga">Yoga</option>
                <option value="Gym">Gym</option>
                <option value="CrossFit">CrossFit</option>
                <option value="Anders">Anders…</option>
              </select>
            </div>
            <div class="add-event-row" id="customTitleRow" style="display:none">
              <span class="add-event-label"></span>
              <input type="text" class="add-event-input" id="newEventTitleCustom" placeholder="Eigen naam" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Datum</span>
              <input type="date" class="add-event-input" id="newEventDate" value="${today}" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Tijd</span>
              <input type="time" class="add-event-input" id="newEventTime" />
            </div>
            <div class="add-event-row" id="routeRow" style="display:none">
              <span class="add-event-label">Route</span>
              <input type="text" class="add-event-input" id="newEventRoute" placeholder="Bijv. Veluwe Noord lus" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Locatie</span>
              <input type="text" class="add-event-input" id="newEventLocation" placeholder="Optioneel" />
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Notities</span>
              <textarea class="add-event-input" id="newEventNotes" placeholder="Optioneel" rows="2" style="resize:vertical"></textarea>
            </div>
          </div>
          <div class="add-event-actions">
            <span class="add-event-status" id="addEventStatus"></span>
            <button class="add-event-cancel-btn" onclick="hideAddEventForm()">Annuleren</button>
            <button class="add-event-save-btn" id="addEventSaveBtn" onclick="savePersonalEvent()">Toevoegen</button>
          </div>
        </div>`;
    }

    function hideAddEventForm() {
      const wrapper = document.getElementById('addEventFormWrapper');
      if (wrapper) wrapper.innerHTML = '';
    }

    function handleEventTitleChange(sel) {
      const row = document.getElementById('customTitleRow');
      if (row) row.style.display = sel.value === 'Anders' ? 'flex' : 'none';
      const routeRow = document.getElementById('routeRow');
      if (routeRow) routeRow.style.display = sel.value === 'Mountainbiken' ? 'flex' : 'none';
    }

    async function savePersonalEvent() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('addEventStatus');
      const saveBtn  = document.getElementById('addEventSaveBtn');

      if (!token) {
        if (statusEl) { statusEl.textContent = '⚠ Token nodig'; statusEl.className = 'add-event-status err'; }
        return;
      }

      const titleSel = document.getElementById('newEventTitle');
      let title = titleSel ? titleSel.value : '';
      if (title === 'Anders') {
        title = (document.getElementById('newEventTitleCustom')?.value || '').trim();
      }
      const date     = (document.getElementById('newEventDate')?.value     || '').trim();
      const time     = (document.getElementById('newEventTime')?.value     || '').trim();
      const route    = (document.getElementById('newEventRoute')?.value    || '').trim();
      const location = (document.getElementById('newEventLocation')?.value || '').trim();
      const notes    = (document.getElementById('newEventNotes')?.value    || '').trim();

      if (!title) {
        if (statusEl) { statusEl.textContent = '⚠ Kies een activiteit'; statusEl.className = 'add-event-status err'; }
        return;
      }
      if (!date) {
        if (statusEl) { statusEl.textContent = '⚠ Kies een datum'; statusEl.className = 'add-event-status err'; }
        return;
      }

      const duplicate = personalEvents.find(e => e.title === title && e.date === date && (e.time || '') === time);
      if (duplicate) {
        if (statusEl) { statusEl.textContent = `⚠ Er staat al een ${title} op ${date}`; statusEl.className = 'add-event-status err'; }
        return;
      }

      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.className = 'add-event-status'; }
      if (saveBtn)  saveBtn.disabled = true;

      const newEvent = { id: `personal_${Date.now()}`, title, date };
      if (time)     newEvent.time     = time;
      if (route)    newEvent.route    = route;
      if (location) newEvent.location = location;
      if (notes)    newEvent.notes    = notes;
      newEvent.created_at = new Date().toISOString();

      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` },
        });
        if (!resp.ok) throw new Error(`GitHub API ${resp.status}`);
        const gist = await resp.json();

        let events = [];
        const existing = gist.files['personal_events.json'];
        if (existing) {
          try { events = JSON.parse(existing.content).events || []; } catch(e) {}
        }

        // Drop events older than 30 days to keep the file tidy
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 30);
        const cutoffStr = cutoff.toISOString().slice(0, 10);
        events = events.filter(e => e.date >= cutoffStr);
        events.push(newEvent);
        events.sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'personal_events.json': { content: JSON.stringify({ events }, null, 2) } } }),
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt: ${patch.status}`);

        personalEvents = events;
        if (statusEl) { statusEl.textContent = '✓ Toegevoegd — naar Google Agenda…'; statusEl.className = 'add-event-status ok'; }

        // Sync naar Google Agenda via workflow
        const gcalToken = document.getElementById('githubToken')?.value.trim();
        if (gcalToken) {
          _dispatchRaw(gcalToken, 'sync_to_gcal.yml', {}).catch(() => {});
        }

        setTimeout(() => {
          hideAddEventForm();
          rerenderUpcomingCards();
        }, 500);

      } catch(e) {
        if (statusEl) { statusEl.textContent = `❌ ${e.message}`; statusEl.className = 'add-event-status err'; }
        if (saveBtn)  saveBtn.disabled = false;
      }
    }

    async function _savePersonalEvents(events) {
      const token = document.getElementById('githubToken').value.trim();
      const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: { 'personal_events.json': { content: JSON.stringify({ events }, null, 2) } } }),
      });
      if (!patch.ok) throw new Error(`Opslaan mislukt: ${patch.status}`);
    }

    async function deletePersonalEvent(id, btn) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      const removed = personalEvents.find(e => e.id === id);
      if (!removed) return;

      btn.disabled = true;
      btn.textContent = '…';
      const before = personalEvents;
      try {
        personalEvents = personalEvents.filter(e => e.id !== id);
        await _savePersonalEvents(personalEvents);
        btn.closest('.card')?.remove();
        showToast(`"${removed.title}" verwijderd`, {
          duration: 7000, actionLabel: 'Ongedaan maken',
          onAction: async () => {
            try {
              personalEvents = [...personalEvents.filter(e => e.id !== id), removed];
              await _savePersonalEvents(personalEvents);
              rerenderUpcomingCards();
              showToast('✓ Teruggezet', { type: 'ok' });
            } catch (e) { showToast(`Terugzetten mislukt: ${e.message}`, { type: 'error' }); }
          },
        });
      } catch(e) {
        personalEvents = before;
        btn.disabled = false;
        btn.textContent = '✕';
        showToast(`Verwijderen mislukt: ${e.message}`, { type: 'error' });
      }
    }

    // Re-renders only the upcoming cards list (used after add/delete without full reload)
    let _upcomingCrossfit = [];
    let _pastCrossfit = [];
    function rerenderUpcomingCards() {
      const cardsEl = document.getElementById('upcomingCards');
      if (!cardsEl) return;
      const todayStr = new Date().toISOString().slice(0, 10);
      const combined = [
        ..._upcomingCrossfit.map(e => ({ ...e, _src: 'crossfit' })),
        ...personalEvents
          .filter(e => isUpcoming(e.date, e.time || null))
          .map(e => ({ ...e, _src: 'personal' })),
      ].sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));

      if (combined.length === 0) {
        cardsEl.innerHTML = `<div class="empty"><span class="empty-icon">📅</span>Geen aankomende events</div>`;
        return;
      }
      cardsEl.innerHTML = combined.map((e, i) =>
        e._src === 'crossfit'
          ? renderCard(e, 'active', i * 0.05, wodByDate[e.date])
          : renderPersonalEventCard(e, i * 0.05)
      ).join('');
    }

    // ── end personal events ───────────────────────────────────────────────

