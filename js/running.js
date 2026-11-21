    // running.js — Hardloopworkout-kaarten, run-analyse, verplaatsen en annuleren.
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
      if (act.gap_speed_ms > 0) {
        const g = 1000 / act.gap_speed_ms / 60;
        parts.push(`GAP <strong>${Math.floor(g)}:${String(Math.round((g % 1) * 60)).padStart(2,'0')}/km</strong>`);
      }
      if (act.avg_hr) parts.push(`gem.HR <strong>${act.avg_hr} bpm</strong>`);
      if (act.max_hr) parts.push(`max.HR <strong>${act.max_hr} bpm</strong>`);
      if (act.avg_watts) parts.push(`⚡ <strong>${Math.round(act.avg_watts)} W</strong>${act.weighted_watts ? ` (gew. ${Math.round(act.weighted_watts)} W)` : ''}`);
      if (act.decoupling_pct != null) parts.push(`drift <strong>${act.decoupling_pct}%</strong>`);
      if (act.stride_length_m) parts.push(`stap <strong>${act.stride_length_m.toFixed(2)} m</strong>`);
      if (act.ground_contact_ms) parts.push(`GCT <strong>${Math.round(act.ground_contact_ms)} ms</strong>`);
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

    // ── Run-analyse (gepland vs werkelijk) ─────────────────────────────────────
    function _analysisForDate(date) {
      return ((runningAnalysisData || {}).by_date || {})[date] || null;
    }

    function _pendingAdjustmentsForDate(date) {
      return ((runningAnalysisData || {}).pending_adjustments || [])
        .filter(a => (a.target_date || '').slice(0, 10) === date && a.status === 'pending');
    }

    const _VERDICT_BADGE = {
      on_target: { label: '✅ Volgens plan', color: '#4caf50', bg: 'rgba(76,175,80,0.15)' },
      faster:    { label: '⚡ Sneller', color: '#42a5f5', bg: 'rgba(66,165,245,0.15)' },
      slower:    { label: '🐢 Trager', color: '#ffa726', bg: 'rgba(255,167,38,0.15)' },
      partial:   { label: '◑ Deels', color: '#ffb300', bg: 'rgba(255,179,0,0.15)' },
      missed:    { label: '✕ Gemist', color: '#ff6b6b', bg: 'rgba(255,107,107,0.15)' },
    };

    function _stepBriefLine(s) {
      if (s.type === 'repeat') {
        return `${s.count}× (${(s.children || []).map(_stepBriefLine).filter(Boolean).join(', ')})`;
      }
      if (s.type === 'rest') return `${s.duration_s || '?'}s rust`;
      const dist = s.distance_m ? `${s.distance_m}m` : (s.duration_s ? `${Math.round(s.duration_s/60)}min` : '');
      const pace = s.pace_min && s.pace_max ? `${s.pace_min}-${s.pace_max}` : (s.pace_target || '');
      const label = s.type === 'warmup' ? 'WU ' : s.type === 'cooldown' ? 'CD ' : '';
      return `${label}${dist}${pace ? ' @ ' + pace : ''}`.trim();
    }

    function renderWorkoutAnalysis(session, entry) {
      if (!entry) return '';

      // Gemiste run
      if (entry.missed || entry.completed === false) {
        return `<div style="margin-top:0.6rem;padding:0.5rem 0.7rem;background:rgba(255,107,107,0.08);border-radius:6px;font-size:0.8rem;color:#ffb0b0">
          ✕ Geen activiteit gekoppeld — workout lijkt gemist.</div>`;
      }

      const m = entry.metrics || {};
      const coach = entry.coach || {};
      const v = _VERDICT_BADGE[entry.verdict || m.overall_verdict] || _VERDICT_BADGE.on_target;

      // Overall-regels
      const overall = [];
      if (m.distance_pct != null) overall.push(`Afstand <strong>${m.distance_pct}%</strong>`);
      if (m.planned_avg_pace && m.actual_avg_pace) {
        const d = m.pace_delta_sec;
        const ds = d != null ? ` (${d >= 0 ? '+' : ''}${d}s/km)` : '';
        overall.push(`Tempo <strong>${m.actual_avg_pace}</strong> vs ${m.planned_avg_pace}${ds}`);
      }
      if (m.hr_zone_adherence_pct != null) overall.push(`HR-zone <strong>${m.hr_zone_adherence_pct}%</strong> in doel`);
      if (m.gap_pace) overall.push(`GAP <strong>${m.gap_pace}</strong>`);
      if (m.max_hr) overall.push(`max HR <strong>${m.max_hr}</strong>`);
      if (m.avg_watts) overall.push(`⚡ <strong>${m.avg_watts}W</strong>${m.weighted_watts ? ` (gew. ${m.weighted_watts}W)` : ''}`);
      if (m.decoupling_pct != null) overall.push(`drift <strong>${m.decoupling_pct}%</strong>`);
      if (m.efficiency_factor) overall.push(`EF <strong>${m.efficiency_factor}</strong>`);
      if (coach.execution_score != null) overall.push(`Score <strong>${coach.execution_score}/10</strong>`);

      // 12-min defensietest — opvallend resultaat-blok
      let testHtml = '';
      if (m.test_result) {
        const t = m.test_result;
        const badge = (ok, label) => `<span style="font-size:0.72rem;padding:0.1rem 0.45rem;border-radius:10px;color:${ok ? '#4caf50' : '#9a9a9a'};background:${ok ? 'rgba(76,175,80,0.18)' : 'rgba(150,150,150,0.12)'}">${ok ? '✓' : '✗'} ${label}</span>`;
        const statusText = t.goal_met
          ? (t.phase2_met ? '🏆 Streefdoel (fase 2) gehaald!' : `Nog ${t.phase2_goal_m - t.projected_12min_m} m tot fase 2`)
          : `Nog ${-t.delta_vs_goal_m} m tot de eis (fase 1)`;
        testHtml = `<div style="margin-top:0.5rem;padding:0.55rem 0.7rem;background:rgba(0,200,83,0.12);border:1px solid rgba(0,200,83,0.3);border-radius:8px">
          <div style="font-size:0.86rem;color:#d0f8d8">🎯 <strong>12-min testresultaat: ${t.test_distance_m} m</strong>${t.avg_pace ? ` @ ${t.avg_pace}/km` : ''}${t.avg_hr ? ` · ${t.avg_hr} bpm` : ''}</div>
          <div style="display:flex;gap:0.4rem;margin-top:0.4rem;flex-wrap:wrap">${badge(t.phase1_met, `Fase 1 · ${t.phase1_goal_m}m`)} ${badge(t.phase2_met, `Fase 2 · ${t.phase2_goal_m}m`)}</div>
          <div style="font-size:0.76rem;color:#a0c8b0;margin-top:0.35rem">${statusText}</div>
        </div>`;
      }

      // Per-interval tabel (alleen bij uitgelijnde laps)
      let tableHtml = '';
      const ivs = (m.intervals || []).filter(i => i.planned_pace || i.actual_pace);
      if (ivs.length) {
        const rows = ivs.map(i => {
          const badge = i.in_band === true ? '<span style="color:#4caf50">✓</span>'
                      : i.in_band === false ? '<span style="color:#ff6b6b">✗</span>' : '';
          const dist = i.planned_distance_m ? `${i.planned_distance_m}m` : '';
          return `<tr>
            <td style="padding:0.15rem 0.4rem;color:#6a9a7a">${i.interval}</td>
            <td style="padding:0.15rem 0.4rem">${dist}</td>
            <td style="padding:0.15rem 0.4rem">${i.planned_pace || '–'}</td>
            <td style="padding:0.15rem 0.4rem"><strong>${i.actual_pace || '–'}</strong></td>
            <td style="padding:0.15rem 0.4rem;text-align:center">${badge}</td>
          </tr>`;
        }).join('');
        const note = m.lap_alignment === 'partial'
          ? '<div style="font-size:0.68rem;color:#8a9a8a;margin-top:0.2rem">≈ benaderde uitlijning (laps ≠ stappen)</div>'
          : '';
        tableHtml = `<table style="width:100%;border-collapse:collapse;font-size:0.74rem;color:#c0e8d0;margin-top:0.4rem">
          <tr style="color:#6a9a7a;text-align:left">
            <th style="padding:0.15rem 0.4rem;font-weight:500">#</th>
            <th style="padding:0.15rem 0.4rem;font-weight:500">afst.</th>
            <th style="padding:0.15rem 0.4rem;font-weight:500">doel</th>
            <th style="padding:0.15rem 0.4rem;font-weight:500">actual</th>
            <th style="padding:0.15rem 0.4rem;font-weight:500;text-align:center">band</th>
          </tr>${rows}</table>${note}`;
      }

      const paceZonesHtml = m.pace_zone_times
        ? _renderZoneBar(m.pace_zone_times, _PACE_ZONE_LABELS, _PACE_ZONE_COLORS, 'Tempozones')
        : '';

      const obs = (coach.key_observations || []).length
        ? `<ul style="margin:0.3rem 0 0;padding-left:1.1rem;font-size:0.75rem;color:#a0c8b0">${
            coach.key_observations.map(o => `<li>${escapeHtml(o)}</li>`).join('')}</ul>`
        : '';
      const summaryHtml = coach.summary
        ? `<div class="run-analysis-summary" style="font-size:0.78rem;color:#b8e0c8;margin-top:0.4rem;line-height:1.5">${safeMarkdown(coach.summary)}</div>`
        : '';

      return `<div style="margin-top:0.6rem;padding:0.55rem 0.7rem;background:rgba(0,200,83,0.06);border:1px solid rgba(0,200,83,0.18);border-radius:8px">
        <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
          <span style="font-size:0.7rem;letter-spacing:0.04em;color:#6a9a7a;text-transform:uppercase">Analyse · gepland vs werkelijk</span>
          <span style="font-size:0.72rem;padding:0.1rem 0.45rem;border-radius:10px;color:${v.color};background:${v.bg}">${v.label}</span>
        </div>
        ${testHtml}
        ${overall.length ? `<div style="font-size:0.8rem;color:#a0e8b0;margin-top:0.4rem;line-height:1.6">${overall.join(' · ')}</div>` : ''}
        ${tableHtml}
        ${paceZonesHtml}
        ${obs}
        ${summaryHtml}
      </div>`;
    }

    function renderAdjustmentProposals(session) {
      const pending = _pendingAdjustmentsForDate(session.date);
      if (!pending.length) return '';
      return pending.map(adj => {
        const w = adj.workout || {};
        const steps = (w.steps || []).map(_stepBriefLine).filter(Boolean).join(' · ');
        const dist = w.total_distance_km ? `${w.total_distance_km} km` : '';
        return `<div id="adj-${adj.id}" style="margin-top:0.6rem;padding:0.55rem 0.7rem;background:rgba(255,179,0,0.07);border:1px solid rgba(255,179,0,0.22);border-radius:8px" onclick="event.stopPropagation()">
          <div style="font-size:0.7rem;letter-spacing:0.04em;color:#d4a017;text-transform:uppercase">💡 Coach stelt aanpassing voor</div>
          <div style="font-size:0.82rem;color:#ffd966;margin-top:0.3rem"><strong>${escapeHtml(w.name || 'Aangepaste workout')}</strong>${dist ? ' · ' + dist : ''}</div>
          ${adj.rationale ? `<div style="font-size:0.76rem;color:#c8c0a0;margin-top:0.25rem;line-height:1.5">${escapeHtml(adj.rationale)}</div>` : ''}
          ${steps ? `<div style="font-size:0.73rem;color:#a0a890;margin-top:0.3rem">${escapeHtml(steps)}</div>` : ''}
          <div style="display:flex;gap:0.5rem;margin-top:0.5rem;flex-wrap:wrap">
            <button class="run-reschedule-btn" style="color:#4caf50;border-color:rgba(76,175,80,0.3)"
              onclick="applyAdjustment('${adj.id}')">✓ Toepassen</button>
            <button class="run-reschedule-btn" style="color:#ff9800;border-color:rgba(255,152,0,0.3)"
              onclick="dismissAdjustment('${adj.id}')">✕ Negeren</button>
          </div>
          <div id="adjstatus-${adj.id}" style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem"></div>
        </div>`;
      }).join('');
    }

    async function _patchAnalysisStatus(token, adjId, status) {
      const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        headers: { Authorization: `token ${token}` }
      });
      const gist = await resp.json();
      let analysis = {};
      try { analysis = JSON.parse(gist.files['running_analysis.json']?.content || '{}'); } catch(e) {}
      const adj = (analysis.pending_adjustments || []).find(a => a.id === adjId);
      if (!adj) throw new Error('Voorstel niet gevonden');
      adj.status = status;
      adj[status === 'applied' ? 'applied_at' : 'dismissed_at'] = new Date().toISOString();
      analysis.updated_at = new Date().toISOString();
      runningAnalysisData = analysis;
      const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: { 'running_analysis.json': { content: JSON.stringify(analysis, null, 2) } } })
      });
      if (!patch.ok) throw new Error(`Opslaan mislukt ${patch.status}`);
    }

    async function applyAdjustment(adjId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      const statusEl = document.getElementById('adjstatus-' + adjId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        await _patchAnalysisStatus(token, adjId, 'applied');
        setStatus('✓ Goedgekeurd — intervals.icu bijwerken…', '#4caf50');
        const triggerTime = new Date();
        const triggerResp = await _dispatchRaw(token, 'analyze_running_workout.yml', { mode: 'apply' });
        if (triggerResp.status !== 204) {
          const body = await triggerResp.json().catch(() => ({}));
          setStatus(`Workflow fout ${triggerResp.status}: ${body.message || 'onbekend'}`, 'var(--accent2)');
          return;
        }
        setStatus('⏳ Workout pushen naar Garmin/intervals.icu…');
        const btnHost = { disabled: false, textContent: '' };
        await pollWorkflowRun(token, triggerTime, statusEl, btnHost, 'analyze_running_workout.yml', '');
      } catch(e) {
        setStatus(`❌ ${e.message}`, '#ff6b6b');
      }
    }

    async function dismissAdjustment(adjId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      const statusEl = document.getElementById('adjstatus-' + adjId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        await _patchAnalysisStatus(token, adjId, 'dismissed');
        setStatus('✓ Voorstel genegeerd', '#4caf50');
        const card = document.getElementById('adj-' + adjId);
        if (card) setTimeout(() => { card.style.display = 'none'; }, 800);
      } catch(e) {
        setStatus(`❌ ${e.message}`, '#ff6b6b');
      }
    }

    function renderRunEventCard(session, delay, idPrefix) {
      const today = new Date().toISOString().slice(0, 10);
      const isCancelled = !!session.cancelled;
      const sessionKey = session.session === 'speed' ? 'run_1' : 'run_2';
      const sessionTime = session.time || (session.session === 'speed' ? '20:00' : '09:00');
      const cardId = (idPrefix || '') + 'run' + session.date.replace(/-/g, '');

      const distStr = session.total_distance_km ? `${session.total_distance_km} km` : '';
      const metaHtml = `<div class="card-meta"><span class="card-time">${sessionTime}${distStr ? ' · ' + distStr : ''}</span></div>`;

      // Toon de uitgevoerde run zodra er intervals.icu-data is — ook al staat de workout
      // voor vandaag gepland. Een toekomstige datum (of vandaag zonder data) blijft
      // "aankomend" met reschedule/annuleer-opties.
      const actualRun = !isCancelled && session.date <= today ? _findActualRun(session.date) : null;
      const isUpcoming = session.date > today || (session.date === today && !actualRun);
      const actualHtml = actualRun ? _renderActualRunStats(actualRun) : '';
      const displayName = session.name || actualRun?.name || session.type || 'Run';

      // Geannuleerde workout: toon grijze kaart met reden en ongedaan-knop
      if (isCancelled) {
        const reason = session.cancel_reason || '';
        return `
          <div class="card cancelled" style="animation-delay:${delay}s" onclick="this.classList.toggle('open')">
            <div class="card-dot dot-cancelled"></div>
            <div class="card-info">
              <div class="card-header">
                <div class="card-header-left">
                  <div class="card-title">🏃 ${escapeHtml(displayName)}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  <div class="card-date cancelled-date">${formatDate(session.date)}</div>
                  <div class="card-relative-day">${relativeDay(session.date)}</div>
                  <div class="wod-chevron" style="color:var(--accent2)">▾</div>
                </div>
              </div>
              <div class="cancelled-undo" onclick="event.stopPropagation()">
                ${reason ? `<div style="font-size:0.75rem;color:#a0a0a0;margin-bottom:0.5rem">Reden: ${escapeHtml(reason)}</div>` : ''}
                <button class="run-reschedule-btn" style="color:#4caf50;border-color:rgba(76,175,80,0.3)"
                  onclick="undoCancelRun('${session.date}', '${cardId}')">↩ Ongedaan maken</button>
                <div id="cancel-status-${cardId}" style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem"></div>
              </div>
            </div>
          </div>`;
      }

      const descText = session.full_description || session.description || '';
      const analysisEntry = !isUpcoming && !isCancelled ? _analysisForDate(session.date) : null;
      const analysisHtml = analysisEntry ? renderWorkoutAnalysis(session, analysisEntry) : '';
      const proposalHtml = renderAdjustmentProposals(session);
      const wodContent = (descText ? `<div style="font-size:0.82rem;color:#a0e8b0;white-space:pre-wrap;line-height:1.6">${escapeHtml(descText)}</div>` : '')
                       + actualHtml + analysisHtml + proposalHtml;

      const scheduledOverride = (healthInput || {})[sessionKey];
      const overrideNote = scheduledOverride
        ? `<div style="font-size:0.7rem;color:#ffb300;margin-bottom:0.4rem">⚠ Verplaatst naar: ${scheduledOverride.replace('T', ' ')}</div>`
        : '';
      const clearBtn = scheduledOverride
        ? `<button class="run-reschedule-btn" style="color:#ff6b6b;border-color:rgba(255,107,107,0.3)" onclick="clearRunReschedule('${sessionKey}', '${cardId}')">✕ Herstel standaard</button>`
        : '';

      const rescheduleForm = isUpcoming ? `
        <div id="${cardId}" class="run-reschedule-form" onclick="event.stopPropagation()">
          ${overrideNote}
          <div style="font-size:0.75rem;color:#a0a0a0;margin-bottom:0.5rem">Nieuwe datum en tijd:</div>
          <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
            <input type="datetime-local" id="rsinput-${cardId}"
                   value="${session.date}T${sessionTime}"
                   class="add-event-input" style="flex:1;min-width:180px">
            <button class="run-reschedule-btn" id="rssave-${cardId}"
                    onclick="saveAndSyncReschedule('${sessionKey}', '${cardId}', '${session.date}')">Opslaan & Sync Garmin</button>
            ${clearBtn}
          </div>
          <div id="rsstatus-${cardId}" style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem"></div>
        </div>` : '';

      const cancelFormId = `cancelform-${cardId}`;
      const cancelForm = isUpcoming ? `
        <div id="${cancelFormId}" class="run-reschedule-form" onclick="event.stopPropagation()" style="display:none">
          <div style="font-size:0.75rem;color:#a0a0a0;margin-bottom:0.5rem">Reden voor annulering (optioneel):</div>
          <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
            <input type="text" id="cancelreason-${cardId}" placeholder="Bijv. Ziek, moe, blessure…"
                   class="add-event-input" style="flex:1;min-width:180px">
            <button class="run-reschedule-btn" style="color:#ff6b6b;border-color:rgba(255,107,107,0.3)"
                    id="cancelsave-${cardId}"
                    onclick="confirmCancelRun('${session.date}', '${cardId}')">✕ Bevestig annulering</button>
          </div>
          <div id="cancel-status-${cardId}" style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem"></div>
        </div>` : '';

      const rescheduleInWod = isUpcoming
        ? `<button class="run-reschedule-btn" onclick="clickReschedule(event, '${cardId}')">📅 Datum/tijd</button>
           <button class="run-reschedule-btn" style="color:#ff9800;border-color:rgba(255,152,0,0.3)" onclick="showCancelRunForm(event, '${cancelFormId}')">✕ Annuleer workout</button>`
        : '';
      const descHtml = (wodContent || rescheduleInWod)
        ? `<div class="card-wod">${rescheduleInWod}${rescheduleForm}${cancelForm}${wodContent}</div>`
        : '';
      const expandable = !!(wodContent || isUpcoming);
      const hasWod = expandable ? ' has-wod' : '';
      const chevron = expandable ? `<div class="wod-chevron" style="color:#00c853">▾</div>` : '';

      return `
        <div class="card${hasWod}" style="animation-delay:${delay}s"${expandable ? ' onclick="toggleWod(this, event)"' : ''}>
          <div class="card-dot" style="background:#00c853"></div>
          <div class="card-info">
            <div class="card-header">
              <div class="card-header-left">
                <div class="card-title">🏃 ${escapeHtml(displayName)}</div>
                ${metaHtml}
              </div>
              <div class="card-right">
                <div class="card-date" style="color:#00c853">${formatDate(session.date)}</div>
                <div class="card-relative-day">${relativeDay(session.date)}</div>
                ${chevron}
              </div>
            </div>
            ${descHtml}
          </div>
        </div>`;
    }

    function toggleReschedule(cardId) {
      const el = document.getElementById(cardId);
      if (!el) return;
      const showing = el.style.display === 'block';
      el.style.display = showing ? 'none' : 'block';
      if (!showing) {
        requestAnimationFrame(() => el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
      }
    }

    function clickReschedule(e, cardId) {
      e.stopPropagation();
      e.preventDefault();
      toggleReschedule(cardId);
    }

    function defaultDaysForFreq(n) {
      return ({1:[1], 2:[1,4], 3:[1,4,6]})[n] || [1,4];
    }

    async function _patchHealthInput(updates) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) throw new Error('GitHub token vereist');
      const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        headers: { Authorization: `token ${token}` }
      });
      const gist = await resp.json();
      let h = {};
      try { h = JSON.parse(gist.files['health_input.json']?.content || '{}'); } catch(e) {}
      Object.assign(h, updates);
      healthInput = h;
      await fetch(`https://api.github.com/gists/${currentGistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: { 'health_input.json': { content: JSON.stringify(h, null, 2) } } })
      });
      return token;
    }

    async function _triggerRunGeneration(statusEl) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) return;
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      setStatus('⏳ Plan hergeneren…');
      const triggerTime = new Date();
      const r = await _dispatchRaw(token, 'generate_running_workout.yml', {});
      if (r.status !== 204) {
        const b = await r.json().catch(() => ({}));
        setStatus(`Workflow fout ${r.status}: ${b.message || 'onbekend'}`, 'var(--accent2)');
        return;
      }
      await pollWorkflowRun(token, triggerTime, statusEl, null, 'generate_running_workout.yml', 'Plan bijgewerkt');
    }

    async function setSessionsPerWeek(n) {
      const statusEl = document.getElementById('run-freq-this-status');
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        const days = defaultDaysForFreq(n);
        await _patchHealthInput({ sessions_per_week: n, run_days_this_week: days, run_1: undefined, run_2: undefined, run_3: undefined });
        // Verwijder run_1/run_2/run_3 expliciet uit het opgeslagen object
        const token = document.getElementById('githubToken').value.trim();
        const resp2 = await fetch(`https://api.github.com/gists/${currentGistId}`, { headers: { Authorization: `token ${token}` } });
        const gist2 = await resp2.json();
        let h2 = {};
        try { h2 = JSON.parse(gist2.files['health_input.json']?.content || '{}'); } catch(e) {}
        delete h2.run_1; delete h2.run_2; delete h2.run_3;
        h2.sessions_per_week = n; h2.run_days_this_week = days;
        healthInput = h2;
        await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH', headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'health_input.json': { content: JSON.stringify(h2, null, 2) } } })
        });
        loadData();
        await _triggerRunGeneration(statusEl);
      } catch(e) {
        const statusEl2 = document.getElementById('run-freq-this-status');
        if (statusEl2) { statusEl2.textContent = `Fout: ${e.message}`; statusEl2.style.color = 'var(--accent2)'; }
        console.error(e);
      }
    }

    async function setSessionsNextWeek(n) {
      const statusEl = document.getElementById('run-freq-next-status');
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        await _patchHealthInput({ sessions_next_week: n, run_days_next_week: defaultDaysForFreq(n) });
        loadData();
        setStatus('✓ Opgeslagen — wordt maandag gebruikt', '#00c853');
        setTimeout(() => { const el = document.getElementById('run-freq-next-status'); if (el) el.textContent = ''; }, 4000);
      } catch(e) {
        setStatus(`Fout: ${e.message}`, 'var(--accent2)');
        console.error(e);
      }
    }

    async function setRunDaysThisWeek(days) {
      const statusEl = document.getElementById('run-freq-this-status');
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        const token = document.getElementById('githubToken').value.trim();
        if (!token || !currentGistId) throw new Error('GitHub token vereist');
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, { headers: { Authorization: `token ${token}` } });
        const gist = await resp.json();
        let h = {};
        try { h = JSON.parse(gist.files['health_input.json']?.content || '{}'); } catch(e) {}
        delete h.run_1; delete h.run_2; delete h.run_3;
        h.run_days_this_week = days;
        h.sessions_per_week = days.length;
        healthInput = h;
        await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH', headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'health_input.json': { content: JSON.stringify(h, null, 2) } } })
        });
        loadData();
        await _triggerRunGeneration(statusEl);
      } catch(e) {
        setStatus(`Fout: ${e.message}`, 'var(--accent2)');
        console.error(e);
      }
    }

    async function setRunDaysNextWeek(days) {
      const statusEl = document.getElementById('run-freq-next-status');
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        await _patchHealthInput({ run_days_next_week: days, sessions_next_week: days.length });
        loadData();
        setStatus('✓ Opgeslagen — wordt maandag gebruikt', '#00c853');
        setTimeout(() => { const el = document.getElementById('run-freq-next-status'); if (el) el.textContent = ''; }, 4000);
      } catch(e) {
        setStatus(`Fout: ${e.message}`, 'var(--accent2)');
        console.error(e);
      }
    }

    async function toggleRunDayThisWeek(wd) {
      const current = (healthInput?.run_days_this_week || defaultDaysForFreq(parseInt(healthInput?.sessions_per_week ?? 2))).slice();
      const idx = current.indexOf(wd);
      const newDays = idx >= 0 ? current.filter(d => d !== wd) : [...current, wd].sort((a,b)=>a-b);
      if (newDays.length === 0) return;
      await setRunDaysThisWeek(newDays);
    }

    async function toggleRunDayNextWeek(wd) {
      const current = (healthInput?.run_days_next_week || defaultDaysForFreq(parseInt(healthInput?.sessions_next_week ?? healthInput?.sessions_per_week ?? 2))).slice();
      const idx = current.indexOf(wd);
      const newDays = idx >= 0 ? current.filter(d => d !== wd) : [...current, wd].sort((a,b)=>a-b);
      if (newDays.length === 0) return;
      await setRunDaysNextWeek(newDays);
    }

    async function _patchRescheduleToGist(token, sessionKey, newDatetime, originalDate) {
      const newDate = newDatetime.slice(0, 10);
      const newTime = newDatetime.slice(11, 16);
      const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
        headers: { Authorization: `token ${token}` }
      });
      const gist = await resp.json();
      let h = {};
      try { h = JSON.parse(gist.files['health_input.json']?.content || '{}'); } catch(e) {}
      h[sessionKey] = newDatetime;
      if (originalDate) h[sessionKey + '_from'] = originalDate;
      healthInput = h;
      let plan = {};
      try { plan = JSON.parse(gist.files['running_plan.json']?.content || '{}'); } catch(e) {}
      if (plan.workouts) {
        const w = originalDate
          ? plan.workouts.find(w => w.date === originalDate && !w.cancelled)
          : plan.workouts.find(w => w.session === (sessionKey === 'run_1' ? 'speed' : 'long_run') && !w.cancelled);
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

    async function saveAndSyncReschedule(sessionKey, cardId, originalDate) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      const input = document.getElementById('rsinput-' + cardId);
      if (!input || !input.value) return;
      const newDatetime = input.value;
      const btn = document.getElementById('rssave-' + cardId);
      const statusEl = document.getElementById('rsstatus-' + cardId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };

      if (btn) { btn.disabled = true; btn.textContent = 'Opslaan…'; }
      try {
        await _patchRescheduleToGist(token, sessionKey, newDatetime, originalDate);
        setStatus('✓ Opgeslagen in Gist — Garmin sync starten…');

        // Trigger health data refresh in the background so the AI coach advice is regenerated
        // with the updated schedule without waiting for the next scheduled run
        _dispatchRaw(token, 'fetch_health_data.yml', {}).catch(() => {});

        // Trigger reschedule workflow
        const triggerTime = new Date();
        const triggerResp = await _dispatchRaw(token, 'reschedule_running_workout.yml', {});
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

    function showCancelRunForm(e, formId) {
      e.stopPropagation();
      e.preventDefault();
      const form = document.getElementById(formId);
      if (!form) return;
      const showing = form.style.display === 'block';
      form.style.display = showing ? 'none' : 'block';
      if (!showing) {
        requestAnimationFrame(() => form.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
      }
    }

    async function confirmCancelRun(workoutDate, cardId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      const reason = (document.getElementById('cancelreason-' + cardId)?.value || '').trim();
      const btn = document.getElementById('cancelsave-' + cardId);
      const statusEl = document.getElementById('cancel-status-' + cardId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };

      if (btn) { btn.disabled = true; btn.textContent = 'Opslaan…'; }
      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` }
        });
        const gist = await resp.json();
        let plan = {};
        try { plan = JSON.parse(gist.files['running_plan.json']?.content || '{}'); } catch(e) {}

        if (plan.workouts) {
          const w = plan.workouts.find(w => w.date === workoutDate);
          if (w) {
            w.cancelled = true;
            if (reason) w.cancel_reason = reason;
            w.cancelled_at = new Date().toISOString();
          }
        }

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'running_plan.json': { content: JSON.stringify(plan, null, 2) } } })
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt ${patch.status}`);

        setStatus('✓ Geannuleerd — agenda event verwijderen…', '#4caf50');

        // Verwijder Google Agenda en intervals.icu events via reschedule workflow (staat op main)
        _dispatchRaw(token, 'reschedule_running_workout.yml', {}).catch(() => {});

        setTimeout(() => location.reload(), 800);
      } catch(e) {
        if (btn) { btn.disabled = false; btn.textContent = '✕ Bevestig annulering'; }
        setStatus(`❌ ${e.message}`, '#ff6b6b');
      }
    }

    async function undoCancelRun(workoutDate, cardId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      const statusEl = document.getElementById('cancel-status-' + cardId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };

      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` }
        });
        const gist = await resp.json();
        let plan = {};
        try { plan = JSON.parse(gist.files['running_plan.json']?.content || '{}'); } catch(e) {}

        if (plan.workouts) {
          const w = plan.workouts.find(w => w.date === workoutDate);
          if (w) {
            delete w.cancelled;
            delete w.cancel_reason;
            delete w.cancelled_at;
          }
        }

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method: 'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { 'running_plan.json': { content: JSON.stringify(plan, null, 2) } } })
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt ${patch.status}`);

        setStatus('✓ Annulering ongedaan gemaakt', '#4caf50');
        setTimeout(() => location.reload(), 600);
      } catch(e) {
        setStatus(`❌ ${e.message}`, '#ff6b6b');
      }
    }

    async function clearRunReschedule(sessionKey, cardId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { showToast('GitHub token vereist — stel in via Acties', { type: 'error' }); return; }
      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` }
        });
        const gist = await resp.json();

        let h = {};
        try { h = JSON.parse(gist.files['health_input.json']?.content || '{}'); } catch(e) {}
        const rescheduledDate = h[sessionKey] ? h[sessionKey].slice(0, 10) : null;
        const fromDate = h[sessionKey + '_from'] || null;
        delete h[sessionKey];
        delete h[sessionKey + '_from'];
        healthInput = h;

        let plan = {};
        try { plan = JSON.parse(gist.files['running_plan.json']?.content || '{}'); } catch(e) {}
        const sessionRole = sessionKey === 'run_1' ? 'speed' : 'long_run';
        if (plan.workouts) {
          const w = (rescheduledDate && plan.workouts.find(w => w.date === rescheduledDate && !w.cancelled))
                 || (fromDate && plan.workouts.find(w => w.date === fromDate && !w.cancelled))
                 || plan.workouts.find(w => w.session === sessionRole);
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

