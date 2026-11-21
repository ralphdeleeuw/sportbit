    // insights.js — Afgeleide inzichten uit de data: dagadvies, trainingsbelasting
    // (acuut:chronisch), prestatievoorspeller, versheid per databron, weekreview,
    // vakantiemodus en token-uitleg.

    // Een inzicht-blok mag nooit de hele tab breken: bij een fout leeg teruggeven.
    function _safeHtml(name, fn) {
      try { return fn() || ''; }
      catch (e) { console.error(`${name} mislukt:`, e); return ''; }
    }

    function _isoDay(offset = 0) {
      const d = new Date(); d.setDate(d.getDate() + offset);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }

    // ── Activiteiten per dag (zonder dubbeltelling) ───────────────────────
    // Intervals.icu en Strava bevatten grotendeels dezelfde activiteiten (beide
    // gevoed door Garmin). Per dag: intervals.icu als die er is, anders Strava.
    function activitiesForDay(d) {
      const i = ((intervalsData?.activities || {}).by_date || {})[d] || [];
      if (i.length) return i;
      return (stravaData?.activities_by_date || {})[d] || [];
    }

    function sportCategory(type) {
      const t = (type || '').toLowerCase();
      if (/run|jog|treadmill/.test(t)) return 'Hardlopen';
      if (/crossfit|weight|strength|workout|hiit|functional/.test(t)) return 'CrossFit/kracht';
      if (/paddl|standup|sup|kayak|row/.test(t)) return 'SUP/water';
      if (/mountain|mtb|ride|bike|cycl|gravel/.test(t)) return 'Fietsen/MTB';
      if (/walk|hike/.test(t)) return 'Wandelen';
      return 'Overig';
    }

    function _activityLoad(a) {
      if (a.training_load) return Number(a.training_load);
      return Number(a.duration_min || 0) * 1.2; // proxy: ~1,2 load per minuut matig
    }

    // ── Trainingsbelasting: acuut (7d) : chronisch (28d) ──────────────────
    // Een gevolgde CrossFit-les zonder geregistreerde activiteit telt als 60 min.
    function computeTrainingLoad() {
      const classDays = new Set((_pastCrossfit || []).map(e => e.date));
      const days = [];
      for (let i = 0; i < 28; i++) {
        const d = _isoDay(-i);
        const acts = activitiesForDay(d);
        let load = acts.reduce((s, a) => s + _activityLoad(a), 0);
        const bySport = {};
        acts.forEach(a => {
          const c = sportCategory(a.type);
          bySport[c] = (bySport[c] || 0) + Number(a.duration_min || 0);
        });
        if (classDays.has(d) && !acts.some(a => sportCategory(a.type) === 'CrossFit/kracht')) {
          load += 72;
          bySport['CrossFit/kracht'] = (bySport['CrossFit/kracht'] || 0) + 60;
        }
        days.push({ date: d, load, bySport });
      }
      const acute = days.slice(0, 7).reduce((s, d) => s + d.load, 0) / 7;
      const chronic = days.reduce((s, d) => s + d.load, 0) / 28;
      const hasData = days.some(d => d.load > 0);
      const acwr = hasData && chronic > 0 ? acute / chronic : null;
      const sport7 = {};
      days.slice(0, 7).forEach(d => Object.entries(d.bySport).forEach(([k, v]) => { sport7[k] = (sport7[k] || 0) + v; }));
      let zone = null;
      if (acwr != null) {
        zone = acwr > 1.5 ? { key: 'high', label: 'Hoog risico', color: '#ff4c2b' }
          : acwr > 1.3 ? { key: 'raised', label: 'Verhoogd', color: '#f5a623' }
          : acwr >= 0.8 ? { key: 'ok', label: 'Goed (sweet spot)', color: '#00c853' }
          : { key: 'low', label: 'Onderbelast', color: '#4db8ff' };
      }
      return { acute, chronic, acwr, zone, sport7, days };
    }

    function renderLoadCard(opts) { return _safeHtml('renderLoadCard', () => _renderLoadCard(opts)); }
    function _renderLoadCard({ compact = false } = {}) {
      const L = computeTrainingLoad();
      if (L.acwr == null) return '';
      const pct = Math.min(100, Math.max(0, (L.acwr / 2) * 100));
      const injuryActive = getInjuries().some(i => i.status !== 'hersteld');
      let warn = '';
      if (L.zone.key === 'high') warn = 'Belasting stijgt veel sneller dan je gewend bent — grootste blessurerisico. Schaal deze week terug.';
      else if (L.zone.key === 'raised') warn = 'Belasting loopt op. Bouw niet verder op en plan een rustdag.';
      if (injuryActive && L.acwr > 1.2) warn = `${warn} Je hebt een actieve blessure: extra voorzichtig.`.trim();
      const sports = Object.entries(L.sport7).filter(([, m]) => m > 0).sort((a, b) => b[1] - a[1])
        .map(([k, m]) => `<span class="load-chip">${escapeHtml(k)} ${Math.round(m)}′</span>`).join('');
      if (compact) {
        return `<div class="load-compact" onclick="switchTab('acties')">
          <span>Belasting 7:28</span>
          <strong style="color:${L.zone.color}">${L.acwr.toFixed(2)} · ${L.zone.label}</strong>
        </div>${warn ? `<div class="load-warn">⚠️ ${escapeHtml(warn)}</div>` : ''}`;
      }
      return `<div class="workflow-card load-card" id="loadCard">
        <div class="workflow-title">📊 Trainingsbelasting</div>
        <div class="workflow-desc">Verhouding belasting afgelopen 7 dagen t.o.v. 28 dagen (CrossFit, hardlopen, MTB, SUP samen).</div>
        <div class="load-value" style="color:${L.zone.color}">${L.acwr.toFixed(2)} <span>${L.zone.label}</span></div>
        <div class="load-bar"><div class="load-bar-zones"></div><div class="load-bar-mark" style="left:${pct}%"></div></div>
        <div class="load-bar-legend">${[[0,'0'],[40,'0,8'],[65,'1,3'],[75,'1,5'],[100,'2']].map(([x, t]) => `<span style="left:${x}%">${t}</span>`).join('')}</div>
        ${warn ? `<div class="load-warn">⚠️ ${escapeHtml(warn)}</div>` : ''}
        ${sports ? `<div class="load-sports">${sports}</div>` : ''}
      </div>`;
    }

    // ── Dagadvies: één kaart bovenaan Vandaag ─────────────────────────────
    function computeDayAdvice() {
      const byDate = intervalsData?.wellness?.by_date || {};
      const today = _isoDay(0), yesterday = _isoDay(-1);
      const wDate = byDate[today] ? today : (byDate[yesterday] ? yesterday : null);
      const w = wDate ? byDate[wDate] : null;
      const reasons = [];
      let score = 0;
      const flag = (pts, txt) => { score += pts; reasons.push({ pts, txt }); };

      if (w) {
        const hist = Object.keys(byDate).filter(d => d < wDate).sort().slice(-28);
        const hrvs = hist.map(d => byDate[d].hrv).filter(v => v != null);
        if (w.hrv != null && hrvs.length >= 5) {
          const avg = hrvs.reduce((a, b) => a + b, 0) / hrvs.length;
          const sd = Math.sqrt(hrvs.reduce((s, v) => s + (v - avg) ** 2, 0) / hrvs.length);
          if (w.hrv < avg * 0.75) flag(2, `HRV ${Math.round(w.hrv)} ms — ver onder je gemiddelde (${Math.round(avg)})`);
          else if (w.hrv < avg - sd) flag(1, `HRV ${Math.round(w.hrv)} ms — onder je normale bandbreedte`);
          else reasons.push({ pts: 0, txt: `HRV ${Math.round(w.hrv)} ms — normaal` });
        }
        const rhrs = hist.slice(-14).map(d => byDate[d].resting_hr).filter(v => v != null);
        if (w.resting_hr != null && rhrs.length >= 5) {
          const avg = rhrs.reduce((a, b) => a + b, 0) / rhrs.length;
          if (w.resting_hr >= avg + 5) flag(1, `Rusthartslag ${w.resting_hr} — ${Math.round(w.resting_hr - avg)} boven normaal`);
        }
        if (w.sleep_hrs != null) {
          if (w.sleep_hrs < 5.5) flag(2, `Slaap ${w.sleep_hrs.toFixed(1)} u — te kort`);
          else if (w.sleep_hrs < 6.5) flag(1, `Slaap ${w.sleep_hrs.toFixed(1)} u — aan de korte kant`);
          else reasons.push({ pts: 0, txt: `Slaap ${w.sleep_hrs.toFixed(1)} u` });
        }
        if (w.tsb != null) {
          if (w.tsb < -30) flag(2, `Vorm (TSB) ${Math.round(w.tsb)} — zwaar vermoeid`);
          else if (w.tsb < -25) flag(1, `Vorm (TSB) ${Math.round(w.tsb)} — vermoeid`);
        }
        if (w.readiness != null) {
          if (w.readiness < 40) flag(2, `Garmin gereedheid ${w.readiness}`);
          else if (w.readiness < 60) flag(1, `Garmin gereedheid ${w.readiness}`);
        }
      }
      const inj = getInjuries().filter(i => i.status !== 'hersteld');
      if (inj.some(i => i.severity === 'ernstig')) flag(2, 'Ernstige blessure actief');
      else if (inj.some(i => i.status === 'actief' && i.severity === 'matig')) flag(1, 'Blessure actief (matig)');
      const L = computeTrainingLoad();
      if (L.acwr != null) {
        if (L.acwr > 1.5) flag(2, `Belasting 7:28 = ${L.acwr.toFixed(2)} — hoog risico`);
        else if (L.acwr > 1.3) flag(1, `Belasting 7:28 = ${L.acwr.toFixed(2)} — verhoogd`);
      }

      if (!w && L.acwr == null && !inj.length) return null;
      const level = score >= 4 ? 'red' : score >= 2 ? 'orange' : 'green';
      const meta = {
        green:  { title: 'Vol gas', icon: '🟢', text: 'Je lichaam is hersteld. Train volgens plan — zware sessie kan.' },
        orange: { title: 'Rustig aan', icon: '🟠', text: 'Train, maar schaal de intensiteit: technisch werk, Z2 of ~70–80% van je gewichten.' },
        red:    { title: 'Rust', icon: '🔴', text: 'Neem rust of alleen mobiliteit/wandelen. Zware training kost je nu meer dan het oplevert.' },
      }[level];
      return { level, ...meta, reasons, wDate, stale: wDate && wDate !== today };
    }

    function renderDayAdviceCard() { return _safeHtml('renderDayAdviceCard', () => _renderDayAdviceCard()); }
    function _renderDayAdviceCard() {
      const a = computeDayAdvice();
      if (!a) return '';
      const reasons = a.reasons
        .sort((x, y) => y.pts - x.pts)
        .map(r => `<li class="${r.pts ? 'da-bad' : 'da-ok'}">${escapeHtml(r.txt)}</li>`).join('');
      return `<div class="day-advice day-advice-${a.level}" onclick="this.classList.toggle('open')">
        <div class="day-advice-head">
          <span class="day-advice-icon">${a.icon}</span>
          <div class="day-advice-main">
            <div class="day-advice-title">${a.title}</div>
            <div class="day-advice-text">${a.text}</div>
          </div>
          <div class="wod-chevron">▾</div>
        </div>
        <div class="day-advice-body">
          ${a.stale ? `<div class="day-advice-note">Meting van ${a.wDate} — vandaag nog geen data.</div>` : ''}
          <ul class="day-advice-reasons">${reasons}</ul>
          ${renderLoadCard({ compact: true })}
        </div>
      </div>`;
    }

    // ── Versheid per databron ─────────────────────────────────────────────
    const _SOURCE_DEFS = [
      { name: 'SugarWOD',      get: () => sugarwodFetchedAt || wodFetchedAt, maxH: 30, wf: 'Fetch SugarWOD' },
      { name: 'Intervals.icu', get: () => intervalsData?.fetched_at,       maxH: 9,  wf: 'Refresh Health Data' },
      { name: 'Strava',        get: () => stravaData?.fetched_at,          maxH: 9,  wf: 'Refresh Health Data' },
      { name: 'Withings',      get: () => withingsData?.fetched_at,        maxH: 9,  wf: 'Refresh Health Data' },
      { name: 'Weer/lucht',    get: () => environmentalData?.fetched_at,   maxH: 9,  wf: 'Refresh Health Data' },
    ];

    function sourceFreshness() {
      const now = Date.now();
      return _SOURCE_DEFS.map(s => {
        const ts = s.get();
        const ageH = ts ? (now - new Date(ts).getTime()) / 3600000 : null;
        const fail = workflowStatus?.[s.wf];
        const recentFail = fail?.last_failure && (now - new Date(fail.last_failure).getTime()) < 24 * 3600000
          && (!ts || new Date(fail.last_failure) > new Date(ts));
        const state = ageH == null ? 'missing' : ageH > s.maxH ? 'stale' : 'ok';
        return { ...s, ts, ageH, state, failUrl: recentFail ? fail.run_url : null };
      });
    }

    function renderFreshnessBlock() { return _safeHtml('renderFreshnessBlock', () => _renderFreshnessBlock()); }
    function _renderFreshnessBlock() {
      const rows = sourceFreshness().map(s => {
        const cls = s.failUrl || s.state !== 'ok' ? 'fresh-bad' : 'fresh-ok';
        const age = s.ts ? relTime(s.ts) : 'nog nooit';
        const fail = s.failUrl ? ` · <a href="${escapeHtml(s.failUrl)}" target="_blank" rel="noopener">laatste run mislukt</a>` : '';
        return `<div class="fresh-row ${cls}"><span class="fresh-dot"></span><span class="fresh-name">${s.name}</span><span class="fresh-age">${age}${fail}</span></div>`;
      }).join('');
      const failedOther = Object.entries(workflowStatus || {})
        .filter(([wf, v]) => v.last_failure && (Date.now() - new Date(v.last_failure).getTime()) < 24 * 3600000
          && !_SOURCE_DEFS.some(s => s.wf === wf))
        .map(([wf, v]) => `<div class="fresh-row fresh-bad"><span class="fresh-dot"></span><span class="fresh-name">${escapeHtml(wf)}</span><span class="fresh-age">mislukt ${relTime(v.last_failure)} · <a href="${escapeHtml(v.run_url || '#')}" target="_blank" rel="noopener">log</a></span></div>`)
        .join('');
      return `<div class="workflow-card fresh-card">
        <div class="workflow-title">🩺 Databronnen</div>
        <div class="workflow-desc">Wanneer elke bron voor het laatst is bijgewerkt. Rood = te oud of mislukt.</div>
        ${rows}${failedOther}
      </div>`;
    }

    // Klein waarschuwingsregeltje op Vandaag als er iets mis is.
    function renderFreshnessChip() { return _safeHtml('renderFreshnessChip', () => _renderFreshnessChip()); }
    function _renderFreshnessChip() {
      const bad = sourceFreshness().filter(s => s.failUrl || s.state === 'stale');
      if (!bad.length) return '';
      const txt = bad.map(s => `${s.name} ${s.failUrl ? 'mislukt' : (s.ageH != null ? Math.round(s.ageH) + 'u oud' : '')}`).join(' · ');
      return `<div class="fresh-chip" onclick="switchTab('acties')">⚠️ ${escapeHtml(txt)}</div>`;
    }

    // ── Prestatievoorspeller (5K + 12-minutentest) ────────────────────────
    // Riegel: T2 = T1 × (D2/D1)^1,06. Per week de beste voorspelling uit runs
    // ≥ 3 km. Rustige duurlopen voorspellen te traag; daarom telt alleen de
    // snelste run per week.
    function _runsHistory(weeks = 16) {
      const out = [];
      for (let i = 0; i < weeks * 7; i++) {
        const d = _isoDay(-i);
        activitiesForDay(d).forEach(a => {
          if (sportCategory(a.type) !== 'Hardlopen') return;
          const dist = Number(a.distance_m || 0), min = Number(a.duration_min || 0);
          if (dist < 3000 || min <= 0) return;
          const pace = min / (dist / 1000);
          if (pace < 3 || pace > 9) return; // onrealistisch (GPS-fout / wandelen)
          out.push({ date: d, dist, min });
        });
      }
      return out;
    }

    function predict5kMin(run) { return run.min * Math.pow(5000 / run.dist, 1.06); }
    function predict12minM(run) { return run.dist * Math.pow(12 / run.min, 1 / 1.06); }

    function _fmtMin(m) {
      const s = Math.round(m * 60);
      return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    }

    function computePerformanceTrend() {
      const runs = _runsHistory(16);
      if (!runs.length) return null;
      const weeks = {};
      runs.forEach(r => {
        const d = new Date(r.date + 'T12:00:00');
        const monday = new Date(d); monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
        const key = monday.toISOString().slice(0, 10);
        const p = predict5kMin(r);
        if (!weeks[key] || p < weeks[key].p5k) weeks[key] = { week: key, p5k: p, p12: predict12minM(r), run: r };
      });
      const series = Object.values(weeks).sort((a, b) => a.week.localeCompare(b.week));
      const last28 = runs.filter(r => r.date >= _isoDay(-28));
      const best = last28.length ? last28.reduce((b, r) => predict5kMin(r) < predict5kMin(b) ? r : b) : null;
      return { series, best };
    }

    let _perfChart = null;
    function renderPerformanceCard() { return _safeHtml('renderPerformanceCard', () => _renderPerformanceCard()); }
    function _renderPerformanceCard() {
      const t = computePerformanceTrend();
      if (!t) return '';
      const cur = t.best;
      const p5 = cur ? _fmtMin(predict5kMin(cur)) : '—';
      const p12 = cur ? Math.round(predict12minM(cur)) : null;
      const goalTxt = p12 == null ? '' : p12 >= 2700 ? '🏆 boven streefdoel (2700 m)'
        : p12 >= 2200 ? `✓ eis gehaald · nog ${2700 - p12} m tot streef` : `nog ${2200 - p12} m tot de eis (2200 m)`;
      return `<div class="perf-card">
        <div class="section-title">Prestatievoorspeller</div>
        <div class="perf-stats">
          <div><div class="perf-val">${p5}</div><div class="perf-lbl">5K (voorspeld)</div></div>
          <div><div class="perf-val">${p12 != null ? p12 + ' m' : '—'}</div><div class="perf-lbl">12-min test</div></div>
        </div>
        ${goalTxt ? `<div class="perf-goal">${goalTxt}</div>` : ''}
        <div class="perf-chart-wrap"><canvas id="perfChart" height="170"></canvas></div>
        <div class="perf-note">Op basis van je snelste run per week (≥ 3 km, formule van Riegel). Een echte test of wedstrijd geeft de zuiverste voorspelling.</div>
      </div>`;
    }

    function initPerformanceChart() {
      try { _initPerformanceChart(); } catch (e) { console.error('Grafiek mislukt:', e); }
    }
    function _initPerformanceChart() {
      const cv = document.getElementById('perfChart');
      const t = computePerformanceTrend();
      if (!cv || !t || typeof Chart === 'undefined') return;
      if (_perfChart) { _perfChart.destroy(); _perfChart = null; }
      const labels = t.series.map(s => { const d = new Date(s.week); return `${d.getDate()} ${MONTH_NL[d.getMonth()]}`; });
      const css = getComputedStyle(document.documentElement);
      const muted = css.getPropertyValue('--muted').trim() || '#888';
      _perfChart = new Chart(cv, {
        type: 'line',
        data: {
          labels,
          datasets: [
            { label: '12-min afstand (m)', data: t.series.map(s => Math.round(s.p12)), borderColor: '#00c853', backgroundColor: '#00c853', tension: 0.3, pointRadius: 3 },
            { label: 'Eis 2200 m', data: t.series.map(() => 2200), borderColor: '#f5a623', borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 },
            { label: 'Streef 2700 m', data: t.series.map(() => 2700), borderColor: '#e8ff3c', borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false, locale: 'nl-NL',
          plugins: {
            legend: { labels: { color: muted, boxWidth: 12, font: { size: 11 } } },
            tooltip: { callbacks: { afterLabel: ctx => ctx.datasetIndex === 0 ? `5K ≈ ${_fmtMin(t.series[ctx.dataIndex].p5k)}` : '' } },
          },
          scales: {
            x: { ticks: { color: muted, font: { size: 10 } }, grid: { display: false } },
            y: { ticks: { color: muted, font: { size: 10 } }, grid: { color: 'rgba(128,128,128,.15)' } },
          },
        },
      });
    }

    // ── Weekreview ────────────────────────────────────────────────────────
    function renderWeeklyReviewCard() { return _safeHtml('renderWeeklyReviewCard', () => _renderWeeklyReviewCard()); }
    function _renderWeeklyReviewCard() {
      const r = weeklyReview?.latest;
      if (!r) return '';
      const ageDays = (Date.now() - new Date(r.generated_at).getTime()) / 86400000;
      if (ageDays > 7.5) return '';
      const delta = (a, b, unit, dec = 1) => (a == null || b == null) ? '' :
        ` <span class="wr-delta">(${a - b >= 0 ? '+' : ''}${(a - b).toFixed(dec).replace('.', ',')}${unit})</span>`;
      const fmt = (v, dec = 1) => v == null ? '—' : Number(v).toFixed(dec).replace('.', ',');
      return `<div class="weekly-review" onclick="this.classList.toggle('open')">
        <div class="ai-coach-toggle">
          <div class="ai-coach-toggle-left">
            <div class="ai-coach-label">📈 Weekreview ${r.week_start.slice(5)} – ${r.week_end.slice(5)}</div>
            <div class="ai-coach-timestamp">${r.crossfit_classes}× CrossFit · ${fmt(r.run_km)} km · slaap ${fmt(r.sleep_avg_h)} u</div>
          </div>
          <div class="wod-chevron">▾</div>
        </div>
        <div class="weekly-review-body">
          <div class="wr-grid">
            <div><span>CrossFit</span><strong>${r.crossfit_classes}×</strong></div>
            <div><span>Hardlopen</span><strong>${r.runs}× · ${fmt(r.run_km)} km</strong></div>
            <div><span>Slaap gem.</span><strong>${fmt(r.sleep_avg_h)} u${delta(r.sleep_avg_h, r.sleep_avg_h_prev, 'u')}</strong></div>
            <div><span>HRV gem.</span><strong>${fmt(r.hrv_avg, 0)}${delta(r.hrv_avg, r.hrv_avg_prev, '', 0)}</strong></div>
            <div><span>Gewicht</span><strong>${fmt(r.weight_kg)} kg${delta(r.weight_kg, r.weight_kg_prev, ' kg')}</strong></div>
            <div><span>Belasting 7:28</span><strong>${r.acwr == null ? '—' : fmt(r.acwr, 2)}</strong></div>
          </div>
          ${r.advice ? `<div class="ai-coach-body">${safeMarkdown(r.advice)}</div>` : ''}
        </div>
      </div>`;
    }

    // ── Vakantiemodus ─────────────────────────────────────────────────────
    function isOnVacation(dateStr) {
      return (vacations || []).some(v => v.from <= dateStr && dateStr <= v.to);
    }

    function renderVacationCard() { return _safeHtml('renderVacationCard', () => _renderVacationCard()); }
    function _renderVacationCard() {
      const today = _isoDay(0);
      const list = (vacations || []).filter(v => v.to >= today).sort((a, b) => a.from.localeCompare(b.from));
      const rows = list.map(v => `<div class="vac-row">
          <span>🏖 ${escapeHtml(v.from)} t/m ${escapeHtml(v.to)}${v.note ? ` — ${escapeHtml(v.note)}` : ''}${v.from <= today && today <= v.to ? ' <strong>(nu actief)</strong>' : ''}</span>
          <button class="vac-del" onclick="removeVacation('${escapeHtml(v.from)}','${escapeHtml(v.to)}')" aria-label="Verwijderen">✕</button>
        </div>`).join('');
      return `<div class="workflow-card" id="vacationCard">
        <div class="workflow-title">🏖 Vakantiemodus</div>
        <div class="workflow-desc">Automatisch inschrijven staat uit in deze periodes. Al geboekte lessen blijven staan — annuleer die zelf in Huppa.</div>
        ${rows || '<div class="injury-empty">Geen vakantie gepland.</div>'}
        <div class="vac-form">
          <label>Van <input type="date" id="vacFrom" min="${today}"></label>
          <label>Tot en met <input type="date" id="vacTo" min="${today}"></label>
          <input type="text" id="vacNote" class="config-input" placeholder="Notitie (optioneel)">
          <button class="workflow-btn info" onclick="addVacation()">Toevoegen</button>
        </div>
      </div>`;
    }

    async function _patchVacations(mutate) {
      const token = _ghToken();
      if (!token || !currentGistId) throw new Error('GitHub token vereist — stel in via Acties');
      const headers = { Authorization: `token ${token}`, 'Content-Type': 'application/json' };
      const r = await fetch(`https://api.github.com/gists/${currentGistId}`, { headers, cache: 'no-store' });
      if (!r.ok) throw new Error(`Gist laden mislukt: ${r.status}`);
      const gist = await r.json();
      await hydrateTruncatedFiles(gist, { Authorization: `token ${token}` });
      const state = JSON.parse(gist.files['sportbit_state.json']?.content || '{}');
      state.vacations = mutate(Array.isArray(state.vacations) ? state.vacations : []);
      const p = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        method: 'PATCH', headers,
        body: JSON.stringify({ files: { 'sportbit_state.json': { content: JSON.stringify(state, null, 2) } } }),
      });
      if (!p.ok) throw new Error(`Opslaan mislukt: ${p.status}`);
      vacations = state.vacations;
    }

    async function addVacation() {
      const from = document.getElementById('vacFrom')?.value;
      const to = document.getElementById('vacTo')?.value;
      const note = (document.getElementById('vacNote')?.value || '').trim();
      if (!from || !to) { showToast('Vul begin- en einddatum in', { type: 'error' }); return; }
      if (to < from) { showToast('Einddatum ligt vóór de begindatum', { type: 'error' }); return; }
      try {
        await _patchVacations(list => [...list.filter(v => !(v.from === from && v.to === to)), { from, to, note }]);
        showToast(`🏖 Vakantie ${from} t/m ${to} opgeslagen — geen automatische inschrijvingen`, { type: 'ok', duration: 5000 });
        loadData();
      } catch (e) { showToast(e.message, { type: 'error' }); }
    }

    async function removeVacation(from, to) {
      const removed = (vacations || []).find(v => v.from === from && v.to === to);
      try {
        await _patchVacations(list => list.filter(v => !(v.from === from && v.to === to)));
        loadData();
        showToast('Vakantie verwijderd', {
          duration: 7000, actionLabel: 'Ongedaan maken',
          onAction: async () => {
            try { await _patchVacations(list => [...list, removed]); loadData(); }
            catch (e) { showToast(e.message, { type: 'error' }); }
          },
        });
      } catch (e) { showToast(e.message, { type: 'error' }); }
    }

    // ── GitHub-token uitleg ───────────────────────────────────────────────
    function renderTokenHelp() {
      return `<details class="token-help">
        <summary>🔐 Welk token gebruik ik?</summary>
        <ol>
          <li>Ga op github.com naar <em>Settings → Developer settings → Personal access tokens → Fine-grained tokens</em>.</li>
          <li>Kies <em>Generate new token</em>, vervaldatum max. 1 jaar.</li>
          <li><em>Repository access</em>: alleen <code>ralphdeleeuw/sportbit</code>.</li>
          <li><em>Repository permissions</em>: <strong>Actions: Read and write</strong> (knoppen) — verder niets.</li>
          <li><em>Account permissions</em>: <strong>Gists: Read and write</strong>.</li>
          <li>Plak het token hierboven en verwijder je oude token (classic <code>ghp_…</code>) op GitHub.</li>
        </ol>
        <div class="token-help-note">Het token staat alleen op dit apparaat. Een fine-grained token kan niets anders dan deze app — lekt het uit, dan blijft de schade beperkt.</div>
      </details>`;
    }
