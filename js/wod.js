    // wod.js — Gist-bestanden parsen, WOD-secties, workout-log en WOD-overrides.

    function stripHtml(html) {
      const div = document.createElement('div');
      div.innerHTML = html;
      return div.textContent || div.innerText || '';
    }

    function formatAdviceTimestamp(isoStr) {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      const days = ['zo','ma','di','wo','do','vr','za'];
      const months = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'];
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} ${hh}:${mm}`;
    }

    // GitHub kapt gist-bestanden boven ~1 MB af: `truncated: true` en een
    // onvolledige `content` die niet meer als JSON te parsen is. Zonder deze stap
    // verdwijnen bijvoorbeeld alle WOD's stilletjes uit de kaarten. Haal de
    // volledige inhoud in dat geval alsnog op via raw_url.
    async function hydrateTruncatedFiles(gist, authHeaders) {
      const files = (gist && gist.files) || {};
      await Promise.all(Object.values(files).map(async f => {
        if (!f || !f.raw_url) return;
        if (!f.truncated && typeof f.content === 'string' && f.content.length > 0) return;
        // Eerst zónder token: gist.githubusercontent.com staat geen Authorization-
        // header toe in een cross-origin verzoek (CORS-preflight faalt), en de
        // raw_url bevat het Gist-ID al. Pas als dat mislukt mét token proberen.
        const attempts = [{}, authHeaders || {}].filter((h, i) => i === 0 || Object.keys(h).length);
        for (const headers of attempts) {
          try {
            const r = await fetch(f.raw_url, { headers });
            if (r.ok) { f.content = await r.text(); f.truncated = false; return; }
            console.warn(`Gist-bestand ${f.filename}: raw_url gaf ${r.status}`);
          } catch (e) {
            console.warn(`Gist-bestand ${f.filename} kon niet volledig geladen worden:`, e);
          }
        }
        f._incomplete = true;
      }));
    }

    function parseGistFiles(gist) {
      // Parse all relevant files from a gist response (single network call)
      const files = gist.files || {};

      // workout_log.json
      const logFile = files['workout_log.json'];
      if (logFile) {
        try {
          const logData = JSON.parse(logFile.content);
          workoutLog = {};
          for (const entry of (logData.entries || [])) workoutLog[entry.date] = entry;
        } catch (e) { /* ignore */ }
      }

      // sugarwod_wod.json
      const wodFile = files['sugarwod_wod.json'];
      if (wodFile) {
        try {
          const data = JSON.parse(wodFile.content);
          wodByDate = data.by_date || {};
          workoutPlans = data.workout_plans || {};
          barbellLifts = data.barbell_lifts || {};
          barbellLiftsHistory = data.barbell_lifts_history || [];
          recoveryAdviceHistory = data.recovery_advice_history || [];
          recoveryAdvice = data.recovery_advice || null;
          recoveryAdviceGeneratedAt = data.recovery_advice_generated_at || null;
          workoutPlansGeneratedAt = data.workout_plans_generated_at || null;
          // Val terug op meest recente history-entry als vandaag geen advies beschikbaar is
          if (!recoveryAdvice && recoveryAdviceHistory.length > 0) {
            const latest = recoveryAdviceHistory[recoveryAdviceHistory.length - 1];
            recoveryAdvice = latest.advice || null;
            recoveryAdviceFromHistory = !!recoveryAdvice;
            if (recoveryAdviceFromHistory) recoveryAdviceGeneratedAt = latest.timestamp || null;
          }
          personalRecords = data.personal_records || [];
          benchmarkWorkouts = data.benchmark_workouts || [];
          stravaData = data.strava_data || null;
          intervalsData = data.intervals_data || null;
          withingsData = data.withings_data || null;
          environmentalData = data.environmental_data || null;
          deloadAlert = data.deload_alert || false;
          wodFetchedAt = data.fetched_at || null;
          sugarwodFetchedAt = data.sugarwod_fetched_at || null;

          const bsEl = document.getElementById('barbellStatus');
          if (bsEl) {
            const source = data.barbell_source;
            const liftCount = Object.keys(barbellLifts).length;
            if (source === 'scraper') {
              bsEl.textContent = `Barbell maxima: ${liftCount} lifts live opgehaald via SugarWOD`;
              bsEl.className = 'barbell-status ok';
            } else if (source === 'fallback') {
              bsEl.textContent = `Barbell maxima: fallback gebruikt (${liftCount} lifts) — scraper kon niet inloggen`;
              bsEl.className = 'barbell-status fallback';
            } else {
              bsEl.textContent = `Barbell maxima: ${liftCount} lifts`;
              bsEl.className = 'barbell-status';
            }
          }
        } catch (e) { console.warn('sugarwod_wod.json kon niet gelezen worden:', e); }
      }

      // health_input.json
      const healthFile = files['health_input.json'];
      if (healthFile) {
        try {
          const h = JSON.parse(healthFile.content) || {};
          healthInput = h;
          healthHistory = h.history || [];
        } catch(e) {}
      }

      // sportbit_state.json — class_capacity
      const stateFile = files['sportbit_state.json'];
      if (stateFile) {
        try {
          const st = JSON.parse(stateFile.content);
          classCapacity = st.class_capacity || {};
          exclusions = st.exclusions || {};
          familyBookings = st.family_bookings || {};
          vacations = Array.isArray(st.vacations) ? st.vacations : [];
        } catch(e) {}
      }

      // personal_events.json
      const personalEventsFile = files['personal_events.json'];
      if (personalEventsFile) {
        try {
          const pe = JSON.parse(personalEventsFile.content);
          const raw = pe.events || [];
          const seenKeys = new Set();
          personalEvents = raw.filter(e => {
            const key = `${e.title}||${e.date}||${e.time || ''}`;
            if (seenKeys.has(key)) return false;
            seenKeys.add(key);
            return true;
          });
        } catch(e) { personalEvents = []; }
      } else {
        personalEvents = [];
      }

      // running_plan.json
      const runningPlanFile = files['running_plan.json'];
      if (runningPlanFile) {
        try { runningPlanData = JSON.parse(runningPlanFile.content); } catch(e) {}
      }

      // running_analysis.json
      const runningAnalysisFile = files['running_analysis.json'];
      if (runningAnalysisFile) {
        try { runningAnalysisData = JSON.parse(runningAnalysisFile.content); } catch(e) { runningAnalysisData = null; }
      } else {
        runningAnalysisData = null;
      }

      // open_gym_program.json
      const openGymFile = files['open_gym_program.json'];
      if (openGymFile) {
        try { openGymProgram = JSON.parse(openGymFile.content); } catch(e) {}
      }

      // home_workout_log.json
      const hwFile = files['home_workout_log.json'];
      if (hwFile) {
        try {
          const hwData = JSON.parse(hwFile.content);
          homeWorkoutLog = {};
          for (const entry of (hwData.entries || [])) homeWorkoutLog[entry.date] = entry;
        } catch(e) {}
      }

      // home_workout_plan.json (AI-gegenereerd dagelijks plan)
      const hwPlanFile = files['home_workout_plan.json'];
      if (hwPlanFile) {
        try { homeWorkoutPlan = JSON.parse(hwPlanFile.content); } catch(e) { homeWorkoutPlan = null; }
      }

      // workflow_status.json (mislukte runs, geschreven door notify_failure.py)
      try { workflowStatus = JSON.parse(files['workflow_status.json']?.content || '{}') || {}; } catch(e) { workflowStatus = {}; }

      // weekly_review.json (weekly_review.py)
      try { weeklyReview = JSON.parse(files['weekly_review.json']?.content || 'null'); } catch(e) { weeklyReview = null; }

      // workout_overrides.json
      const overridesFile = files['workout_overrides.json'];
      if (overridesFile) {
        try { workoutOverrides = JSON.parse(overridesFile.content) || {}; } catch(e) { workoutOverrides = {}; }
      } else {
        workoutOverrides = {};
      }
    }

    async function loadWod(gistId) {
      // Legacy: kept for compatibility but now just re-fetches and calls parseGistFiles
      currentGistId = gistId;
      const el = document.getElementById('wod-status');
      const token = document.getElementById('githubToken').value.trim();
      const authHeaders = token ? { Authorization: `token ${token}` } : {};
      try {
        const resp = await fetch(`https://api.github.com/gists/${gistId}`, { headers: authHeaders });
        if (!resp.ok) { if (el) el.textContent = `WOD: API fout ${resp.status}`; return; }
        const gist = await resp.json();
        await hydrateTruncatedFiles(gist, authHeaders);
        parseGistFiles(gist);
        const n = Object.keys(wodByDate).length;
        if (el) el.textContent = n > 0 ? `WOD geladen voor ${n} dag(en)` : 'WOD: geen workouts in by_date (fetch mislukt?)';
      } catch (e) { if (el) el.textContent = `WOD fout: ${e.message}`; }
    }

    function getMainWods(date) {
      return (wodByDate[date] || []).filter(w =>
        w.description || MAIN_KEYWORDS.some(k => (w.title || '').toLowerCase().includes(k))
      );
    }

    function renderLogSection(date, customWods) {
      const entry = workoutLog[date];
      const mainWods = deduplicateWods(customWods || wodByDate[date] || []);
      const checkedTitles = entry ? (entry.workouts_done || []) : [];
      const existingNotes = entry ? (entry.notes || '') : '';

      const checkboxes = mainWods.map(w => {
        const isChecked = checkedTitles.includes(w.title);
        return `<label class="log-checkbox${isChecked ? ' checked' : ''}">
          <input type="checkbox" data-date="${date}" value="${escapeHtml(w.title)}"${isChecked ? ' checked' : ''}
            onchange="this.closest('.log-checkbox').classList.toggle('checked', this.checked)">
          ${escapeHtml(w.title)}
        </label>`;
      }).join('');

      const savedLabel = entry ? `<span class="log-status ok" id="log-status-${date}">✓ Opgeslagen</span>` :
                                  `<span class="log-status" id="log-status-${date}"></span>`;

      return `<div class="log-section">
        <div class="log-section-title">Wat heb je gedaan?</div>
        ${mainWods.length > 0
          ? `<div class="log-checkboxes" id="log-checks-${date}">${checkboxes}</div>`
          : `<div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.6rem">Geen workouts bekend voor deze dag</div>`}
        <textarea class="log-textarea" id="log-notes-${date}" placeholder="Gewichten & notities (bijv. Deadlift 60kg, Box Jump step-down…)">${escapeHtml(existingNotes)}</textarea>
        <div class="log-actions">
          ${savedLabel}
          <button class="log-save-btn" onclick="saveWorkoutLog('${date}')">Opslaan</button>
        </div>
      </div>`;
    }

    async function saveWorkoutLog(date) {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById(`log-status-${date}`);

      if (!token) {
        if (statusEl) { statusEl.textContent = '⚠ Voer eerst een GitHub Token in'; statusEl.className = 'log-status err'; }
        return;
      }

      // Collect checked workouts
      const checks = document.querySelectorAll(`#log-checks-${date} input[type="checkbox"]:checked`);
      const workoutsDone = Array.from(checks).map(cb => cb.value);

      const notes = (document.getElementById(`log-notes-${date}`) || {}).value || '';

      const newEntry = {
        date,
        workouts_done: workoutsDone,
        notes,
        logged_at: new Date().toISOString(),
      };

      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.className = 'log-status'; }

      try {
        // Fetch current log
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` },
        });
        if (!resp.ok) throw new Error(`GitHub API ${resp.status}`);
        const gist = await resp.json();

        let entries = [];
        const existing = gist.files['workout_log.json'];
        if (existing) {
          try { entries = JSON.parse(existing.content).entries || []; } catch(e) {}
        }

        // Replace entry for this date
        entries = entries.filter(e => e.date !== date);
        entries.push(newEntry);
        entries.sort((a, b) => b.date.localeCompare(a.date));

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: {
            Authorization: `token ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            files: { 'workout_log.json': { content: JSON.stringify({ entries }, null, 2) } }
          }),
        });

        if (!patch.ok) throw new Error(`Opslaan mislukt: ${patch.status}`);

        workoutLog[date] = newEntry;
        if (statusEl) { statusEl.textContent = '✓ Opgeslagen'; statusEl.className = 'log-status ok'; }
      } catch(e) {
        if (statusEl) { statusEl.textContent = `❌ ${e.message}`; statusEl.className = 'log-status err'; }
      }
    }

    function renderPastCard(item, delay) {
      const wods = wodByDate[item.date] || [];
      const hasWod = wods.length > 0;
      const eventId = item.event_id || '';
      const metaHtml = `<div class="card-meta">
        <span class="card-time">${item.time}</span>
        ${renderMonthCountBadge(item)}
      </div>`;

      const logHtml = renderLogSection(item.date);
      const stravaHtml = renderStravaBlock(item.date, 'non-run');

      const nietGedaanBtn = eventId ? `
        <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid var(--border);display:flex;justify-content:flex-end">
          <button class="niet-gedaan-btn" id="ng-${eventId}"
            onclick="markNietGedaan('${eventId}','${item.date}','${item.time}','${escapeHtml(item.title)}',this)">
            Niet gedaan
          </button>
        </div>` : '';

      // Open Gym: toon het gegenereerde programma, niet de CrossFit WOD
      const isOpenGym = (item.title || '').toLowerCase().includes('open gym');
      const prog = isOpenGym ? openGymProgramsByEventId[eventId] : null;
      if (prog) {
        // Extraheer ## secties uit de programma-markdown als log-checkboxes
        const openGymSections = (prog.program_markdown || '').split('\n')
          .filter(l => /^##\s/.test(l))
          .map(l => ({ title: l.replace(/^##\s+/, '').trim() }));
        const ts = prog.generated_at
          ? `<div class="ai-coach-timestamp">gegenereerd ${formatAdviceTimestamp(prog.generated_at)}</div>`
          : '';
        const focusBadge = prog.focus_summary
          ? `<div class="card-wod-preview" style="padding:0.25rem 0.8rem 0.1rem;font-size:0.72rem;color:var(--accent);opacity:0.85">${escapeHtml(prog.focus_summary)}</div>`
          : '';
        const openGymLogHtml = renderLogSection(item.date, openGymSections.length ? openGymSections : undefined);
        return `
          <div class="card has-wod" style="animation-delay:${delay}s">
            <div class="card-dot dot-active" style="background:#9b59b6;opacity:0.4"></div>
            <div class="card-info">
              <div class="card-header" onclick="toggleWod(this.closest('.card'), event)" style="cursor:pointer">
                <div class="card-header-left">
                  <div class="card-title">${escapeHtml(item.title)}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  <div class="card-date">${formatDate(item.date)}</div>
                  <div class="card-relative-day">${relativeDay(item.date)}</div>
                  <div class="wod-chevron">▾</div>
                </div>
              </div>
              ${focusBadge}
              <div class="card-wod">
                <div class="ai-coach-block" style="margin:0">
                  <div class="ai-coach-label">Open Gym Programma</div>
                  ${ts}
                  <div class="ai-coach-body">${safeMarkdown(prog.program_markdown)}</div>
                </div>
                ${stravaHtml}${openGymLogHtml}${nietGedaanBtn}
              </div>
            </div>
          </div>`;
      }

      const wodSections = hasWod ? deduplicateWods(wods).map(w => {
        const desc = stripHtml(w.description || '').trim();
        return `<div class="wod-section">
          <div class="wod-section-title">${w.title}</div>
          ${desc ? `<div class="wod-section-body">${desc}</div>` : ''}
        </div>`;
      }).join('') : '';

      return `
        <div class="card has-wod" style="animation-delay:${delay}s">
          <div class="card-dot dot-active" style="opacity:0.4"></div>
          <div class="card-info">
            <div class="card-header" onclick="toggleWod(this.closest('.card'), event)" style="cursor:pointer">
              <div class="card-header-left">
                <div class="card-title">${escapeHtml(item.title)}</div>
                ${metaHtml}
              </div>
              <div class="card-right">
                <div class="card-date">${formatDate(item.date)}</div>
                <div class="card-relative-day">${relativeDay(item.date)}</div>
                <div class="wod-chevron">▾</div>
              </div>
            </div>
            <div class="card-wod">${wodSections}${stravaHtml}${logHtml}${nietGedaanBtn}</div>
          </div>
        </div>`;
    }

    async function markNietGedaan(eventId, date, time, title, btn) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) {
        btn.textContent = '⚠ Token nodig';
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Opslaan…';
      try {
        // Fetch current state
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` },
        });
        if (!resp.ok) throw new Error(`GitHub API ${resp.status}`);
        const gist = await resp.json();
        const stateRaw = gist.files['sportbit_state.json']?.content;
        if (!stateRaw) throw new Error('sportbit_state.json niet gevonden');
        const state = JSON.parse(stateRaw);

        // Move event from signed_up to cancelled
        delete state.signed_up[eventId];
        state.cancelled = state.cancelled || {};
        state.cancelled[eventId] = {
          date, time, title,
          cancelled_at: new Date().toISOString(),
        };

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            files: { 'sportbit_state.json': { content: JSON.stringify(state, null, 2) } }
          }),
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt ${patch.status}`);

        // Hide the card visually
        btn.closest('.card').style.opacity = '0.4';
        btn.textContent = '✓ Verwijderd uit coach context';
      } catch(e) {
        btn.disabled = false;
        btn.textContent = `❌ ${e.message}`;
      }
    }

    async function markOngedaanGemaakt(eventId, date, time, title, btn) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) {
        btn.textContent = '⚠ Token nodig';
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Opslaan…';
      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` },
        });
        if (!resp.ok) throw new Error(`GitHub API ${resp.status}`);
        const gist = await resp.json();
        const stateRaw = gist.files['sportbit_state.json']?.content;
        if (!stateRaw) throw new Error('sportbit_state.json niet gevonden');
        const state = JSON.parse(stateRaw);

        // Move event from cancelled back to signed_up
        delete state.cancelled[eventId];
        state.signed_up = state.signed_up || {};
        state.signed_up[eventId] = {
          date, time, title,
          signed_up_at: new Date().toISOString(),
        };

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            files: { 'sportbit_state.json': { content: JSON.stringify(state, null, 2) } }
          }),
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt ${patch.status}`);

        btn.textContent = '✓ Hersteld';
        btn.closest('.card').style.opacity = '0.4';
      } catch(e) {
        btn.disabled = false;
        btn.textContent = `❌ ${e.message}`;
      }
    }

    async function _patchExclusions(updatedExclusions) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) throw new Error('Token nodig');
      const resp = await fetch(`https://api.github.com/gists/${currentGistId}`,
        { headers: { Authorization: `token ${token}` } });
      if (!resp.ok) throw new Error(`GitHub API ${resp.status}`);
      const gist = await resp.json();
      const state = JSON.parse(gist.files['sportbit_state.json']?.content || '{}');
      state.exclusions = updatedExclusions;
      const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: { 'sportbit_state.json': { content: JSON.stringify(state, null, 2) } } }),
      });
      if (!patch.ok) throw new Error(`Opslaan mislukt ${patch.status}`);
    }

    async function addExclusion(key, btn) {
      btn.disabled = true; btn.textContent = 'Opslaan…';
      try {
        exclusions[key] = { excluded_at: new Date().toISOString() };
        await _patchExclusions(exclusions);
        const card = btn.closest('.card');
        card.classList.add('cancelled');
        card.style.opacity = '0.55';
        card.querySelector('.card-dot').style.background = '#ff6b6b';
        card.querySelector('.card-dot').style.opacity = '0.7';
        card.querySelector('.card-meta span').outerHTML = '<span style="color:#ff6b6b">Overgeslagen</span>';
        btn.textContent = 'Toch inschrijven';
        btn.disabled = false;
        btn.onclick = () => removeExclusion(key, btn);
      } catch(e) {
        delete exclusions[key];
        btn.disabled = false; btn.textContent = `❌ ${e.message}`;
      }
    }

    async function removeExclusion(key, btn) {
      btn.disabled = true; btn.textContent = 'Opslaan…';
      try {
        delete exclusions[key];
        await _patchExclusions(exclusions);
        const card = btn.closest('.card');
        card.classList.remove('cancelled');
        card.style.opacity = '1';
        card.querySelector('.card-dot').style.background = 'var(--accent)';
        card.querySelector('.card-dot').style.opacity = '0.35';
        card.querySelector('.card-meta span').outerHTML = '<span style="color:var(--text-muted)">Nog niet ingeschreven</span>';
        btn.textContent = 'Overslaan';
        btn.disabled = false;
        btn.onclick = () => addExclusion(key, btn);
      } catch(e) {
        exclusions[key] = { excluded_at: new Date().toISOString() };
        btn.disabled = false; btn.textContent = `❌ ${e.message}`;
      }
    }

    const KNOWN_LIFTS = [
      'back squat','front squat','overhead squat',
      'deadlift','sumo deadlift',
      'bench press','shoulder press','overhead press','push press','push jerk','split jerk',
      'clean','hang clean','power clean','squat clean','clean and jerk','hang power clean',
      'snatch','hang snatch','power snatch','squat snatch','hang power snatch',
      'thruster','good morning','romanian deadlift','rdl',
    ];

    function renderWeightSuggestions(wods) {
      if (!Object.keys(barbellLifts).length) return '';
      const allText = wods.map(w => (w.title + ' ' + stripHtml(w.description || '')).toLowerCase()).join(' ');
      const found = KNOWN_LIFTS.filter(l => allText.includes(l));
      if (!found.length) return '';

      // Resolve lift name to barbellLifts key (case-insensitive partial match)
      const rows = found.map(liftName => {
        const key = Object.keys(barbellLifts).find(k => k.toLowerCase() === liftName ||
          k.toLowerCase().includes(liftName) || liftName.includes(k.toLowerCase()));
        if (!key) return null;
        const lifts = barbellLifts[key];
        const oneRM = lifts['1RM'];
        if (!oneRM) return null;
        const pcts = [70, 75, 80, 85, 90, 100, 105];
        const cols = pcts.map(p => {
          const kg = Math.round(oneRM * p / 100 / 2.5) * 2.5;
          const is1rm = p === 100;
          const style = is1rm
            ? `text-align:center;padding:3px 6px;color:#e8ff3c;font-weight:700`
            : `text-align:center;padding:3px 6px`;
          return `<td style="${style}">${kg}</td>`;
        }).join('');
        return `<tr><td style="padding:3px 8px 3px 0;color:#ccc;font-size:0.8rem">${key}</td>${cols}</tr>`;
      }).filter(Boolean);

      if (!rows.length) return '';
      const pctHeaders = [70, 75, 80, 85, 90, 100, 105].map(p => {
        const style = p === 100
          ? `text-align:center;padding:3px 6px;color:#e8ff3c;font-size:0.75rem;font-weight:700`
          : `text-align:center;padding:3px 6px;color:#888;font-size:0.75rem`;
        return `<th style="${style}">${p}%</th>`;
      }).join('');
      return `<div class="weight-suggestions">
        <div class="weight-suggestions-label">Gewichten (kg)</div>
        <table style="border-collapse:collapse;width:100%">
          <thead><tr><th></th>${pctHeaders}</tr></thead>
          <tbody>${rows.join('')}</tbody>
        </table>
      </div>`;
    }

    function getEffectiveWorkouts(date, wods) {
      const dayOverrides = workoutOverrides[date] || {};
      return wods.map(w => {
        const ov = dayOverrides[w.title];
        if (!ov) return { ...w, _overridden: false, _deleted: false, _overrideStale: false };
        const stale = ov.original_description !== (w.description || '') ||
                      ov.original_athlete_notes !== (w.athlete_notes || '');
        if (stale) return { ...w, _overridden: false, _deleted: false, _overrideStale: true };
        return {
          ...w,
          description: ov.description,
          athlete_notes: ov.athlete_notes,
          _overridden: true,
          _deleted: ov.deleted || false,
          _overrideStale: false,
        };
      });
    }

    function deduplicateWods(wods) {
      const seen = new Set();
      return wods.filter(w => {
        const key = w.title + '|||' + stripHtml(w.description || '').trim() + '|||' + (w.athlete_notes || '').trim();
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }

    function renderWodSections(wods, date) {
      const effective = getEffectiveWorkouts(date, deduplicateWods(wods));
      const visible = effective.filter(w => !w._deleted);
      const deleted = effective.filter(w => w._deleted);

      const sections = visible.map(w => {
        const desc = stripHtml(w.description || '').trim();
        const notes = (w.athlete_notes || '').trim();
        const notesHtml = notes ? `
          <div class="athlete-notes">
            <div class="athlete-notes-label">Athlete Notes</div>
            <div class="athlete-notes-body">${escapeHtml(notes)}</div>
          </div>` : '';
        const staleWarning = w._overrideStale
          ? `<div class="wod-override-badge stale">SugarWOD gewijzigd — aanpassing genegeerd</div>` : '';
        const overrideBadge = w._overridden && !w._overrideStale
          ? `<div class="wod-override-badge">aangepast</div>` : '';
        const editPanel = date ? buildWodEditPanel(date, w.title, w) : '';
        return `<div class="wod-section">
          <div class="wod-section-header">
            <div class="wod-section-title">${escapeHtml(w.title)}</div>
            ${date ? `<button class="wod-edit-btn" onclick="toggleWodEdit('${escapeHtml(date)}','${escapeHtml(w.title)}',event)" title="Bewerken">✎</button>` : ''}
          </div>
          ${staleWarning}${overrideBadge}
          ${desc ? `<div class="wod-section-body">${desc}</div>` : ''}
          ${notesHtml}
          ${editPanel}
        </div>`;
      }).join('');

      const deletedHtml = deleted.length > 0 ? (() => {
        const id = `wod-deleted-${date}`;
        const items = deleted.map(w => `
          <div class="wod-deleted-item">
            <span class="wod-deleted-title">${escapeHtml(w.title)}</span>
            <button class="wod-restore-btn" onclick="restoreWodSection('${escapeHtml(date)}','${escapeHtml(w.title)}',this)">Terugzetten</button>
          </div>`).join('');
        return `<div class="wod-deleted-toggle" onclick="document.getElementById('${id}').classList.toggle('open')">
          ${deleted.length} onderdeel${deleted.length > 1 ? 'en' : ''} verborgen ▾
        </div>
        <div id="${id}" class="wod-deleted-list">
          ${items}
        </div>`;
      })() : '';

      const weightHtml = renderWeightSuggestions(visible.length > 0 ? visible : wods);

      const plan = date && workoutPlans[date];
      const planTsStr = plan ? formatAdviceTimestamp(workoutPlansGeneratedAt) : '';
      const planTsHtml = planTsStr ? `<div class="ai-coach-timestamp">gegenereerd ${planTsStr}</div>` : '';
      const planHtml = plan ? `
        <div class="coach-plan">
          <div class="coach-plan-label">AI Coach Plan</div>
          ${planTsHtml}
          <div class="coach-plan-body">${safeMarkdown(plan)}</div>
        </div>` : '';

      return sections + deletedHtml + weightHtml + planHtml;
    }

    function _wodSafeKey(title) {
      return title.replace(/[^a-zA-Z0-9]/g, '_');
    }

    function buildWodEditPanel(date, title, workout) {
      const key = `${date}_${_wodSafeKey(title)}`;
      const desc = stripHtml(workout.description || '').trim();
      const notes = (workout.athlete_notes || '').trim();
      return `
        <div id="wod-edit-${key}" class="wod-edit-panel" onclick="event.stopPropagation()" style="display:none">
          <div class="add-event-fields">
            <div class="add-event-row">
              <span class="add-event-label">Beschrijving</span>
              <textarea class="add-event-input" id="wodDesc-${key}" rows="5" style="resize:vertical;font-family:monospace;font-size:0.78rem">${escapeHtml(desc)}</textarea>
            </div>
            <div class="add-event-row">
              <span class="add-event-label">Athlete Notes</span>
              <textarea class="add-event-input" id="wodNotes-${key}" rows="3" style="resize:vertical;font-size:0.78rem">${escapeHtml(notes)}</textarea>
            </div>
          </div>
          <div class="add-event-actions">
            <span class="add-event-status" id="wodStatus-${key}"></span>
            <button class="wod-delete-btn" onclick="deleteWodSection('${escapeHtml(date)}','${escapeHtml(title)}',this)">Verbergen</button>
            <button class="add-event-cancel-btn" onclick="toggleWodEdit('${escapeHtml(date)}','${escapeHtml(title)}',event)">Annuleren</button>
            <button class="add-event-save-btn" id="wodSaveBtn-${key}" onclick="saveWodOverride('${escapeHtml(date)}','${escapeHtml(title)}',this)">Opslaan</button>
          </div>
        </div>`;
    }

    function toggleWodEdit(date, title, e) {
      if (e) { e.stopPropagation(); e.preventDefault(); }
      const key = `${date}_${_wodSafeKey(title)}`;
      const panel = document.getElementById(`wod-edit-${key}`);
      if (!panel) return;
      const opening = panel.style.display === 'none';
      panel.style.display = opening ? 'block' : 'none';
      if (opening) requestAnimationFrame(() => panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    }

    async function saveWodOverride(date, title, btn) {
      const token = document.getElementById('githubToken').value.trim();
      const key = `${date}_${_wodSafeKey(title)}`;
      const statusEl = document.getElementById(`wodStatus-${key}`);
      const saveBtn = btn || document.getElementById(`wodSaveBtn-${key}`);

      if (!token) {
        if (statusEl) { statusEl.textContent = '⚠ Token nodig'; statusEl.className = 'add-event-status err'; }
        return;
      }

      const descEl = document.getElementById(`wodDesc-${key}`);
      const notesEl = document.getElementById(`wodNotes-${key}`);
      const newDesc = descEl ? descEl.value : '';
      const newNotes = notesEl ? notesEl.value.trim() : '';

      const originalWod = (wodByDate[date] || []).find(w => w.title === title);
      if (!originalWod) {
        if (statusEl) { statusEl.textContent = '⚠ Workout niet gevonden'; statusEl.className = 'add-event-status err'; }
        return;
      }

      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.className = 'add-event-status'; }
      if (saveBtn) saveBtn.disabled = true;

      if (!workoutOverrides[date]) workoutOverrides[date] = {};
      workoutOverrides[date][title] = {
        original_description: originalWod.description || '',
        original_athlete_notes: originalWod.athlete_notes || '',
        description: newDesc,
        athlete_notes: newNotes,
        deleted: false,
        modified_at: new Date().toISOString(),
      };

      try {
        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'workout_overrides.json': { content: JSON.stringify(workoutOverrides, null, 2) } } }),
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt: ${patch.status}`);

        if (statusEl) { statusEl.textContent = '✓ Opgeslagen'; statusEl.className = 'add-event-status ok'; }
        setTimeout(() => {
          const panel = document.getElementById(`wod-edit-${key}`);
          if (panel) panel.style.display = 'none';
          _rerenderCardWod(date);
        }, 600);
      } catch(err) {
        delete workoutOverrides[date][title];
        if (statusEl) { statusEl.textContent = `❌ ${err.message}`; statusEl.className = 'add-event-status err'; }
        if (saveBtn) saveBtn.disabled = false;
      }
    }

    async function deleteWodSection(date, title, btn) {
      const token = document.getElementById('githubToken').value.trim();
      const key = `${date}_${_wodSafeKey(title)}`;
      const statusEl = document.getElementById(`wodStatus-${key}`);

      if (!token) {
        if (statusEl) { statusEl.textContent = '⚠ Token nodig'; statusEl.className = 'add-event-status err'; }
        return;
      }

      const originalWod = (wodByDate[date] || []).find(w => w.title === title);
      if (!originalWod) return;

      if (btn) btn.disabled = true;

      if (!workoutOverrides[date]) workoutOverrides[date] = {};
      const existing = workoutOverrides[date][title] || {};
      workoutOverrides[date][title] = {
        original_description: originalWod.description || '',
        original_athlete_notes: originalWod.athlete_notes || '',
        description: existing.description || originalWod.description || '',
        athlete_notes: existing.athlete_notes || originalWod.athlete_notes || '',
        deleted: true,
        modified_at: new Date().toISOString(),
      };

      try {
        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'workout_overrides.json': { content: JSON.stringify(workoutOverrides, null, 2) } } }),
        });
        if (!patch.ok) throw new Error(`Verbergen mislukt: ${patch.status}`);
        _rerenderCardWod(date);
      } catch(err) {
        delete workoutOverrides[date][title];
        if (statusEl) { statusEl.textContent = `❌ ${err.message}`; statusEl.className = 'add-event-status err'; }
        if (btn) btn.disabled = false;
      }
    }

    async function restoreWodSection(date, title, btn) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) return;

      if (btn) btn.disabled = true;

      if (workoutOverrides[date]) delete workoutOverrides[date][title];

      try {
        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'workout_overrides.json': { content: JSON.stringify(workoutOverrides, null, 2) } } }),
        });
        if (!patch.ok) throw new Error(`Terugzetten mislukt: ${patch.status}`);
        _rerenderCardWod(date);
      } catch(err) {
        if (btn) btn.disabled = false;
      }
    }

    function _rerenderCardWod(date) {
      const wods = wodByDate[date] || [];
      if (wods.length === 0) return;
      const newSections = renderWodSections(wods, date);
      const envBadge = renderEnvBadge(date);
      document.querySelectorAll(`.card.has-wod[data-wod-date="${date}"]`).forEach(card => {
        const wod = card.querySelector('.card-wod');
        if (wod) wod.innerHTML = envBadge + newSections;
      });
    }

    // Koppelt het type van een handmatig personal event aan de activiteitstypes
    // (intervals.icu/Strava) die eronder getoond mogen worden. Gedeeld door
    // renderPersonalEventCard (coupling) en de orphan-detectie (dedup).
    const personalTypeKeywords = {
      'Hiken':        ['hike', 'walk', 'hiking', 'walking'],
      'Hardlopen':    ['run', 'running', 'trailrun', 'treadmill', 'jog'],
      'Fietsen':      ['ride', 'cycling', 'virtualride', 'ebikeride'],
      'Mountainbiken':['mountainbikeride', 'mtb', 'gravel', 'virtualride'],
      'Zwemmen':      ['swim', 'openwaterswim'],
      'SUPpen':       ['sup', 'stand', 'paddle', 'row', 'canoe'],
      'Yoga':         ['yoga', 'flexibility', 'stretching'],
      'Gym':          ['weighttraining', 'strength', 'weight', 'workout'],
      'CrossFit':     ['crossfit', 'workout', 'weight'],
    };

