    const DAY_NL = ['Zo', 'Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za'];
    const MONTH_NL = ['jan', 'feb', 'mrt', 'apr', 'mei', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];

    // Load saved Gist ID
    const savedGistId = localStorage.getItem('sportbit_gist_id');
    if (savedGistId) {
      document.getElementById('gistId').value = savedGistId;
      loadData();
    }

    function formatDate(dateStr) {
      const d = new Date(dateStr + 'T00:00:00');
      return `${DAY_NL[d.getDay()]} ${d.getDate()} ${MONTH_NL[d.getMonth()]}`;
    }

    function relativeDay(dateStr) {
      const today = new Date(); today.setHours(0,0,0,0);
      const d = new Date(dateStr + 'T00:00:00');
      const diff = Math.round((d - today) / 86400000);
      if (diff === 0) return 'today';
      if (diff === 1) return 'tomorrow';
      if (diff === -1) return 'yesterday';
      if (diff > 1) return `in ${diff} days`;
      return `${Math.abs(diff)} days ago`;
    }

    function isUpcoming(dateStr, timeStr) {
      const classStart = new Date(dateStr + 'T' + (timeStr || '00:00') + ':00');
      return classStart > new Date();
    }

    function renderCapacityBadge(date, time) {
      const key = `${date}_${time}`;
      const cap = classCapacity[key];
      if (!cap || !cap.max) return '';
      const pct = cap.current / cap.max;
      let cls = 'open';
      if (pct >= 1) cls = 'full';
      else if (pct >= 0.8) cls = 'near-full';
      return `<span class="capacity-badge ${cls}">${cap.current}/${cap.max}</span>`;
    }

    function renderCard(item, type, delay, wods) {
      const cancelled = type === 'cancelled';
      const metaHtml = `<div class="card-meta">
        <span class="card-time">${item.time}</span>
      </div>`;

      if (wods && wods.length > 0) {
        const sections = renderWodSections(wods, item.date);
        const envBadge = !cancelled ? renderEnvBadge(item.date) : '';
        return `
          <div class="card has-wod" style="animation-delay:${delay}s" onclick="toggleWod(this)">
            <div class="card-dot dot-active"></div>
            <div class="card-info">
              <div class="card-header">
                <div class="card-header-left">
                  <div class="card-title">${item.title}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  <div class="card-date">${formatDate(item.date)}</div>
                  <div class="card-relative-day">${relativeDay(item.date)}</div>
                  <div class="wod-chevron">▾</div>
                </div>
              </div>
              <div class="card-wod">${envBadge}${sections}</div>
            </div>
          </div>`;
      }

      const undoBtn = cancelled && item.event_id ? `
        <button class="niet-gedaan-btn" style="margin-top:0.5rem;font-size:0.75rem" id="undo-${item.event_id}"
          onclick="markOngedaanGemaakt('${item.event_id}','${item.date}','${item.time}','${escapeHtml(item.title)}',this)">
          Ongedaan maken
        </button>` : '';

      return `
        <div class="card ${cancelled ? 'cancelled' : ''}" style="animation-delay:${delay}s">
          <div class="card-dot ${cancelled ? 'dot-cancelled' : 'dot-active'}"></div>
          <div class="card-info">
            <div class="card-title">${item.title}</div>
            ${metaHtml}
            ${undoBtn}
          </div>
          <div class="card-right">
            <div class="card-date ${cancelled ? 'cancelled-date' : ''}">${formatDate(item.date)}</div>
            <div class="card-relative-day">${relativeDay(item.date)}</div>
          </div>
        </div>`;
    }

    // Registreer service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js');
    }

    // ── SugarWOD ──────────────────────────────────────────────

    let wodByDate = {};
    let workoutPlans = {};
    let barbellLifts = {};
    let barbellLiftsHistory = []; // [{date, lifts: {...}}]
    let recoveryAdvice = null;
    let recoveryAdviceHistory = []; // [{date, advice}] laatste 3 dagen
    let recoveryAdviceFromHistory = false; // true als advies uit history komt i.p.v. vandaag
    let personalRecords = [];
    let benchmarkWorkouts = [];
    let workoutLog = {};   // {date: entry} from workout_log.json
    let stravaData = null; // Strava activiteiten data
    let healthInput = {}; // Subjectieve hersteldata {slaap, energie, spierpijn, stress}
    let healthHistory = []; // [{date, slaap, energie, spierpijn, stress}]
    let classCapacity = {}; // {"YYYY-MM-DD_HH:MM": {current, max, checked_at}}
    let keukenbaasData = null; // {meals: [...], fetched_at}
    let mfpData = null;        // {diary: {by_date: {...}}, fetched_at}
    let personalEvents = []; // [{id, title, date, time?, location?, notes?, created_at}]
    let intervalsData = null;   // {wellness: {by_date: {...}}, activities: {by_date: {...}}, fetched_at}
    let withingsData = null;    // {measurements: [...], fetched_at}
    let deloadAlert = false;    // true als overtraining risico gedetecteerd
    let environmentalData = null; // {training_conditions: {...}, aqi: {...}, fetched_at}
    let runningPlanData = null; // {generated_at, week_number, workouts: [{date, type, name, description, total_duration_min}]}
    let activeChartLift = null;
    let liftChart = null;
    let currentGistId = '';

    const MAIN_KEYWORDS = ['metcon', 'weightlifting', 'team metcon', 'strength', 'conditioning'];

    // Load saved token
    const savedToken = localStorage.getItem('sportbit_github_token');
    if (savedToken) document.getElementById('githubToken').value = savedToken;

    document.getElementById('githubToken').addEventListener('change', () => {
      const t = document.getElementById('githubToken').value.trim();
      if (t) localStorage.setItem('sportbit_github_token', t);
    });

    function stripHtml(html) {
      const div = document.createElement('div');
      div.innerHTML = html;
      return div.textContent || div.innerText || '';
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
          // Val terug op meest recente history-entry als vandaag geen advies beschikbaar is
          if (!recoveryAdvice && recoveryAdviceHistory.length > 0) {
            const latest = recoveryAdviceHistory[recoveryAdviceHistory.length - 1];
            recoveryAdvice = latest.advice || null;
            recoveryAdviceFromHistory = !!recoveryAdvice;
          }
          personalRecords = data.personal_records || [];
          benchmarkWorkouts = data.benchmark_workouts || [];
          stravaData = data.strava_data || null;
          intervalsData = data.intervals_data || null;
          withingsData = data.withings_data || null;
          environmentalData = data.environmental_data || null;
          deloadAlert = data.deload_alert || false;

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
        } catch (e) { /* ignore */ }
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
        } catch(e) {}
      }

      // keukenbaas_meals.json
      const mealsFile = files['keukenbaas_meals.json'];
      if (mealsFile) {
        try { keukenbaasData = JSON.parse(mealsFile.content); } catch(e) {}
      }

      // myfitnesspal_nutrition.json
      const mfpFile = files['myfitnesspal_nutrition.json'];
      if (mfpFile) {
        try { mfpData = JSON.parse(mfpFile.content); } catch(e) {}
      }

      // personal_events.json
      const personalEventsFile = files['personal_events.json'];
      if (personalEventsFile) {
        try {
          const pe = JSON.parse(personalEventsFile.content);
          personalEvents = pe.events || [];
        } catch(e) { personalEvents = []; }
      } else {
        personalEvents = [];
      }

      // running_plan.json
      const runningPlanFile = files['running_plan.json'];
      if (runningPlanFile) {
        try { runningPlanData = JSON.parse(runningPlanFile.content); } catch(e) {}
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

    function renderLogSection(date) {
      const entry = workoutLog[date];
      const mainWods = wodByDate[date] || [];
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
      </div>`;

      const wodSections = hasWod ? wods.map(w => {
        const desc = stripHtml(w.description || '').trim();
        return `<div class="wod-section">
          <div class="wod-section-title">${w.title}</div>
          ${desc ? `<div class="wod-section-body">${desc}</div>` : ''}
        </div>`;
      }).join('') : '';

      const logHtml = renderLogSection(item.date);
      const stravaHtml = renderStravaBlock(item.date);

      // "Niet gedaan" button — marks this class as cancelled in the state so the
      // AI coach stops counting it as an attended session
      const nietGedaanBtn = eventId ? `
        <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid var(--border);display:flex;justify-content:flex-end">
          <button class="niet-gedaan-btn" id="ng-${eventId}"
            onclick="markNietGedaan('${eventId}','${item.date}','${item.time}','${escapeHtml(item.title)}',this)">
            Niet gedaan
          </button>
        </div>` : '';

      return `
        <div class="card has-wod" style="animation-delay:${delay}s">
          <div class="card-dot dot-active" style="opacity:0.4"></div>
          <div class="card-info">
            <div class="card-header" onclick="toggleWod(this.closest('.card'))" style="cursor:pointer">
              <div class="card-header-left">
                <div class="card-title">${item.title}</div>
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
        const pcts = [65, 70, 75, 80, 85, 90, 100, 105];
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
      const pctHeaders = [65, 70, 75, 80, 85, 90, 100, 105].map(p => {
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

    function renderWodSections(wods, date) {
      const sections = wods.map(w => {
        const desc = stripHtml(w.description || '').trim();
        const notes = (w.athlete_notes || '').trim();
        const notesHtml = notes ? `
          <div class="athlete-notes">
            <div class="athlete-notes-label">Athlete Notes</div>
            <div class="athlete-notes-body">${escapeHtml(notes)}</div>
          </div>` : '';
        return `<div class="wod-section">
          <div class="wod-section-title">${w.title}</div>
          ${desc ? `<div class="wod-section-body">${desc}</div>` : ''}
          ${notesHtml}
        </div>`;
      }).join('');

      const weightHtml = renderWeightSuggestions(wods);

      const plan = date && workoutPlans[date];
      const planHtml = plan ? `
        <div class="coach-plan">
          <div class="coach-plan-label">AI Coach Plan</div>
          <div class="coach-plan-body">${marked.parse(plan)}</div>
        </div>` : '';

      return sections + weightHtml + planHtml;
    }

    function renderStravaBlock(date) {
      if (!stravaData) return '';
      const acts = (stravaData.activities_by_date || {})[date];
      if (!acts || acts.length === 0) return '';
      return acts.map(act => {
        const dur     = act.duration_min ? `<span class="strava-stat"><strong>${act.duration_min}</strong> min</span>` : '';
        const elapsed = act.elapsed_min  ? `<span class="strava-stat">totaal <strong>${act.elapsed_min}</strong> min</span>` : '';
        const hr      = act.avg_hr   ? `<span class="strava-stat">gem.HR <strong>${Math.round(act.avg_hr)}</strong> bpm</span>` : '';
        const hrMax   = act.max_hr   ? `<span class="strava-stat">max.HR <strong>${Math.round(act.max_hr)}</strong> bpm</span>` : '';
        const cal     = act.calories ? `<span class="strava-stat"><strong>${Math.round(act.calories)}</strong> kcal</span>` : '';
        const suffer  = act.suffer_score       ? `<span class="strava-stat">RE <strong>${Math.round(act.suffer_score)}</strong></span>` : '';
        const rpe     = act.perceived_exertion ? `<span class="strava-stat">RPE <strong>${act.perceived_exertion}</strong></span>` : '';
        const name    = act.name ? ` — ${act.name}` : '';
        return `<div class="strava-block">
          <div class="strava-block-label">Strava${name}</div>
          ${dur}${elapsed}${hr}${hrMax}${cal}${suffer}${rpe}
        </div>`;
      }).join('');
    }

    function renderIntervalsBlock(date) {
      if (!intervalsData) return '';
      const acts = ((intervalsData.activities || {}).by_date || {})[date];
      if (!acts || acts.length === 0) return '';
      return acts.map(act => {
        const dur  = act.duration_min  ? `<span class="strava-stat"><strong>${act.duration_min}</strong> min</span>` : '';
        const hr   = act.avg_hr        ? `<span class="strava-stat">gem.HR <strong>${act.avg_hr}</strong> bpm</span>` : '';
        const hrMax= act.max_hr        ? `<span class="strava-stat">max.HR <strong>${act.max_hr}</strong> bpm</span>` : '';
        const cal  = act.calories      ? `<span class="strava-stat"><strong>${act.calories}</strong> kcal</span>` : '';
        const tl   = act.training_load != null ? `<span class="strava-stat">TL <strong>${Math.round(act.training_load)}</strong></span>` : '';
        const name = act.name || act.type || 'Activiteit';
        return `<div class="strava-block">
          <div class="strava-block-label">Intervals — ${name}</div>
          ${dur}${hr}${hrMax}${cal}${tl}
        </div>`;
      }).join('');
    }

    function renderRunningPlanSection() {
      if (!runningPlanData) return '';
      const workouts = runningPlanData.workouts || [];
      if (workouts.length === 0) return '';

      const today = new Date().toISOString().slice(0, 10);
      const weekBadge = runningPlanData.week_number
        ? `<span class="run-badge">Week ${runningPlanData.week_number}</span>` : '';

      const rows = workouts.map(s => {
        const dur = s.total_duration_min ? `${s.total_duration_min}min` : '';
        const meta = [formatDate(s.date), dur].filter(Boolean).join(' · ');
        const past = s.date < today ? ' style="opacity:0.55"' : '';
        return `<div class="run-item"${past}>
          <span class="run-title">🏃 ${escapeHtml(s.name || s.type || 'Run')}</span>
          <span class="run-meta">${escapeHtml(meta)}</span>
        </div>`;
      }).join('');

      // 5K voortgangsmeter
      const goal5kSec  = 26 * 60;  // 26:00
      const start5kSec = 28 * 60;  // 28:00 (startpunt)
      // Sanity check: schatting op basis van intervaldata kan onbetrouwbaar zijn.
      // Als de waarde > 32 min is, is de berekening fout (bijv. duurlooptempo meegenomen).
      const rawEst = runningPlanData.estimated_5k_seconds;
      const est5kSec = (rawEst && rawEst <= 32 * 60) ? rawEst : null;
      let progressHtml = '';
      if (est5kSec) {
        const clampedEst = Math.min(Math.max(est5kSec, goal5kSec), start5kSec);
        const pct = Math.round((start5kSec - clampedEst) / (start5kSec - goal5kSec) * 100);
        const estMins = Math.floor(est5kSec / 60);
        const estSecs = est5kSec % 60;
        const secLeft = Math.max(0, est5kSec - goal5kSec);
        progressHtml = `<div class="run-5k-progress">
          <div class="run-5k-labels">
            <span>5K doel: <strong>26:00</strong></span>
            <span style="color:#e8ff3c">Huidig: <strong>${estMins}:${String(estSecs).padStart(2,'0')}</strong></span>
          </div>
          <div class="run-5k-bar-track">
            <div class="run-5k-bar-fill" style="width:${pct}%"></div>
          </div>
          <div class="run-5k-sub">Nog ~${Math.floor(secLeft)}s te verbeteren · ${pct}% naar doel</div>
        </div>`;
      }

      return `<div class="run-block">
        <div class="run-block-label">Hardloopplan${weekBadge}</div>
        ${progressHtml}
        ${rows}
      </div>`;
    }

    function renderActivityCard(date, delay) {
      const acts = ((intervalsData?.activities || {}).by_date || {})[date] || [];
      const stravaActs = (stravaData?.activities_by_date || {})[date] || [];
      if (acts.length === 0 && stravaActs.length === 0) return '';

      // Gebruik intervals.icu data als die beschikbaar is; anders Strava
      const intervalsHtml = renderIntervalsBlock(date);
      // Strava alleen tonen als er geen intervals data is (voorkomt dubbeling)
      const stravaHtml = intervalsHtml ? '' : renderStravaBlock(date);
      if (!intervalsHtml && !stravaHtml) return '';

      const first = acts[0] || {};
      const title = first.name || first.type || (stravaActs[0]?.name) || 'Activiteit';

      const actualStartTime = (acts[0] || stravaActs[0])?.start_time;
      const plannedRun = runningPlanData
        ? (runningPlanData.workouts || []).find(s => s.date === date)
        : null;
      const plannedTime = plannedRun
        ? (plannedRun.time || (plannedRun.session === 'speed' ? '20:00' : '09:00'))
        : null;
      const timeToShow = actualStartTime || plannedTime;
      const metaHtml = timeToShow ? `<div class="card-meta"><span class="card-time">${timeToShow}</span></div>` : '';

      return `
        <div class="card has-wod" style="animation-delay:${delay}s">
          <div class="card-dot dot-active" style="opacity:0.4"></div>
          <div class="card-info">
            <div class="card-header" onclick="toggleWod(this.closest('.card'))" style="cursor:pointer">
              <div class="card-header-left">
                <div class="card-title">${title}</div>
                ${metaHtml}
              </div>
              <div class="card-right">
                <div class="card-date">${formatDate(date)}</div>
                <div class="card-relative-day">${relativeDay(date)}</div>
                <div class="wod-chevron">▾</div>
              </div>
            </div>
            <div class="card-wod">${intervalsHtml}${stravaHtml}</div>
          </div>
        </div>`;
    }

    function toggleSection(titleEl) {
      titleEl.classList.toggle('open');
      titleEl.nextElementSibling.classList.toggle('open');
    }

    function toggleWod(card) {
      const wod = card.querySelector('.card-wod');
      wod.style.display = wod.style.display === 'block' ? 'none' : 'block';
      card.classList.toggle('open');
    }


    // ── Sign-up data ──────────────────────────────────────────

    function buildSkeleton() {
      const stats = `<div class="stats" style="margin-bottom:2rem">
        ${[1,2,3].map(() => `<div class="stat skeleton skeleton-stat" style="height:80px"></div>`).join('')}
      </div>`;
      const cards = [1,2,3].map(i =>
        `<div class="skeleton skeleton-card" style="animation-delay:${i*0.1}s"></div>`
      ).join('');
      return stats +
        `<div class="skeleton skeleton-section-title" style="margin-bottom:0.8rem"></div>` +
        cards;
    }

    async function loadData() {
      const gistId = document.getElementById('gistId').value.trim();
      if (!gistId) return;

      localStorage.setItem('sportbit_gist_id', gistId);
      currentGistId = gistId;

      const content = document.getElementById('content');
      content.innerHTML = buildSkeleton();


      const token = document.getElementById('githubToken').value.trim();
      const authHeaders = token ? { Authorization: `token ${token}` } : {};

      try {
        // Single fetch — parse all files from one response
        const resp = await fetch(`https://api.github.com/gists/${gistId}`, { headers: authHeaders });
        if (!resp.ok) throw new Error(`GitHub API fout: ${resp.status}`);
        const gist = await resp.json();

        // Parse all file types from this single response
        parseGistFiles(gist);

        const stateFile = gist.files['sportbit_state.json'];
        if (!stateFile) throw new Error('sportbit_state.json niet gevonden in Gist');

        const state = JSON.parse(stateFile.content);
        // Include event_id in each item so the "Niet gedaan" button can patch the state
        const signedUp = Object.entries(state.signed_up || {}).map(([id, info]) => ({...info, event_id: id}));
        const cancelled = Object.entries(state.cancelled || {}).map(([id, info]) => ({...info, event_id: id}));

        signedUp.sort((a, b) => a.date.localeCompare(b.date));
        cancelled.sort((a, b) => b.date.localeCompare(a.date));

        const upcoming = signedUp.filter(e => isUpcoming(e.date, e.time));
        const past = signedUp.filter(e => !isUpcoming(e.date, e.time));


        document.getElementById('lastUpdated').textContent =
          new Date(gist.updated_at).toLocaleString('nl-NL');

        let html = '';

        // Unified recovery block (Garmin/Intervals.icu + Withings + subjectief gevoel)
        html += `<div id="recoveryTodayWrapper">${renderRecoveryTodayBlock()}</div>`;
        if (recoveryAdvice) {
          const adviceLabel = recoveryAdviceFromHistory
            ? `Coach Advies (${recoveryAdviceHistory[recoveryAdviceHistory.length - 1].date})`
            : 'Coach Advies Vandaag';
          html += `<div class="recovery-block">
            <div class="recovery-block-label">${adviceLabel}</div>
            <div class="recovery-block-body">${marked.parse(recoveryAdvice)}</div>
          </div>`;
        }

        // Meals block (Keukenbaas) en MFP worden na de Eerder-sectie getoond

        // Upcoming: CrossFit classes + personal events + running plan combined
        _upcomingCrossfit = upcoming;
        const todayForRun = new Date().toISOString().slice(0, 10);
        const cutoffRun = (() => { const d = new Date(); d.setDate(d.getDate() + 14); return d.toISOString().slice(0, 10); })();
        const upcomingPersonal = personalEvents.filter(e => isUpcoming(e.date, e.time || null));
        const upcomingRuns = runningPlanData
          ? (runningPlanData.workouts || [])
              .filter(s => {
                const t = s.time || (s.session === 'speed' ? '20:00' : '09:00');
                return isUpcoming(s.date, t) && s.date <= cutoffRun;
              })
              .map(s => ({ ...s, _src: 'run' }))
          : [];
        const allUpcoming = [
          ...upcoming.map(e => ({ ...e, _src: 'crossfit' })),
          ...upcomingPersonal.map(e => ({ ...e, _src: 'personal' })),
          ...upcomingRuns,
        ].sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));

        if (deloadAlert) {
          html += `<div class="deload-banner">⚠️ Herstelweek aanbevolen — je lichaam geeft overbelastingssignalen. Schaal WODs naar 60–70% en prioriteer slaap.</div>`;
        }
        html += `<div class="section-title">Aankomend <button class="add-event-btn" onclick="showAddEventForm()">+ Toevoegen</button></div>`;
        html += `<div id="addEventFormWrapper"></div>`;
        html += `<div class="cards" id="upcomingCards">`;
        if (allUpcoming.length === 0) {
          html += `<div class="empty"><span class="empty-icon">📅</span>Geen aankomende events</div>`;
        } else {
          allUpcoming.forEach((e, i) => {
            if (e._src === 'crossfit') html += renderCard(e, 'active', i * 0.05, wodByDate[e.date]);
            else if (e._src === 'run') html += renderRunEventCard(e, i * 0.05);
            else html += renderPersonalEventCard(e, i * 0.05);
          });
        }
        html += `</div>`;

        // Cancelled — only today + next 8 days
        const todayStr = new Date().toISOString().slice(0, 10);
        const maxDateStr = (() => { const d = new Date(); d.setDate(d.getDate() + 8); return d.toISOString().slice(0, 10); })();
        const recentCancelled = cancelled.filter(e => e.date >= todayStr && e.date <= maxDateStr);
        if (recentCancelled.length > 0) {
          html += `<div class="section-title">Uitgeschreven</div><div class="cards">`;
          recentCancelled.forEach((e, i) => html += renderCard(e, 'cancelled', i * 0.05));
          html += `</div>`;
        }

        // Past: CrossFit lessen + standalone activiteiten (intervals/Strava zonder les)
        {
          const classDates = new Set(signedUp.map(e => e.date));

          // Activiteitsdatums zonder bijbehorende les (laatste 21 dagen)
          const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 21);
          const cutoffStr = cutoff.toISOString().slice(0, 10);
          const activityDates = new Set([
            ...Object.keys((intervalsData?.activities || {}).by_date || {}),
            ...Object.keys((stravaData?.activities_by_date) || {}),
          ]);
          const orphanDates = Array.from(activityDates)
            .filter(d => !classDates.has(d) && d >= cutoffStr && d <= new Date().toISOString().slice(0, 10));

          // Bouw gecombineerde lijst: {type, date, item?}
          const pastRuns = runningPlanData
            ? (runningPlanData.workouts || []).filter(s => {
                const t = s.time || (s.session === 'speed' ? '20:00' : '09:00');
                // Skip if already shown as a recorded activity card
                return s.date >= cutoffStr && !isUpcoming(s.date, t) && !activityDates.has(s.date);
              })
            : [];
          const pastItems = [
            ...past.slice(-5).map(e => ({ type: 'class', date: e.date, item: e })),
            ...orphanDates.map(d => ({ type: 'activity', date: d })),
            ...pastRuns.map(s => ({ type: 'run', date: s.date, item: s })),
          ];
          pastItems.sort((a, b) => b.date.localeCompare(a.date));
          const pastSlice = pastItems.slice(0, 8); // max 8 kaarten

          if (pastSlice.length > 0) {
            html += `<div class="section-title">Eerder</div><div class="cards">`;
            pastSlice.forEach((entry, i) => {
              if (entry.type === 'class') {
                html += renderPastCard(entry.item, i * 0.05);
              } else if (entry.type === 'run') {
                html += renderRunEventCard(entry.item, i * 0.05);
              } else {
                html += renderActivityCard(entry.date, i * 0.05);
              }
            });
            html += `</div>`;
          }
        }

        // Voeding (Keukenbaas + MyFitnessPal) na Eerder-sectie
        const mealsHtml = renderMealsBlock();
        if (mealsHtml) html += mealsHtml;
        const mfpHtml = renderMfpBlock();
        if (mfpHtml) html += mfpHtml;

        // Barbell progressie (table + chart)
        if (Object.keys(barbellLifts).length > 0) {
          html += `<div class="section-title collapsible" onclick="toggleSection(this)">Kracht</div><div class="collapsible-body">${renderBarbellSection()}</div>`;
        }

        // Personal Records
        if (personalRecords.length > 0) {
          const sorted = [...personalRecords].sort((a, b) =>
            (b.date || '').localeCompare(a.date || '')
          );
          html += `<div class="section-title collapsible" onclick="toggleSection(this)">Persoonlijke Records</div><div class="collapsible-body"><div class="pr-list">`;
          sorted.forEach((pr, i) => {
            const dateLabel = pr.date ? formatPrDate(pr.date) : '—';
            html += `<div class="pr-item" style="animation-delay:${i * 0.03}s">
              <div class="pr-workout">${escapeHtml(pr.workout)}</div>
              ${pr.result ? `<div class="pr-result">${escapeHtml(pr.result)}</div>` : ''}
              ${pr.notes ? `<div class="pr-notes">${escapeHtml(pr.notes)}</div>` : ''}
              <div class="pr-date">${dateLabel}</div>
            </div>`;
          });
          html += `</div></div>`;
        }

        // Benchmark Workouts
        if (benchmarkWorkouts.length > 0) {
          html += `<div class="section-title collapsible" onclick="toggleSection(this)">Benchmark Workouts</div><div class="collapsible-body">` + renderBenchmarks(benchmarkWorkouts) + `</div>`;
        }

        // Hardloopplan
        const runningPlanHtml = renderRunningPlanSection();
        if (runningPlanHtml) {
          html += `<div class="section-title collapsible" onclick="toggleSection(this)">Hardloopplan</div>
                   <div class="collapsible-body">${runningPlanHtml}</div>`;
        }

        // Data bronnen inspector
        html += renderDataSourcesBlock();

        content.innerHTML = html;

        // Initialize chart after DOM is ready
        if (Object.keys(barbellLifts).length > 0) {
          initBarbellChart();
        }

      } catch (e) {
        content.innerHTML = `<div class="error-msg">❌ ${e.message}</div>`;
      }
    }

    async function triggerSync() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('syncStatus');
      const btn = document.getElementById('syncBtn');
      const skipAI = document.getElementById('skipAISync').checked;

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '↻ Bezig…';
      statusEl.textContent = 'Workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const inputs = {};
        if (skipAI) inputs.skip_ai = true;

        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/fetch_sugarwod.yml/dispatches',
          {
            method: 'POST',
            headers: {
              Authorization: `token ${token}`,
              Accept: 'application/vnd.github+json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main', inputs }),
          }
        );

        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false;
          btn.textContent = '↻ Sync';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'fetch_sugarwod.yml', '↻ Sync');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '↻ Sync';
      }
    }

    async function triggerHealthRefresh() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('healthStatus');
      const btn = document.getElementById('healthBtn');
      const skipStrava = document.getElementById('skipStravaHealth').checked;
      const skipIntervals = document.getElementById('skipIntervalsHealth').checked;
      const skipWithings = document.getElementById('skipWithingsHealth').checked;

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '♥ Bezig…';
      statusEl.textContent = 'Health workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const inputs = {};
        if (skipStrava) inputs.skip_strava = true;
        if (skipIntervals) inputs.skip_intervals = true;
        if (skipWithings) inputs.skip_withings = true;

        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/fetch_health_data.yml/dispatches',
          {
            method: 'POST',
            headers: {
              Authorization: `token ${token}`,
              Accept: 'application/vnd.github+json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main', inputs }),
          }
        );

        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false;
          btn.textContent = '♥ Health';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'fetch_health_data.yml', '♥ Health');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '♥ Health';
      }
    }

    async function triggerRunningPlan() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('runningPlanStatus');
      const btn = document.getElementById('runningPlanBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '🏃 Bezig…';
      statusEl.textContent = 'Hardloopplan workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/generate_running_workout.yml/dispatches',
          {
            method: 'POST',
            headers: {
              Authorization: `token ${token}`,
              Accept: 'application/vnd.github+json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main', inputs: {} }),
          }
        );

        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false;
          btn.textContent = '🏃 Genereer';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'generate_running_workout.yml', '🏃 Genereer');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '🏃 Genereer';
      }
    }

    async function triggerSignup() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('signupStatus');
      const btn = document.getElementById('signupBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '⚡ Bezig…';
      statusEl.textContent = 'Inschrijf-workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/autosignup.yml/dispatches',
          {
            method: 'POST',
            headers: {
              Authorization: `token ${token}`,
              Accept: 'application/vnd.github+json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main' }),
          }
        );

        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false;
          btn.textContent = '⚡ Inschrijven';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(
          token, triggerTime, statusEl, btn,
          'autosignup.yml', '⚡ Inschrijven'
        );

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '⚡ Inschrijven';
      }
    }

    async function pollWorkflowRun(token, triggerTime, statusEl, btn, workflowFile = 'fetch_sugarwod.yml', btnLabel = '↻ Sync') {
      const headers = {
        Authorization: `token ${token}`,
        Accept: 'application/vnd.github+json',
      };
      const runsUrl = `https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/${workflowFile}/runs?event=workflow_dispatch&per_page=5`;
      const maxWaitMs = 10 * 60 * 1000; // 10 min timeout
      const pollInterval = 15000; // 15 sec
      const started = Date.now();

      // Wait a moment before first poll so GitHub registers the run
      await new Promise(r => setTimeout(r, 5000));

      while (Date.now() - started < maxWaitMs) {
        try {
          const r = await fetch(runsUrl, { headers });
          if (r.ok) {
            const data = await r.json();
            const run = (data.workflow_runs || []).find(
              wr => new Date(wr.created_at) >= triggerTime
            );
            if (run) {
              const elapsed = Math.round((Date.now() - started) / 1000);
              if (run.status === 'completed') {
                if (run.conclusion === 'success') {
                  statusEl.textContent = `✅ Klaar (${elapsed}s) — data opnieuw laden…`;
                  statusEl.style.color = '#4caf50';
                  btn.disabled = false;
                  btn.textContent = btnLabel;
                  await new Promise(r => setTimeout(r, 1500));
                  await loadData();
                  statusEl.textContent = `✅ Data bijgewerkt (${elapsed}s geleden)`;
                } else {
                  statusEl.textContent = `❌ Workflow mislukt: ${run.conclusion}`;
                  statusEl.style.color = 'var(--accent2)';
                  btn.disabled = false;
                  btn.textContent = btnLabel;
                }
                return;
              } else if (run.status === 'in_progress') {
                statusEl.textContent = `⚙️ Bezig… (${elapsed}s)`;
                statusEl.style.color = 'var(--muted)';
              } else {
                statusEl.textContent = `⏳ In wachtrij… (${elapsed}s)`;
                statusEl.style.color = 'var(--muted)';
              }
            }
          }
        } catch (_) { /* network blip, keep polling */ }

        await new Promise(r => setTimeout(r, pollInterval));
      }

      // Timeout
      statusEl.textContent = 'Timeout: workflow duurde te lang. Laad handmatig opnieuw.';
      statusEl.style.color = 'var(--accent2)';
      btn.disabled = false;
      btn.textContent = btnLabel;
    }

    function renderBenchmarks(benchmarks) {
      // Group by category
      const categories = {};
      for (const b of benchmarks) {
        const cat = b.category || 'Overig';
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(b);
      }
      const cats = Object.keys(categories).sort();
      const firstCat = cats[0];
      const tabsId = 'bm-tabs';
      const tableId = 'bm-table';

      let tabsHtml = cats.map(cat =>
        `<button class="benchmark-tab${cat === firstCat ? ' active' : ''}" onclick="switchBenchmarkTab('${escapeHtml(cat)}')">${escapeHtml(cat)}</button>`
      ).join('');

      // Encode all categories as JSON in a hidden script
      const encoded = JSON.stringify(categories);

      return `
        <div id="${tabsId}" class="benchmark-tabs">${tabsHtml}</div>
        <script id="bm-data" type="application/json">${encoded}<\/script>
        <div id="${tableId}">${buildBenchmarkTable(categories[firstCat])}</div>`;
    }

    function buildBenchmarkTable(rows) {
      const sorted = [...rows].sort((a, b) => (a.name || '').localeCompare(b.name || '', 'nl'));
      return `<table class="benchmark-table">
        <thead><tr>
          <th>Benchmark</th>
          <th>Resultaat</th>
          <th>Scaling</th>
          <th>Datum</th>
        </tr></thead>
        <tbody>${sorted.map(r => `<tr>
          <td class="bm-name">${escapeHtml(r.name)}</td>
          <td class="bm-result">${escapeHtml(r.result)}</td>
          <td class="bm-scaling">${escapeHtml(r.scaling)}</td>
          <td class="bm-date">${escapeHtml(r.date)}</td>
        </tr>`).join('')}</tbody>
      </table>`;
    }

    function switchBenchmarkTab(cat) {
      // Update active tab
      document.querySelectorAll('.benchmark-tab').forEach(btn => {
        btn.classList.toggle('active', btn.textContent === cat);
      });
      // Load data and re-render table
      const raw = document.getElementById('bm-data');
      if (!raw) return;
      const categories = JSON.parse(raw.textContent);
      const table = document.getElementById('bm-table');
      if (table && categories[cat]) {
        table.innerHTML = buildBenchmarkTable(categories[cat]);
      }
    }

    function formatPrDate(raw) {
      // Accepts YYYY-MM-DD, YYYYMMDD, or human-readable strings
      const clean = raw.replace(/\//g, '-').trim();
      const m = clean.match(/^(\d{4})-?(\d{2})-?(\d{2})/);
      if (m) {
        const d = new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00`);
        return `${d.getDate()} ${MONTH_NL[d.getMonth()]} ${d.getFullYear()}`;
      }
      return raw;
    }

    // ── Data bronnen inspector ────────────────────────────────────────────
    function renderDataSourcesBlock() {
      const rows = [];

      // helper: maak een tabel van een array van objecten
      function makeTable(records, cols) {
        if (!records || records.length === 0) return '<em class="ds-empty">geen data</em>';
        const header = cols.map(c => `<th>${c.label}</th>`).join('');
        const body = records.map(r => {
          const cells = cols.map(c => {
            const v = c.get ? c.get(r) : r[c.key];
            return `<td>${v == null ? '<span class="ds-null">—</span>' : v}</td>`;
          }).join('');
          return `<tr>${cells}</tr>`;
        }).join('');
        return `<table class="ds-table"><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
      }

      // ── Intervals.icu wellness (laatste 14 dagen) ──────────────────
      {
        const byDate = intervalsData?.wellness?.by_date || {};
        const dates = Object.keys(byDate).sort().slice(-14);
        const records = dates.map(d => ({ date: d, ...byDate[d] }));
        const cols = [
          { label: 'Datum',    get: r => r.date },
          { label: 'HRV ms',   key: 'hrv', get: r => r.hrv != null ? Math.round(r.hrv) : null },
          { label: 'RHR bpm',  key: 'resting_hr' },
          { label: 'Slaap u',  get: r => r.sleep_hrs != null ? r.sleep_hrs.toFixed(1) : null },
          { label: 'Slaapscore', key: 'sleep_score' },
          { label: 'SpO₂ %',    key: 'spo2' },
          { label: 'CTL',        get: r => r.ctl != null ? Math.round(r.ctl) : null },
          { label: 'ATL',        get: r => r.atl != null ? Math.round(r.atl) : null },
          { label: 'TSB',        get: r => r.tsb != null ? Math.round(r.tsb) : null },
          { label: 'Gewicht',    key: 'weight_kg' },
          { label: 'Stappen',    key: 'steps' },
          { label: 'VO2max',     key: 'vo2max' },
          { label: 'Spierpijn',  key: 'soreness' },
          { label: 'Vermoeid',   key: 'fatigue' },
          { label: 'Stress',     key: 'stress' },
          { label: 'Stemming',   key: 'mood' },
          { label: 'Motivatie',  key: 'motivation' },
        ];
        rows.push(`<div class="ds-section-title">Intervals.icu — Wellness (laatste 14 dagen)</div>${makeTable(records, cols)}`);
      }

      // ── Intervals.icu activiteiten (laatste 21 dagen) ──────────────
      {
        const byDate = intervalsData?.activities?.by_date || {};
        const allActs = Object.entries(byDate)
          .sort((a, b) => b[0].localeCompare(a[0]))
          .slice(0, 21)
          .flatMap(([date, acts]) => (acts || []).map(a => ({ date, ...a })));
        const cols = [
          { label: 'Datum',    key: 'date' },
          { label: 'Naam',     key: 'name' },
          { label: 'Type',     key: 'type' },
          { label: 'Duur min', key: 'duration_min' },
          { label: 'Afstand m', get: r => r.distance_m != null ? Math.round(r.distance_m) : null },
          { label: 'HR gem',   key: 'avg_hr' },
          { label: 'HR max',   key: 'max_hr' },
          { label: 'Watt gem', get: r => r.avg_watts != null ? Math.round(r.avg_watts) : null },
          { label: 'TL',       get: r => r.training_load != null ? Math.round(r.training_load) : null },
          { label: 'RPE',      key: 'rpe' },
          { label: 'kcal',     key: 'calories' },
        ];
        rows.push(`<div class="ds-section-title">Intervals.icu — Activiteiten</div>${makeTable(allActs, cols)}`);
      }

      // ── Withings metingen ──────────────────────────────────────────
      {
        const measurements = (withingsData?.measurements || []).slice(0, 10);
        const cols = [
          { label: 'Datum',        key: 'date' },
          { label: 'Gewicht kg',   key: 'weight_kg' },
          { label: 'Vet %',        key: 'fat_pct' },
          { label: 'Spier kg',     key: 'muscle_kg' },
          { label: 'Hydratatie kg', key: 'hydration_kg' },
          { label: 'Visceraal',    key: 'visceral_fat' },
          { label: 'Bot kg',       key: 'bone_kg' },
          { label: 'PWV m/s',      key: 'pwv_ms' },
          { label: 'Zenuw /100',   key: 'nerve_health' },
        ];
        rows.push(`<div class="ds-section-title">Withings — Metingen (laatste 10)</div>${makeTable(measurements, cols)}`);
      }

      // ── Strava activiteiten ────────────────────────────────────────
      {
        const byDate = stravaData?.activities_by_date || {};
        const allActs = Object.entries(byDate)
          .sort((a, b) => b[0].localeCompare(a[0]))
          .slice(0, 14)
          .flatMap(([date, acts]) => (acts || []).map(a => ({ date, ...a })));
        const cols = [
          { label: 'Datum',     key: 'date' },
          { label: 'Naam',      key: 'name' },
          { label: 'Type',      key: 'type' },
          { label: 'Duur min',  key: 'duration_min' },
          { label: 'HR gem',    get: r => r.avg_hr != null ? Math.round(r.avg_hr) : null },
          { label: 'HR max',    get: r => r.max_hr != null ? Math.round(r.max_hr) : null },
          { label: 'kcal',      get: r => r.calories != null ? Math.round(r.calories) : null },
          { label: 'Suffer',    key: 'suffer_score' },
          { label: 'RPE',       key: 'perceived_exertion' },
        ];
        rows.push(`<div class="ds-section-title">Strava — Activiteiten</div>${makeTable(allActs, cols)}`);
      }

      // ── Hardloopplan workouts ──────────────────────────────────────
      {
        const allSessions = (runningPlanData?.workouts || []).slice().sort((a, b) => b.date.localeCompare(a.date));
        if (allSessions.length > 0) {
          const cols = [
            { label: 'Datum',   key: 'date' },
            { label: 'Naam',    key: 'name' },
            { label: 'Type',    key: 'type' },
            { label: 'Min',     key: 'total_duration_min' },
          ];
          rows.push(`<div class="ds-section-title">Hardloopplan — Workouts</div>${makeTable(allSessions, cols)}`);
        }
      }

      return `<div class="section-title collapsible" onclick="toggleSection(this)">Data bronnen</div>
        <div class="collapsible-body">
          <div class="ds-block">${rows.join('')}</div>
        </div>`;
    }

    // ── Recovery today block ──────────────────────────────────────────────

    function renderRecoveryTodayBlock() {
      const today = new Date().toISOString().slice(0, 10);
      const yesterday = (() => { const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); })();

      // ── Intervals.icu wellness ──────────────────────────────────────
      const byDate = intervalsData?.wellness?.by_date || {};
      const wDate = byDate[today] ? today : (byDate[yesterday] ? yesterday : null);
      let w = wDate ? byDate[wDate] : null;

      // Historische reeks voor baselines: laatste 28 dagen VÓÓR de meetdatum (nooit de meting zelf meetellen)
      const histDates = Object.keys(byDate).filter(d => d < (wDate || today)).sort().slice(-28);
      const histHrv   = histDates.map(d => byDate[d].hrv).filter(v => v != null);
      const histSpo2  = histDates.slice(-7).map(d => byDate[d].spo2).filter(v => v != null);

      // HRV baseline (28-daags gemiddelde + standaarddeviatie) → Garmin-stijl status + kleuren
      const hrvBaseline = histHrv.length >= 5
        ? histHrv.reduce((a, b) => a + b, 0) / histHrv.length : null;
      const hrvBaselineStd = (hrvBaseline && histHrv.length >= 5)
        ? Math.sqrt(histHrv.reduce((s, v) => s + Math.pow(v - hrvBaseline, 2), 0) / histHrv.length)
        : null;
      const hrvBaselineLow  = (hrvBaseline && hrvBaselineStd != null) ? Math.round(hrvBaseline - hrvBaselineStd) : null;
      const hrvBaselineHigh = (hrvBaseline && hrvBaselineStd != null) ? Math.round(hrvBaseline + hrvBaselineStd) : null;

      // Garmin HRV status: Evenwichtig (●), Ongebalanceerd (■), Laag (▲)
      let hrvStatus = null, hrvColor = null, hrvIcon = null;
      if (hrvBaseline && w?.hrv != null) {
        const ratio = w.hrv / hrvBaseline;
        if (w.hrv >= (hrvBaselineLow ?? hrvBaseline * 0.90)) {
          hrvStatus = 'Evenwichtig'; hrvColor = '#57BB87'; hrvIcon = '●';
        } else if (ratio >= 0.75) {
          hrvStatus = 'Ongebalanceerd'; hrvColor = '#F5A623'; hrvIcon = '■';
        } else {
          hrvStatus = 'Laag'; hrvColor = '#E23B35'; hrvIcon = '▲';
        }
      }

      // SpO₂ 7-daags gemiddelde
      const spo2Avg = histSpo2.length >= 3
        ? Math.round(histSpo2.reduce((a, b) => a + b, 0) / histSpo2.length * 10) / 10 : null;

      // TSB badge
      const tsb = w?.tsb;
      const tsbColor = tsb == null ? '#888' : tsb > 5 ? '#2ecc71' : tsb < -10 ? '#e74c3c' : '#f39c12';
      const tsbLabel = tsb == null ? '' : tsb > 5 ? 'Fris' : tsb < -10 ? 'Vermoeid' : 'Neutraal';
      const tsbBadge = tsb != null
        ? `<span class="recovery-tsb-badge" style="background:${tsbColor}">${tsbLabel} ${tsb > 0 ? '+' : ''}${Math.round(tsb)}</span>`
        : '';

      // Rij 1: biometrics (Garmin/Intervals.icu)
      let metricsRow = '';
      if (w) {
        const p = [];
        if (w.hrv != null) {
          const baselineRange = (hrvBaselineLow != null && hrvBaselineHigh != null)
            ? `${hrvBaselineLow}–${hrvBaselineHigh}ms`
            : (hrvBaseline ? `${Math.round(hrvBaseline)}ms` : '');
          const baselineTitle = baselineRange ? ` (basislijn ${baselineRange})` : '';
          const col = hrvColor ? ` style="color:${hrvColor}"` : '';
          const statusBadge = (hrvIcon && hrvStatus)
            ? ` <span style="color:${hrvColor};font-size:0.85em">${hrvIcon} ${hrvStatus}</span>` : '';
          const trendData = intervalsData?.hrv_trend;
          const trendBadge = (() => {
            if (!trendData || Math.abs(trendData.delta_ms) < 0.5) return '';
            const up = trendData.delta_ms > 0;
            const col2 = up ? '#2ecc71' : '#f39c12';
            const arrow = up ? '↑' : '↓';
            return ` <span style="color:${col2};font-size:0.78em" title="HRV trend (${trendData.days_used} dagen): ${trendData.prev_avg}ms → ${trendData.recent_avg}ms">${arrow}${Math.abs(trendData.delta_ms)}ms</span>`;
          })();
          p.push(`HRV <strong${col} title="Vandaag${baselineTitle}">${Math.round(w.hrv)}ms</strong>${statusBadge}${trendBadge}`);
        }
        if (w.resting_hr != null)  p.push(`RHR <strong>${w.resting_hr}bpm</strong>`);
        if (w.sleep_hrs != null) {
          let s = `Slaap <strong>${w.sleep_hrs.toFixed(1)}u`;
          if (w.sleep_score != null) s += ` (${w.sleep_score})`;
          p.push(s + '</strong>');
        }
        if (w.spo2 != null) {
          let spo2Str = `SpO₂ <strong>${w.spo2}%`;
          if (spo2Avg != null && Math.abs(w.spo2 - spo2Avg) >= 0.5)
            spo2Str += ` <span class="rec-avg">gem ${spo2Avg}%</span>`;
          p.push(spo2Str + '</strong>');
        }
        if (w.ctl != null && w.atl != null)
          p.push(`Fitness <strong>${Math.round(w.ctl)}</strong> · Moe <strong>${Math.round(w.atl)}</strong>`);
        if (p.length) metricsRow = `<div class="recovery-data-row"><span class="rec-source">Garmin</span>${p.join(' · ')}</div>`;
      }

      // Rij 2: lichaamssamenstelling (Withings) + meetdatum
      let bodyRow = '';
      if (withingsData?.measurements?.length) {
        const latest = withingsData.measurements.find(m => m.weight_kg != null);
        if (latest) {
          const prev = withingsData.measurements.find(m => m.weight_kg != null && m !== latest);
          let wt = `<strong>${latest.weight_kg}kg</strong>`;
          if (prev) {
            const delta = Math.round((latest.weight_kg - prev.weight_kg) * 10) / 10;
            if (delta !== 0) {
              const col = delta > 0 ? '#e74c3c' : '#2ecc71';
              wt += `<span style="color:${col};margin-left:2px">${delta > 0 ? '↑' : '↓'}${Math.abs(delta)}</span>`;
            }
          }
          const d = new Date(latest.date + 'T00:00:00');
          const dateLabel = `${d.getDate()} ${MONTH_NL[d.getMonth()]}`;
          const p = [wt];
          if (latest.fat_pct != null)      p.push(`Vet <strong>${latest.fat_pct}%</strong>`);
          if (latest.muscle_kg != null)    p.push(`Spier <strong>${latest.muscle_kg}kg</strong>`);
          if (latest.visceral_fat != null) p.push(`Visceraal <strong>${latest.visceral_fat}</strong>`);
          if (latest.pwv_ms != null)       p.push(`PWV <strong>${latest.pwv_ms}m/s</strong>`);
          if (latest.nerve_health != null) p.push(`Zenuw <strong>${latest.nerve_health}/100</strong>`);
          bodyRow = `<div class="recovery-data-row"><span class="rec-source">Withings ${dateLabel}</span>${p.join(' · ')}</div>`;
        }
      }

      if (!metricsRow && !bodyRow) return '';

      return `<div class="recovery-today-block">
        <div class="recovery-today-header">
          <span class="recovery-today-label">Herstel vandaag</span>
          ${tsbBadge}
        </div>
        ${metricsRow}${bodyRow}
      </div>`;
    }

    // ── end health helpers ────────────────────────────────────────────────

    // ── Environmental widget (gebruikt in renderCard via renderEnvBadge) ─
    function renderEnvBadge(dateStr) {
      if (!environmentalData) return '';
      const cond = (environmentalData.training_conditions || {})[dateStr];
      const aqi  = environmentalData.aqi;
      if (!cond && !aqi) return '';

      const parts = [];
      if (cond) {
        parts.push(`${Math.round(cond.temp_c)}°C`);
        if (cond.feels_like_c != null && Math.abs(cond.feels_like_c - cond.temp_c) >= 2) {
          parts.push(`(voelt ${Math.round(cond.feels_like_c)}°C)`);
        }
        parts.push(cond.weather_desc);
        if (cond.humidity_pct != null) parts.push(`${cond.humidity_pct}% vochtig`);
      }
      if (aqi) {
        const aqiColor = aqi.value <= 50 ? '#2ecc71' : aqi.value <= 100 ? '#f39c12' : '#e74c3c';
        parts.push(`<span class="aqi-badge" style="background:${aqiColor}">AQI ${aqi.value}</span>`);
      }
      return parts.length ? `<div class="env-badge">${parts.join(' · ')}</div>` : '';
    }

    // ── end Oura/Withings/Environmental helpers ──────────────────────────

    // ── Keukenbaas meals ─────────────────────────────────────────────────

    function renderMealsBlock() {
      if (!keukenbaasData || !keukenbaasData.meals || keukenbaasData.meals.length === 0) return '';
      const today = new Date().toISOString().slice(0, 10);
      // Show meals for the next 7 days starting today
      const meals = keukenbaasData.meals
        .filter(m => m.date >= today)
        .slice(0, 7);
      if (meals.length === 0) return '';

      const rows = meals.map(m => {
        const d = new Date(m.date + 'T00:00:00');
        const label = `${DAY_NL[d.getDay()]} ${d.getDate()}`;
        const kcal = m.energy_kcal ? `${Math.round(m.energy_kcal)} kcal` : '';
        return `<div class="meal-row">
          <div class="meal-date">${label}</div>
          <div class="meal-name">${escapeHtml(m.meal_name)}</div>
          ${kcal ? `<div class="meal-kcal">${kcal}</div>` : ''}
        </div>`;
      }).join('');

      return `<div class="meals-block">
        <div class="meals-block-label">Maaltijden komende week</div>
        ${rows}
      </div>`;
    }

    function renderMfpBlock() {
      const byDate = mfpData?.diary?.by_date;
      if (!byDate) return '';
      const entries = Object.entries(byDate)
        .filter(([, d]) => d.calories > 0)
        .sort(([a], [b]) => b.localeCompare(a))
        .slice(0, 7);
      if (entries.length === 0) return '';

      const pct = (val, goal) => goal ? Math.round(val / goal * 100) : null;
      const pctSpan = (p) => {
        if (p == null) return '';
        // Spieropbouw: meer eten is positief — rood alleen bij te weinig
        const c = p >= 90 ? '#2ecc71' : p >= 70 ? '#f39c12' : '#e74c3c';
        return ` <span style="color:${c};font-size:0.8em">${p}%</span>`;
      };
      const statStr = (label, val, goalVal, unit) => {
        const p = pct(val, goalVal);
        const goalPart = goalVal ? `<span style="color:#999">/${Math.round(goalVal)}</span>` : '';
        return `<span class="mfp-stat"><span style="color:#aaa;font-size:0.8em">${label}</span> <strong>${Math.round(val)}</strong>${goalPart}${unit}${pctSpan(p)}</span>`;
      };

      const rows = entries.map(([dateStr, d]) => {
        const dt = new Date(dateStr + 'T00:00:00');
        const label = `${DAY_NL[dt.getDay()]} ${dt.getDate()}`;
        const g = d.goal;
        return `<div class="mfp-day-row">
          <div class="meal-date">${label}</div>
          <div class="mfp-stats">
            ${statStr('kcal', d.calories, g?.calories, '')}
            ${statStr('E', d.protein_g, g?.protein_g, 'g')}
            ${statStr('KH', d.carbs_g, g?.carbs_g, 'g')}
            ${statStr('V', d.fat_g, g?.fat_g, 'g')}
            ${d.fiber_g > 0 ? statStr('vezel', d.fiber_g, g?.fiber_g, 'g') : ''}
            ${d.sugar_g > 0 ? statStr('suiker', d.sugar_g, g?.sugar_g, 'g') : ''}
            ${d.water_cups != null ? `<span class="mfp-stat">💧 <strong>${d.water_cups}</strong> cups</span>` : ''}
          </div>
        </div>`;
      }).join('');

      // Gemiddelde over beschikbare dagen
      const n = entries.length;
      const avg = (key) => entries.reduce((s, [, d]) => s + (d[key] || 0), 0) / n;
      const g0 = entries[0][1].goal || {};
      const avgRow = `<div class="mfp-day-row" style="border-top:1px solid #2a5020;margin-top:0.3rem;padding-top:0.6rem">
        <div class="meal-date" style="color:#aaa">∅ ${n}d</div>
        <div class="mfp-stats">
          ${statStr('kcal', avg('calories'), g0.calories, '')}
          ${statStr('E', avg('protein_g'), g0.protein_g, 'g')}
          ${statStr('KH', avg('carbs_g'), g0.carbs_g, 'g')}
          ${statStr('V', avg('fat_g'), g0.fat_g, 'g')}
          ${entries.some(([,d]) => d.fiber_g > 0) ? statStr('vezel', avg('fiber_g'), g0.fiber_g, 'g') : ''}
          ${entries.some(([,d]) => d.sugar_g > 0) ? statStr('suiker', avg('sugar_g'), g0.sugar_g, 'g') : ''}
        </div>
      </div>`;

      const fetchedAt = mfpData?.fetched_at
        ? (() => {
            const d = new Date(mfpData.fetched_at);
            const now = new Date();
            const diffMin = Math.round((now - d) / 60000);
            const timeStr = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
            const age = diffMin < 60
              ? `${diffMin}m geleden`
              : diffMin < 1440
                ? `${Math.round(diffMin / 60)}u geleden`
                : `${Math.round(diffMin / 1440)}d geleden`;
            return `<span style="color:#666;font-size:0.75em;float:right">${timeStr} (${age})</span>`;
          })()
        : '';

      return `<div class="meals-block">
        <div class="meals-block-label">MyFitnessPal — gegeten (laatste dagen)${fetchedAt}</div>
        ${rows}
        ${avgRow}
      </div>`;
    }

    // ── Barbell progressie (chart + table) ────────────────────────────────

    // Top lifts to show buttons for (most common CrossFit barbell movements)
    const TOP_LIFTS = [
      'Back Squat', 'Deadlift', 'Clean & Jerk', 'Snatch', 'Front Squat',
      'Bench Press', 'Shoulder Press', 'Clean', 'Push Jerk',
    ];

    function renderBarbellSection() {
      // Build buttons only for lifts we have history OR current data for
      const availableLifts = TOP_LIFTS.filter(l => barbellLifts[l] || barbellLiftsHistory.some(h => h.lifts && h.lifts[l]));
      if (availableLifts.length === 0) {
        // Fallback: just show table
        return `<div class="section-title">Kracht Maxima</div>` + renderBarbellTable();
      }

      activeChartLift = activeChartLift && availableLifts.includes(activeChartLift)
        ? activeChartLift
        : availableLifts[0];

      const buttons = availableLifts.map(l =>
        `<button class="chart-lift-btn${l === activeChartLift ? ' active' : ''}" onclick="selectLift('${escapeHtml(l)}')">${escapeHtml(l)}</button>`
      ).join('');

      const historyCount = barbellLiftsHistory.length;
      const historyNote = historyCount > 1
        ? `<span style="font-size:0.68rem;color:var(--muted);margin-left:auto">${historyCount} meetpunten</span>`
        : `<span style="font-size:0.68rem;color:var(--muted);margin-left:auto">Nog geen history — groeit elke dag</span>`;

      return `<div class="section-title">Kracht Progressie</div>
        <div class="chart-section">
          <div class="chart-controls">
            ${buttons}
            ${historyNote}
          </div>
          <div class="chart-container">
            <canvas id="liftChartCanvas"></canvas>
          </div>
        </div>
        <div class="section-title">Barbell Maxima</div>
        ${renderBarbellTable()}`;
    }

    function renderBarbellTable() {
      const lifts = Object.entries(barbellLifts).sort((a, b) => a[0].localeCompare(b[0], 'nl'));
      if (lifts.length === 0) return '<div class="empty" style="padding:1rem">Geen barbell data</div>';
      const rows = lifts.map(([name, rms]) => {
        const rmRows = Object.entries(rms).sort((a, b) => {
          const n = s => parseInt(s.replace('RM',''));
          return n(a[0]) - n(b[0]);
        }).map(([rm, val]) =>
          `<div class="barbell-rm-row">
            <span class="barbell-rm-label">${rm}</span>
            <span class="barbell-rm-val">${val} kg</span>
          </div>`
        ).join('');
        return `<div class="barbell-lift-item">
          <div class="barbell-lift-name">${escapeHtml(name)}</div>
          <div class="barbell-rm-list">${rmRows}</div>
        </div>`;
      }).join('');
      return `<div class="barbell-lift-list">${rows}</div>`;
    }

    function initBarbellChart() {
      if (typeof Chart === 'undefined') return;
      const canvas = document.getElementById('liftChartCanvas');
      if (!canvas) return;
      if (liftChart) { liftChart.destroy(); liftChart = null; }
      renderLiftChart(activeChartLift || TOP_LIFTS[0]);
    }

    function renderLiftChart(liftName) {
      const canvas = document.getElementById('liftChartCanvas');
      if (!canvas) return;
      if (liftChart) { liftChart.destroy(); liftChart = null; }

      // Build data points from history + current value
      const points = [];
      for (const snapshot of barbellLiftsHistory) {
        const liftData = snapshot.lifts && snapshot.lifts[liftName];
        if (!liftData) continue;
        const rm1 = liftData['1RM'];
        if (rm1 != null) points.push({ x: snapshot.date, y: rm1 });
      }
      // Add current value if not already in history for today
      const today = new Date().toISOString().slice(0, 10);
      const currentLift = barbellLifts[liftName];
      if (currentLift && currentLift['1RM'] != null && !points.find(p => p.x === today)) {
        points.push({ x: today, y: currentLift['1RM'] });
      }
      points.sort((a, b) => a.x.localeCompare(b.x));

      if (points.length === 0) {
        // No chart data — show current RM values as text
        canvas.style.display = 'none';
        const container = canvas.parentElement;
        const existing = container.querySelector('.chart-empty');
        if (!existing) {
          const div = document.createElement('div');
          div.className = 'chart-empty';
          const vals = currentLift ? Object.entries(currentLift).map(([k,v]) => `${k}: ${v}kg`).join(' · ') : 'Geen data';
          div.textContent = `${liftName}: ${vals}`;
          container.appendChild(div);
        }
        return;
      }
      canvas.style.display = '';
      const container = canvas.parentElement;
      const empty = container.querySelector('.chart-empty');
      if (empty) empty.remove();

      liftChart = new Chart(canvas, {
        type: 'line',
        data: {
          labels: points.map(p => {
            const d = new Date(p.x + 'T00:00:00');
            return `${d.getDate()} ${MONTH_NL[d.getMonth()]}`;
          }),
          datasets: [{
            label: `${liftName} 1RM (kg)`,
            data: points.map(p => p.y),
            borderColor: '#e8ff3c',
            backgroundColor: 'rgba(232,255,60,0.08)',
            pointBackgroundColor: '#e8ff3c',
            pointRadius: points.length < 10 ? 5 : 3,
            fill: true,
            tension: 0.3,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#1e1e1e',
              titleColor: '#e8ff3c',
              bodyColor: '#f0f0f0',
              borderColor: '#2a2a2a',
              borderWidth: 1,
            },
          },
          scales: {
            x: {
              ticks: { color: '#666', font: { size: 10 } },
              grid: { color: '#1e1e1e' },
            },
            y: {
              ticks: { color: '#666', font: { size: 10 }, callback: v => `${v}kg` },
              grid: { color: '#1e1e1e' },
            },
          },
        },
      });
    }

    function selectLift(name) {
      activeChartLift = name;
      document.querySelectorAll('.chart-lift-btn').forEach(btn => {
        btn.classList.toggle('active', btn.textContent === name);
      });
      renderLiftChart(name);
    }

    // ── end barbell chart ─────────────────────────────────────────────────

    // ── Personal events ───────────────────────────────────────────────────

    function renderPersonalEventCard(event, delay) {
      const timeHtml = event.time ? `<span class="card-time" style="color:#4db8ff">${event.time}</span>` : '';
      const locHtml  = event.location ? `<span>${escapeHtml(event.location)}</span>` : '';
      const metaHtml = (timeHtml || locHtml) ? `<div class="card-meta">${timeHtml}${locHtml}</div>` : '';
      const deleteBtn = `<button class="personal-delete-btn" title="Verwijderen"
        onclick="event.stopPropagation();deletePersonalEvent('${escapeHtml(event.id)}',this)">✕</button>`;

      if (event.notes) {
        return `
          <div class="card has-wod" style="animation-delay:${delay}s" onclick="toggleWod(this)">
            <div class="card-dot dot-personal"></div>
            <div class="card-info">
              <div class="card-header">
                <div class="card-header-left">
                  <div class="card-title">${escapeHtml(event.title)}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  <div class="card-date" style="color:#4db8ff">${formatDate(event.date)}</div>
                  <div class="card-relative-day">${relativeDay(event.date)}</div>
                  <div style="display:flex;gap:0.3rem;align-items:center">${deleteBtn}<div class="wod-chevron" style="color:#4db8ff">▾</div></div>
                </div>
              </div>
              <div class="card-wod">
                <div style="font-size:0.82rem;color:#b0ccf0;white-space:pre-wrap;line-height:1.6">${escapeHtml(event.notes)}</div>
              </div>
            </div>
          </div>`;
      }

      return `
        <div class="card" style="animation-delay:${delay}s">
          <div class="card-dot dot-personal"></div>
          <div class="card-info">
            <div class="card-title">${escapeHtml(event.title)}</div>
            ${metaHtml}
          </div>
          <div class="card-right">
            <div class="card-date" style="color:#4db8ff">${formatDate(event.date)}</div>
            <div class="card-relative-day">${relativeDay(event.date)}</div>
            ${deleteBtn}
          </div>
        </div>`;
    }

    // ── Hardlooplan event cards ────────────────────────────────────────────────

    function _findActualRun(date) {
      const runTypes = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
      const acts = ((intervalsData?.activities || {}).by_date || {})[date] || [];
      return acts.find(a => runTypes.some(rt => (a.type || '').toLowerCase().includes(rt))) || null;
    }

    function _renderActualRunStats(act) {
      const parts = [];
      if (act.distance_m) parts.push(`<strong>${(act.distance_m / 1000).toFixed(1)} km</strong>`);
      if (act.duration_min) parts.push(`<strong>${act.duration_min} min</strong>`);
      if (act.avg_speed_ms > 0) {
        const spm = 1000 / act.avg_speed_ms / 60;
        parts.push(`pace <strong>${Math.floor(spm)}:${String(Math.round((spm % 1) * 60)).padStart(2,'0')}/km</strong>`);
      }
      if (act.avg_hr) parts.push(`gem.HR <strong>${act.avg_hr} bpm</strong>`);
      if (act.rpe) parts.push(`RPE <strong>${act.rpe}</strong>`);

      let lapsHtml = '';
      if (act.laps && act.laps.length > 1) {
        const lapRows = act.laps.map((lap, i) => {
          const d = lap.distance_m ? `${lap.distance_m}m` : '';
          const p = lap.pace_per_km ? `${lap.pace_per_km}/km` : '';
          const h = lap.avg_hr ? `${lap.avg_hr}bpm` : '';
          return `<div style="display:flex;gap:0.6rem;font-size:0.75rem;color:#c0e8d0;padding:0.1rem 0">
            <span style="color:#6a9a7a;min-width:1.2rem">${i+1}</span>
            <span>${[d,p,h].filter(Boolean).join(' · ')}</span></div>`;
        }).join('');
        lapsHtml = `<div style="margin-top:0.4rem;border-top:1px solid rgba(0,200,83,0.15);padding-top:0.4rem">${lapRows}</div>`;
      }

      return `<div style="margin-top:0.6rem;padding:0.5rem 0.7rem;background:rgba(0,200,83,0.08);border-radius:6px;font-size:0.8rem;color:#a0e8b0">
        ✅ Uitgevoerd: ${parts.join(' · ')}${lapsHtml}</div>`;
    }

    function renderRunEventCard(session, delay) {
      const today = new Date().toISOString().slice(0, 10);
      const isUpcoming = session.date >= today;
      const sessionKey = session.session === 'speed' ? 'run_1' : 'run_2';
      const sessionTime = session.time || (session.session === 'speed' ? '20:00' : '09:00');
      const cardId = 'run' + session.date.replace(/-/g, '');

      const distStr = session.total_distance_km ? `${session.total_distance_km} km` : '';
      const distHtml = distStr ? `<div class="card-meta" style="text-align:right">${distStr}</div>` : '';
      const metaHtml = `<div class="card-meta"><span class="card-time">${sessionTime}</span></div>`;

      const actualRun = !isUpcoming ? _findActualRun(session.date) : null;
      const actualHtml = actualRun ? _renderActualRunStats(actualRun) : '';

      const descText = session.full_description || session.description || '';
      const wodContent = (descText ? `<div style="font-size:0.82rem;color:#a0e8b0;white-space:pre-wrap;line-height:1.6">${escapeHtml(descText)}</div>` : '')
                       + actualHtml;
      const descHtml = wodContent
        ? `<div class="card-wod">${wodContent}</div>`
        : '';
      const hasWod = wodContent ? ' has-wod' : '';
      const chevron = wodContent ? `<div class="wod-chevron" style="color:#00c853">▾</div>` : '';

      const rescheduleBtn = isUpcoming
        ? `<button class="run-reschedule-btn" onclick="event.stopPropagation(); toggleReschedule('${cardId}')">📅 Datum/tijd</button>`
        : '';

      const scheduledOverride = (healthInput || {})[sessionKey];
      const overrideNote = scheduledOverride
        ? `<div style="font-size:0.7rem;color:#ffb300;margin-bottom:0.4rem">⚠ Verplaatst naar: ${scheduledOverride.replace('T', ' ')}</div>`
        : '';
      const clearBtn = scheduledOverride
        ? `<button class="run-reschedule-btn" style="color:#ff6b6b;border-color:rgba(255,107,107,0.3)" onclick="clearRunReschedule('${sessionKey}', '${cardId}')">✕ Herstel standaard</button>`
        : '';

      const rescheduleForm = isUpcoming ? `
        <div id="${cardId}" class="run-reschedule-form">
          ${overrideNote}
          <div style="font-size:0.75rem;color:#a0a0a0;margin-bottom:0.5rem">Nieuwe datum en tijd:</div>
          <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
            <input type="datetime-local" id="rsinput-${cardId}"
                   value="${session.date}T${sessionTime}"
                   class="add-event-input" style="flex:1;min-width:180px">
            <button class="run-reschedule-btn" id="rssave-${cardId}"
                    onclick="saveAndSyncReschedule('${sessionKey}', '${cardId}')">Opslaan & Sync Garmin</button>
            ${clearBtn}
          </div>
          <div id="rsstatus-${cardId}" style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem"></div>
        </div>` : '';

      const cardStyle = isUpcoming && session.description
        ? 'border-radius:8px 8px 0 0;border-bottom-color:transparent;'
        : '';

      return `
        <div>
          <div class="card${hasWod}" style="animation-delay:${delay}s;${cardStyle}"${session.description ? ' onclick="toggleWod(this)"' : ''}>
            <div class="card-dot" style="background:#00c853"></div>
            <div class="card-info">
              <div class="card-header">
                <div class="card-header-left">
                  <div class="card-title">🏃 ${escapeHtml(session.name || session.type || 'Run')}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  ${rescheduleBtn}
                  <div class="card-date" style="color:#00c853">${formatDate(session.date)}</div>
                  ${distHtml}
                  <div class="card-relative-day">${relativeDay(session.date)}</div>
                  ${chevron}
                </div>
              </div>
              ${descHtml}
            </div>
          </div>
          ${rescheduleForm}
        </div>`;
    }

    function toggleReschedule(cardId) {
      const el = document.getElementById(cardId);
      if (!el) return;
      el.style.display = el.style.display === 'block' ? 'none' : 'block';
    }

    async function _patchRescheduleToGist(token, sessionKey, newDatetime) {
      const newDate = newDatetime.slice(0, 10);
      const newTime = newDatetime.slice(11, 16);
      const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        headers: { Authorization: `token ${token}` }
      });
      const gist = await resp.json();
      let h = {};
      try { h = JSON.parse(gist.files['health_input.json']?.content || '{}'); } catch(e) {}
      h[sessionKey] = newDatetime;
      healthInput = h;
      let plan = {};
      try { plan = JSON.parse(gist.files['running_plan.json']?.content || '{}'); } catch(e) {}
      const sessionRole = sessionKey === 'run_1' ? 'speed' : 'long_run';
      if (plan.workouts) {
        const w = plan.workouts.find(w => w.session === sessionRole);
        if (w) { w.date = newDate; w.time = newTime; }
      }
      await fetch(`https://api.github.com/gists/${currentGistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: {
          'health_input.json': { content: JSON.stringify(h, null, 2) },
          'running_plan.json': { content: JSON.stringify(plan, null, 2) },
        }})
      });
    }

    async function saveAndSyncReschedule(sessionKey, cardId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
      const input = document.getElementById('rsinput-' + cardId);
      if (!input || !input.value) return;
      const newDatetime = input.value;
      const btn = document.getElementById('rssave-' + cardId);
      const statusEl = document.getElementById('rsstatus-' + cardId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };

      if (btn) { btn.disabled = true; btn.textContent = 'Opslaan…'; }
      try {
        await _patchRescheduleToGist(token, sessionKey, newDatetime);
        setStatus('✓ Opgeslagen in Gist — Garmin sync starten…');

        // Trigger reschedule workflow
        const triggerTime = new Date();
        const triggerResp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/reschedule_running_workout.yml/dispatches',
          {
            method: 'POST',
            headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref: 'main', inputs: {} }),
          }
        );
        if (triggerResp.status !== 204) {
          const body = await triggerResp.json().catch(() => ({}));
          setStatus(`Workflow fout ${triggerResp.status}: ${body.message || 'onbekend'}`, 'var(--accent2)');
          if (btn) { btn.disabled = false; btn.textContent = 'Opslaan & Sync Garmin'; }
          return;
        }
        if (btn) { btn.textContent = '⏳ Sync…'; }
        setStatus('⏳ Garmin sync bezig…');
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'reschedule_running_workout.yml', 'Opslaan & Sync Garmin');
      } catch(e) {
        setStatus(`Fout: ${e.message}`, 'var(--accent2)');
        if (btn) { btn.disabled = false; btn.textContent = 'Opslaan & Sync Garmin'; }
        console.error(e);
      }
    }

    async function clearRunReschedule(sessionKey, cardId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` }
        });
        const gist = await resp.json();

        let h = {};
        try { h = JSON.parse(gist.files['health_input.json']?.content || '{}'); } catch(e) {}
        delete h[sessionKey];
        healthInput = h;

        let plan = {};
        try { plan = JSON.parse(gist.files['running_plan.json']?.content || '{}'); } catch(e) {}
        const sessionRole = sessionKey === 'run_1' ? 'speed' : 'long_run';
        if (plan.workouts) {
          const w = plan.workouts.find(w => w.session === sessionRole);
          if (w) {
            const targetDay = sessionKey === 'run_1' ? 2 : 6; // 2=di, 6=za
            const today = new Date();
            const daysAhead = (targetDay - today.getDay() + 7) % 7 || 7;
            const def = new Date(today);
            def.setDate(today.getDate() + daysAhead);
            w.date = def.toISOString().slice(0, 10);
            w.time = sessionKey === 'run_1' ? '20:00' : '09:00';
          }
        }

        await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: {
            'health_input.json': { content: JSON.stringify(h, null, 2) },
            'running_plan.json': { content: JSON.stringify(plan, null, 2) },
          }})
        });
        setTimeout(() => location.reload(), 300);
      } catch(e) { console.error(e); }
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
                <option value="Yoga">Yoga</option>
                <option value="Gym">Gym</option>
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

      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.className = 'add-event-status'; }
      if (saveBtn)  saveBtn.disabled = true;

      const newEvent = { id: `personal_${Date.now()}`, title, date };
      if (time)     newEvent.time     = time;
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
        if (statusEl) { statusEl.textContent = '✓ Toegevoegd'; statusEl.className = 'add-event-status ok'; }

        setTimeout(() => {
          hideAddEventForm();
          rerenderUpcomingCards();
        }, 500);

      } catch(e) {
        if (statusEl) { statusEl.textContent = `❌ ${e.message}`; statusEl.className = 'add-event-status err'; }
        if (saveBtn)  saveBtn.disabled = false;
      }
    }

    async function deletePersonalEvent(id, btn) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) { btn.textContent = '⚠'; return; }

      btn.disabled = true;
      btn.textContent = '…';

      try {
        personalEvents = personalEvents.filter(e => e.id !== id);

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'personal_events.json': { content: JSON.stringify({ events: personalEvents }, null, 2) } } }),
        });
        if (!patch.ok) throw new Error(`${patch.status}`);

        btn.closest('.card').remove();
      } catch(e) {
        personalEvents.push({ id }); // restore so next delete attempt still works
        btn.disabled = false;
        btn.textContent = '✕';
      }
    }

    // Re-renders only the upcoming cards list (used after add/delete without full reload)
    let _upcomingCrossfit = [];
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

    function escapeHtml(str) {
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }
