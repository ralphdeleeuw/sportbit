    // health.js — Benchmarks, databronnen, herstelblok, omgeving en barbell-grafieken.
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
      let categories;
      try { categories = JSON.parse(raw.textContent); } catch(e) { return; }
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
          { label: 'Huidtemp °C', get: r => r.skin_temp_c != null ? r.skin_temp_c.toFixed(2) : null },
          { label: 'Endurance', key: 'endurance_score' },
          { label: 'Hill',      key: 'hill_score' },
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
          { label: 'Stap m',   get: r => r.stride_length_m != null ? r.stride_length_m.toFixed(2) : null },
          { label: 'GCT ms',   get: r => r.ground_contact_ms != null ? Math.round(r.ground_contact_ms) : null },
          { label: 'Vert.osc', get: r => r.vert_oscillation_mm != null ? r.vert_oscillation_mm.toFixed(1) : null },
          { label: 'Vert.%',   get: r => r.vert_ratio_pct != null ? r.vert_ratio_pct.toFixed(1) : null },
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
      const tsbColor = tsb == null ? '#888'
        : tsb > 5 ? '#2ecc71'
        : tsb > 0 ? '#27ae60'
        : tsb > -10 ? '#f39c12'
        : tsb > -30 ? '#3498db'
        : '#e74c3c';
      const tsbLabel = tsb == null ? ''
        : tsb > 5 ? 'Fris'
        : tsb > 0 ? 'Overgang'
        : tsb > -10 ? 'Grijze zone'
        : tsb > -30 ? 'Optimaal'
        : 'Hoog risico';
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
          let hrvStr = `HRV <strong${col} title="Vandaag${baselineTitle}">${Math.round(w.hrv)}ms</strong>${statusBadge}${trendBadge}`;
          if (w.hrv_sdnn != null) hrvStr += ` <span style="color:#888;font-size:0.8em">SDNN ${Math.round(w.hrv_sdnn)}ms</span>`;
          p.push(hrvStr);
        }
        if (w.resting_hr != null)  p.push(`RHR <strong>${w.resting_hr}bpm</strong>`);
        if (w.avg_sleeping_hr != null) p.push(`Slaap-HR <strong>${Math.round(w.avg_sleeping_hr)}bpm</strong>`);
        if (w.readiness != null) {
          const rColor = w.readiness >= 70 ? '#2ecc71' : w.readiness >= 40 ? '#f39c12' : '#e74c3c';
          p.push(`Gereedheid <strong style="color:${rColor}">${w.readiness}</strong>`);
        }
        if (w.sleep_hrs != null) {
          let s = `Slaap <strong>${w.sleep_hrs.toFixed(1)}u`;
          if (w.sleep_score != null) s += ` (${w.sleep_score})`;
          if (w.sleep_quality != null) s += ` kw:${w.sleep_quality}`;
          p.push(s + '</strong>');
        }
        if (w.respiration != null) p.push(`Adem <strong>${w.respiration.toFixed(1)}/min</strong>`);
        if (w.spo2 != null) {
          let spo2Str = `SpO₂ <strong>${w.spo2}%`;
          if (spo2Avg != null && Math.abs(w.spo2 - spo2Avg) >= 0.5)
            spo2Str += ` <span class="rec-avg">gem ${spo2Avg}%</span>`;
          p.push(spo2Str + '</strong>');
        }
        if (w.bp_systolic != null && w.bp_diastolic != null)
          p.push(`Bloeddruk <strong>${w.bp_systolic}/${w.bp_diastolic}</strong>`);
        if (w.body_fat_pct != null) p.push(`Vet <strong>${w.body_fat_pct}%</strong>`);
        // Fenix 8 Elevate V5: huidtemperatuur(-afwijking) als herstel-/ziekte-indicator
        if (w.skin_temp_c != null) {
          const sign = w.skin_temp_c > 0 ? '+' : '';
          p.push(`Huidtemp <strong>${sign}${w.skin_temp_c.toFixed(2)}°C</strong>`);
        }
        // Fenix 8 Garmin prestatie-scores (indien gesynct via intervals.icu)
        if (w.endurance_score != null) p.push(`Endurance <strong>${w.endurance_score}</strong>`);
        if (w.hill_score != null) p.push(`Hill <strong>${w.hill_score}</strong>`);
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

    // ── Barbell progressie (chart + table) ────────────────────────────────

    // Top lifts to show buttons for (most common CrossFit barbell movements)
    const TOP_LIFTS = [
      'Back Squat', 'Deadlift', 'Clean & Jerk', 'Snatch', 'Front Squat',
      'Bench Press', 'Shoulder Press', 'Clean', 'Push Jerk',
    ];

    function renderBarbellSection() {
      return renderBarbellTable();
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

