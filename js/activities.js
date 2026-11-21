    // activities.js — Strava/Intervals-blokken, hardloopplan-sectie en activiteitkaarten.
    function renderStravaBlock(date, typeFilter, keywords, excludeKeywords, allowIds) {
      if (!stravaData) return '';
      const _rtS = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
      let acts = (stravaData.activities_by_date || {})[date];
      if (!acts || acts.length === 0) return '';
      if (typeFilter === 'run') acts = acts.filter(a => _rtS.some(rt => (a.type || '').toLowerCase().includes(rt)));
      else if (typeFilter === 'non-run') acts = acts.filter(a => !_rtS.some(rt => (a.type || '').toLowerCase().includes(rt)));
      else if (keywords) acts = acts.filter(a => keywords.some(k => (a.type || '').toLowerCase().includes(k)));
      if (excludeKeywords && excludeKeywords.length) acts = acts.filter(a => !excludeKeywords.some(k => (a.type || '').toLowerCase().includes(k)));
      if (allowIds) acts = acts.filter(a => allowIds.has(a.activity_id));
      if (acts.length === 0) return '';
      return acts.map(act => {
        const dur     = act.duration_min ? `<span class="strava-stat"><strong>${act.duration_min}</strong> min</span>` : '';
        const elapsed = act.elapsed_min  ? `<span class="strava-stat">totaal <strong>${act.elapsed_min}</strong> min</span>` : '';
        const hr      = act.avg_hr   ? `<span class="strava-stat">gem.HR <strong>${Math.round(act.avg_hr)}</strong> bpm</span>` : '';
        const hrMax   = act.max_hr   ? `<span class="strava-stat">max.HR <strong>${Math.round(act.max_hr)}</strong> bpm</span>` : '';
        const cal     = act.calories ? `<span class="strava-stat"><strong>${Math.round(act.calories)}</strong> kcal</span>` : '';
        const suffer  = act.suffer_score       ? `<span class="strava-stat">RE <strong>${Math.round(act.suffer_score)}</strong></span>` : '';
        const rpe     = act.perceived_exertion ? `<span class="strava-stat">RPE <strong>${act.perceived_exertion}</strong></span>` : '';
        const power   = act.avg_watts ? `<span class="strava-stat">⚡ <strong>${Math.round(act.avg_watts)}</strong> W</span>` : '';
        const name    = act.name ? ` — ${act.name}` : '';
        return `<div class="strava-block">
          <div class="strava-block-label">Strava${name}</div>
          ${dur}${elapsed}${power}${hr}${hrMax}${cal}${suffer}${rpe}
        </div>`;
      }).join('');
    }

    // Herbruikbare zone-verdeling balk (HR- of tempozones): seconden per zone.
    const _PACE_ZONE_COLORS = ['#bbdefb','#90caf9','#64b5f6','#42a5f5','#1e88e5','#1565c0'];
    const _PACE_ZONE_LABELS = ['Z1','Z2','Z3','Z4','Z5','Z6'];
    function _renderZoneBar(times, labels, colors, heading) {
      if (!Array.isArray(times) || times.length < 2) return '';
      const total = times.reduce((s, v) => s + (v || 0), 0);
      if (total <= 0) return '';
      const bars = times.map((s, i) => {
        const pct = Math.round((s || 0) / total * 100);
        if (pct < 1) return '';
        const mins = Math.floor((s || 0) / 60);
        return `<div title="${labels[i]}: ${mins}min (${pct}%)" style="width:${pct}%;background:${colors[i] || '#888'};height:100%;display:inline-block;vertical-align:top"></div>`;
      }).join('');
      const lab = times.map((s, i) => {
        const pct = Math.round((s || 0) / total * 100);
        if (pct < 5) return '';
        return `<span style="color:${colors[i] || '#888'};font-size:0.7rem">${labels[i]} ${pct}%</span>`;
      }).filter(Boolean).join(' ');
      const head = heading ? `<div style="font-size:0.68rem;color:#6a9a7a;margin-bottom:0.15rem">${heading}</div>` : '';
      return `<div style="margin-top:0.4rem">${head}
        <div style="height:6px;border-radius:3px;overflow:hidden;background:rgba(255,255,255,0.1)">${bars}</div>
        <div style="margin-top:0.2rem;display:flex;gap:0.5rem;flex-wrap:wrap">${lab}</div>
      </div>`;
    }

    function renderIntervalsBlock(date, typeFilter, keywords, excludeKeywords, allowIds) {
      if (!intervalsData) return '';
      const runTypes = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
      let acts = ((intervalsData.activities || {}).by_date || {})[date];
      if (!acts || acts.length === 0) return '';
      if (typeFilter === 'run') acts = acts.filter(a => runTypes.some(rt => (a.type || '').toLowerCase().includes(rt)));
      else if (typeFilter === 'non-run') acts = acts.filter(a => !runTypes.some(rt => (a.type || '').toLowerCase().includes(rt)));
      else if (keywords) acts = acts.filter(a => keywords.some(k => (a.type || '').toLowerCase().includes(k)));
      if (excludeKeywords && excludeKeywords.length) acts = acts.filter(a => !excludeKeywords.some(k => (a.type || '').toLowerCase().includes(k)));
      if (allowIds) acts = acts.filter(a => allowIds.has(a.intervals_id));
      if (acts.length === 0) return '';
      return acts.map(act => {
        const isRun = runTypes.some(rt => (act.type || '').toLowerCase().includes(rt));
        const dur     = act.duration_min  ? `<span class="strava-stat"><strong>${act.duration_min}</strong> min</span>` : '';
        const hr      = act.avg_hr        ? `<span class="strava-stat">gem.HR <strong>${act.avg_hr}</strong> bpm</span>` : '';
        const hrMax   = act.max_hr        ? `<span class="strava-stat">max.HR <strong>${act.max_hr}</strong> bpm</span>` : '';
        const cal     = act.calories      ? `<span class="strava-stat"><strong>${act.calories}</strong> kcal</span>` : '';
        const tl      = act.training_load != null ? `<span class="strava-stat">TL <strong>${Math.round(act.training_load)}</strong></span>` : '';
        const trimp   = act.trimp != null ? `<span class="strava-stat">TRIMP <strong>${Math.round(act.trimp)}</strong></span>` : '';
        const dist    = act.distance_m    ? `<span class="strava-stat"><strong>${(act.distance_m / 1000).toFixed(1)}</strong> km</span>` : '';
        const pace    = (isRun && act.avg_speed_ms > 0)
          ? (() => { const spm = 1000 / act.avg_speed_ms / 60; return `<span class="strava-stat">tempo <strong>${Math.floor(spm)}:${String(Math.round((spm % 1) * 60)).padStart(2,'0')}/km</strong></span>`; })()
          : '';
        const elev    = act.elevation_m   ? `<span class="strava-stat">↑ <strong>${act.elevation_m}</strong> m</span>` : '';
        const rpe     = act.rpe != null   ? `<span class="strava-stat">RPE <strong>${act.rpe}</strong></span>` : '';
        const cadence = act.avg_cadence   ? `<span class="strava-stat">cadans <strong>${isRun ? Math.round(act.avg_cadence * 2) : Math.round(act.avg_cadence)}</strong> ${isRun ? 'spm' : 'rpm'}</span>` : '';
        const temp    = act.avg_temp_c != null ? `<span class="strava-stat">🌡 <strong>${act.avg_temp_c}°C</strong></span>` : '';
        // Vermogen: bij hardlopen is dit running power (Fenix 8 vanaf de pols), bij fietsen wattage
        const power   = act.avg_watts     ? `<span class="strava-stat">⚡ <strong>${Math.round(act.avg_watts)}</strong> W</span>` : '';
        // Running dynamics (Fenix 8) — alleen tonen bij hardlopen
        const stride  = (isRun && act.stride_length_m)    ? `<span class="strava-stat">stap <strong>${act.stride_length_m.toFixed(2)}</strong> m</span>` : '';
        const gct     = (isRun && act.ground_contact_ms)  ? `<span class="strava-stat">GCT <strong>${Math.round(act.ground_contact_ms)}</strong> ms</span>` : '';
        const vosc    = (isRun && act.vert_oscillation_mm)? `<span class="strava-stat">vert.osc <strong>${act.vert_oscillation_mm.toFixed(1)}</strong> mm</span>` : '';
        const vratio  = (isRun && act.vert_ratio_pct)     ? `<span class="strava-stat">vert.ratio <strong>${act.vert_ratio_pct.toFixed(1)}</strong>%</span>` : '';
        const flags   = [act.indoor ? '🏠 Indoor' : '', act.race ? '🏁 Race' : ''].filter(Boolean).map(f => `<span class="strava-stat">${f}</span>`).join('');
        const name    = act.name || act.type || 'Activiteit';

        // HR-zone balk: [Z1, Z2, Z3, Z4, Z5] in seconden
        let hrZoneHtml = '';
        if (act.hr_zone_times && act.hr_zone_times.length >= 2) {
          const zColors = ['#4db6ac','#66bb6a','#ffa726','#ef5350','#ab47bc'];
          const zLabels = ['Z1','Z2','Z3','Z4','Z5'];
          const total = act.hr_zone_times.reduce((s, v) => s + v, 0);
          if (total > 0) {
            const bars = act.hr_zone_times.map((s, i) => {
              const pct = Math.round(s / total * 100);
              if (pct < 1) return '';
              const mins = Math.floor(s / 60);
              return `<div title="${zLabels[i]}: ${mins}min (${pct}%)" style="width:${pct}%;background:${zColors[i] || '#888'};height:100%;display:inline-block;vertical-align:top"></div>`;
            }).join('');
            const labels = act.hr_zone_times.map((s, i) => {
              const pct = Math.round(s / total * 100);
              if (pct < 5) return '';
              return `<span style="color:${zColors[i] || '#888'};font-size:0.7rem">${zLabels[i]} ${pct}%</span>`;
            }).filter(Boolean).join(' ');
            hrZoneHtml = `<div style="margin-top:0.4rem">
              <div style="height:6px;border-radius:3px;overflow:hidden;background:rgba(255,255,255,0.1)">${bars}</div>
              <div style="margin-top:0.2rem;display:flex;gap:0.5rem;flex-wrap:wrap">${labels}</div>
            </div>`;
          }
        }

        // Tempozone balk: [Z1..Z6] in seconden (intervals.icu "Tempozones")
        const paceZoneHtml = (isRun && act.pace_zone_times)
          ? _renderZoneBar(act.pace_zone_times, _PACE_ZONE_LABELS, _PACE_ZONE_COLORS, 'Tempozones')
          : '';

        let lapsHtml = '';
        if (isRun && act.laps && act.laps.length > 1) {
          const lapRows = act.laps.map((lap, i) => {
            const d = lap.distance_m ? `${lap.distance_m}m` : '';
            const p = lap.pace_per_km ? `${lap.pace_per_km}/km` : '';
            const h = lap.avg_hr ? `${lap.avg_hr}bpm` : '';
            const c = lap.avg_cadence ? `${Math.round(lap.avg_cadence * 2)}spm` : '';
            return `<div style="display:flex;gap:0.6rem;font-size:0.75rem;color:#c0e8d0;padding:0.1rem 0">
              <span style="color:#6a9a7a;min-width:1.2rem">${i+1}</span>
              <span>${[d,p,h,c].filter(Boolean).join(' · ')}</span></div>`;
          }).join('');
          lapsHtml = `<div style="margin-top:0.4rem;border-top:1px solid rgba(0,200,83,0.15);padding-top:0.4rem">${lapRows}</div>`;
        }

        return `<div class="strava-block">
          <div class="strava-block-label">Intervals — ${name}${flags ? ' ' + flags : ''}</div>
          ${dist}${dur}${pace}${power}${cadence}${stride}${gct}${vosc}${vratio}${hr}${hrMax}${elev}${cal}${rpe}${tl}${trimp}${temp}${hrZoneHtml}${paceZoneHtml}${lapsHtml}
        </div>`;
      }).join('');
    }

    function renderRunningPlanSection() {
      if (!runningPlanData) return '';
      const workouts = runningPlanData.workouts || [];
      if (workouts.length === 0) return '';

      const weekBadge = runningPlanData.week_number
        ? `<span class="run-badge">Week ${runningPlanData.week_number}</span>` : '';

      // Sessiefrequentie + dagkeuze selector
      const freqThis = parseInt(healthInput?.sessions_per_week ?? 2);
      const freqNext = parseInt(healthInput?.sessions_next_week ?? healthInput?.sessions_per_week ?? 2);
      const DAY_NAMES_SHORT = ['ma','di','wo','do','vr','za','zo'];
      const todayWd = (new Date().getDay() + 6) % 7; // Mon=0…Sun=6
      const thisWeekDays = healthInput?.run_days_this_week || defaultDaysForFreq(freqThis);
      const nextWeekDays = healthInput?.run_days_next_week || defaultDaysForFreq(freqNext);
      const renderDayBtns = (selected, disablePast, fn) =>
        DAY_NAMES_SHORT.map((name, wd) => {
          const active = selected.includes(wd) ? ' active' : '';
          const dis = disablePast && wd < todayWd ? ' disabled' : '';
          return `<button class="run-freq-day-btn${active}${dis}"${dis?' disabled':''} onclick="${fn}(${wd})">${name}</button>`;
        }).join('');
      const freqHtml = `<div class="run-freq-wrapper">
        <div class="run-freq-row">
          <span class="run-freq-label">Deze week:</span>
          <div class="run-freq-btns">
            ${[1,2,3].map(n => `<button class="run-freq-btn${freqThis===n?' active':''}" onclick="setSessionsPerWeek(${n})">${n}×</button>`).join('')}
          </div>
          <span id="run-freq-this-status" class="run-freq-status"></span>
        </div>
        <div class="run-freq-days-row">${renderDayBtns(thisWeekDays, true, 'toggleRunDayThisWeek')}</div>
        <div class="run-freq-row" style="margin-top:8px">
          <span class="run-freq-label">Volgende week:</span>
          <div class="run-freq-btns">
            ${[1,2,3].map(n => `<button class="run-freq-btn${freqNext===n?' active':''}" onclick="setSessionsNextWeek(${n})">${n}×</button>`).join('')}
          </div>
          <span id="run-freq-next-status" class="run-freq-status"></span>
        </div>
        <div class="run-freq-days-row">${renderDayBtns(nextWeekDays, false, 'toggleRunDayNextWeek')}</div>
      </div>`;

      // Defensie fitnesstest voortgangsbalk — twee doelen: 2200m (eis) en 2700m (streef)
      const defStart  = 2100; // baseline o.b.v. huidige 5K (~5:36/km × 12min)
      const defEis    = 2200; // minimumeis defensie (fase 1)
      const defStreef = 2700; // streefdoel defensie (fase 2)
      const rawEst12m = runningPlanData.estimated_12min_distance_m;
      const est12m = (rawEst12m && rawEst12m >= 1500 && rawEst12m <= 3500) ? rawEst12m : null;
      let progressHtml = '';
      if (est12m) {
        const clampedEst = Math.min(Math.max(est12m, defStart), defStreef);
        const pct      = Math.round((clampedEst - defStart) / (defStreef - defStart) * 100);
        const eisPct   = Math.round((defEis   - defStart) / (defStreef - defStart) * 100);
        const statusText = est12m >= defEis
          ? `✓ Fase 1 gehaald${est12m >= defStreef ? ' · ✓ Fase 2 gehaald' : ` · nog ${defStreef - est12m}m tot fase 2`}`
          : `Nog ${defEis - est12m}m tot eis (fase 1)`;
        progressHtml = `<div class="run-5k-progress">
          <div class="run-5k-labels">
            <span>Defensietest 12min</span>
            <span style="color:#e8ff3c">Huidig: <strong>~${est12m}m</strong></span>
          </div>
          <div class="run-5k-bar-track" style="position:relative">
            <div class="run-5k-bar-fill" style="width:${pct}%"></div>
            <div style="position:absolute;top:-8px;left:${eisPct}%;transform:translateX(-50%);font-size:10px;color:#ff9800" title="Fase 1 eis">▼${defEis}m</div>
          </div>
          <div class="run-5k-sub">${statusText} · fase 2: ${defStreef}m</div>
        </div>`;
      }

      // Collect past run dates from Intervals/Strava not already in the plan
      const today = new Date().toISOString().slice(0, 10);
      const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 42);
      const cutoffStr = cutoff.toISOString().slice(0, 10);
      const runTypes = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
      const planDates = new Set(workouts.map(s => s.date));

      const pastRunDates = new Set();
      Object.keys((intervalsData?.activities || {}).by_date || {}).forEach(date => {
        if (date < cutoffStr || date >= today || planDates.has(date)) return;
        const acts = ((intervalsData.activities || {}).by_date || {})[date] || [];
        if (acts.some(a => runTypes.some(rt => (a.type || '').toLowerCase().includes(rt)))) pastRunDates.add(date);
      });
      Object.keys(stravaData?.activities_by_date || {}).forEach(date => {
        if (date < cutoffStr || date >= today || planDates.has(date) || pastRunDates.has(date)) return;
        const acts = (stravaData.activities_by_date || {})[date] || [];
        if (acts.some(a => runTypes.some(rt => (a.type || '').toLowerCase().includes(rt)))) pastRunDates.add(date);
      });

      // Build all sessions split into three buckets
      const orphanSessions = Array.from(pastRunDates)
        .map(date => ({ date, session: 'long_run', name: null, _orphan: true }));

      const futureSessions = [
        ...workouts.filter(s => s.date > today && !s.cancelled),
      ].sort((a, b) => a.date.localeCompare(b.date));

      const todaySessions = [
        ...workouts.filter(s => s.date === today && !s.cancelled),
        ...orphanSessions.filter(s => s.date === today),
      ];

      const pastAllSessions = [
        ...workouts.filter(s => s.date < today || s.cancelled),
        ...orphanSessions.filter(s => s.date < today),
      ].sort((a, b) => b.date.localeCompare(a.date));

      const divider = label => `<div class="run-section-divider"><span>${label}</span></div>`;

      let cardsHtml = '';
      if (futureSessions.length) cardsHtml += futureSessions.map((s, i) => renderRunEventCard(s, i * 0.05, 'plan')).join('');
      if (todaySessions.length) cardsHtml += divider('Vandaag') + todaySessions.map((s, i) => renderRunEventCard(s, i * 0.05, 'plan')).join('');
      if (pastAllSessions.length) {
        const sep = (futureSessions.length || todaySessions.length) ? divider('Geweest') : '';
        cardsHtml += sep + pastAllSessions.map((s, i) => renderRunEventCard(s, i * 0.05, 'plan')).join('');
      }

      const phaseOverviewHtml = renderRunningPhaseOverview(runningPlanData.week_number);

      return `<div class="run-plan-header">
          <span class="run-plan-label">Hardloopplan</span>${weekBadge}
        </div>
        ${freqHtml}
        ${progressHtml}
        ${phaseOverviewHtml}
        <div class="cards">${cardsHtml}</div>`;
    }

    function getRunPhaseInfo(w) {
      const test = w % 2 === 0 ? '12-min test 🎯' : 'Threshold run';
      // Fase 1: weken 1-10 (2200m doel)
      if (w <= 4)  return { label: 'Fase 1 · Basis',     color: '#4caf50', di: 'Lichte fartlek (Z2-Z3)',           vr: test };
      if (w <= 8)  return { label: 'Fase 1 · Aëroob',    color: '#2196f3', di: '400m/600m @ testpace',             vr: test };
      if (w <= 10) return { label: 'Fase 1 · Intensiteit',color:'#ff9800', di: '200m/300m sprints',                vr: test };
      // Fase 2: weken 11+ (2700m doel)
      if (w <= 14) return { label: 'Fase 2 · Basis',     color: '#4caf50', di: 'Fartlek fase-2 paces',             vr: test };
      if (w <= 18) return { label: 'Fase 2 · Aëroob',    color: '#2196f3', di: '400m/600m @ fase-2 paces',        vr: test };
      if (w % 4 === 0) return { label: 'Herstelweek',    color: '#9c27b0', di: 'Lichte easy run',                  vr: w % 2 === 0 ? '12-min test 🎯' : 'Korte tempo (−30%)' };
      return                 { label: 'Fase 2 · Intensiteit', color: '#f44336', di: '200m/300m fase-2 paces',      vr: test };
    }

    function renderRunningPhaseOverview(currentWeek) {
      if (!currentWeek) return '';
      const stored = localStorage.getItem('runPlanExpanded') === 'true';
      let rows = '';
      for (let i = 0; i < 10; i++) {
        const w = currentWeek + i;
        const p = getRunPhaseInfo(w);
        const isCurrent = i === 0;
        rows += `<div class="run-phase-row${isCurrent ? ' current-week' : ''}">
          <div class="run-phase-week-num">W${w}${isCurrent ? ' ←' : ''}</div>
          <div class="run-phase-label" style="background:${p.color}">${p.label}</div>
          <div class="run-phase-sessions">
            <span>Di</span> ${p.di}<br>
            <span>Vr</span> ${p.vr}
          </div>
        </div>`;
      }
      return `<button class="run-phase-toggle${stored ? ' expanded' : ''}" onclick="
        const el=this.nextElementSibling;
        const open=el.classList.toggle('open');
        this.classList.toggle('expanded',open);
        localStorage.setItem('runPlanExpanded',open);
      ">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M4 2l4 4-4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        10-weken plan
      </button>
      <div class="run-phase-overview${stored ? ' open' : ''}">${rows}</div>`;
    }

    function renderActivityCard(date, delay, runOnly, excludeKeywords) {
      const _rtA = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
      const tf = runOnly ? 'run' : null;
      let acts = ((intervalsData?.activities || {}).by_date || {})[date] || [];
      let stravaActs = (stravaData?.activities_by_date || {})[date] || [];
      if (runOnly) {
        acts = acts.filter(a => _rtA.some(rt => (a.type || '').toLowerCase().includes(rt)));
        stravaActs = stravaActs.filter(a => _rtA.some(rt => (a.type || '').toLowerCase().includes(rt)));
      }
      // Activiteiten die al door een handmatig personal event op deze datum geclaimd zijn,
      // niet nogmaals als losse kaart tonen.
      if (excludeKeywords && excludeKeywords.length) {
        acts = acts.filter(a => !excludeKeywords.some(k => (a.type || '').toLowerCase().includes(k)));
        stravaActs = stravaActs.filter(a => !excludeKeywords.some(k => (a.type || '').toLowerCase().includes(k)));
      }
      if (acts.length === 0 && stravaActs.length === 0) return '';

      const intervalsHtml = renderIntervalsBlock(date, tf, null, excludeKeywords);
      const stravaHtml = intervalsHtml ? '' : renderStravaBlock(date, tf, null, excludeKeywords);
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
            <div class="card-header" onclick="toggleWod(this.closest('.card'), event)" style="cursor:pointer">
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

    function toggleWod(card, e) {
      const evt = e || event;
      if (evt && evt.target && evt.target.closest &&
          evt.target.closest('.run-reschedule-btn, .run-reschedule-form, .personal-edit-btn, .personal-edit-panel, .wod-edit-btn, .wod-edit-panel, .wod-deleted-toggle, .wod-deleted-list, .wod-restore-btn, .wod-delete-btn')) return;
      card.classList.toggle('open');
    }


