    // tabs.js — Render-functies per tab (Vandaag, Schema, CrossFit, Hardlopen, Acties).
    // ── Tab render functions ──────────────────────────────────

    function renderTodayTab(upcoming, past, allUpcoming) {
      const el = document.getElementById('today-content');
      if (!el) return;
      const now = new Date();
      const dayNames = ['zondag','maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag'];
      const monthNames = ['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december'];
      const dateLabel = `${dayNames[now.getDay()]} ${now.getDate()} ${monthNames[now.getMonth()]}`;

      let h = `<div class="today-header">
        <div class="today-date">${dateLabel}</div>
        <div class="today-greeting">${(() => { const h = now.getHours(); return h < 12 ? 'Goedemorgen' : h < 18 ? 'Goedemiddag' : 'Goedenavond'; })()}, Ralph</div>
        <button class="refresh-btn" onclick="hardRefresh()" title="Ververs pagina">↻</button>
      </div>`;

      // Waarschuwing als een databron achterloopt of een workflow mislukte
      h += renderFreshnessChip();
      // Eén duidelijk dagadvies (HRV, slaap, vorm, belasting, blessures)
      h += renderDayAdviceCard();
      // Weekreview (zondag gegenereerd, een week zichtbaar)
      h += renderWeeklyReviewCard();

      // Actieve blessures — zichtbaar bij de coaching die erop is aangepast
      const activeInjuries = getInjuries().filter(i => i.status !== 'hersteld');
      if (activeInjuries.length) {
        const items = activeInjuries.map(i => {
          const bits = [i.severity, i.status === 'herstellend' ? 'herstellend' : '', _isWorsened(i) ? `verergerd ${i.worsened_on}` : ''].filter(Boolean);
          const label = i.area + (bits.length ? ` (${bits.join(', ')})` : '');
          return `<li>${escapeHtml(label)}${i.description ? ` — ${escapeHtml(i.description)}` : ''}</li>`;
        }).join('');
        h += `<div class="injury-banner" onclick="switchTab('acties')">
          <div class="injury-banner-title">🩹 Actieve blessure${activeInjuries.length > 1 ? 's' : ''}</div>
          <ul class="injury-banner-list">${items}</ul>
          <div class="injury-banner-hint">De AI-coaches houden hier rekening mee · tik om te beheren</div>
        </div>`;
      }

      h += renderHomeWorkoutCard();

      // Recovery + AI coach
      const recoveryBlock = renderRecoveryTodayBlock();
      h += `<div class="recovery-card-wrapper">${recoveryBlock || ''}`;
      if (recoveryAdvice) {
        const label = recoveryAdviceFromHistory
          ? `Coach Advies (${recoveryAdviceHistory[recoveryAdviceHistory.length-1].date})`
          : 'AI Coach advies';
        const tsStr = formatAdviceTimestamp(recoveryAdviceGeneratedAt);
        const tsHtml = tsStr ? `<div class="ai-coach-timestamp">gegenereerd ${tsStr}</div>` : '';
        h += `<div class="ai-coach-block" onclick="this.classList.toggle('open')">
          <div class="ai-coach-toggle">
            <div class="ai-coach-toggle-left">
              <div class="ai-coach-label">${label}</div>
              ${tsHtml}
            </div>
            <div class="wod-chevron">▾</div>
          </div>
          <div class="ai-coach-content">
            <div class="ai-coach-body">${safeMarkdown(recoveryAdvice)}</div>
          </div>
        </div>`;
      } else {
        h += `<div class="ai-coach-empty">Nog geen AI coach-advies. Genereer het on-demand 👇</div>`;
      }
      // On-demand: regenereert herstel-advies + workout-plannen (fetch_sugarwod, AI aan)
      h += aiGenButton('🧠 Coach-advies genereren', 'fetch_sugarwod.yml', {});
      h += `</div>`;

      if (deloadAlert) h += `<div class="deload-banner">⚠️ Herstelweek aanbevolen — schaal WODs naar 60–70%.</div>`;

      // Next two activities — include today's already-done crossfit so they stay
      // visible on the Vandaag tab until midnight (for quick reference after class)
      const todayStr = now.toISOString().slice(0, 10);
      const todayDone = past
        .filter(e => e.date === todayStr)
        .map(e => ({ ...e, _src: 'crossfit' }));
      const displayItems = [...todayDone, ...allUpcoming];

      // Open Gym programma: toon als standalone blok wanneer het programma
      // bestaat voor vandaag of morgen maar het event nog niet als kaart zichtbaar is
      // (bijv. omdat autosignup nog niet heeft gedraaid en de state nog niet bijgewerkt is).
      const tomorrowStr = (() => { const d = new Date(now); d.setDate(d.getDate()+1); return d.toISOString().slice(0,10); })();
      const openGymAlreadyInCards = displayItems.slice(0, 3).some(
        e => (e.title || '').toLowerCase().includes('open gym') &&
             openGymProgram && e.date === openGymProgram.for_date
      );
      const openGymProgramForToday = openGymProgram &&
        (openGymProgram.for_date === todayStr || openGymProgram.for_date === tomorrowStr);
      if (openGymProgramForToday && !openGymAlreadyInCards) {
        const ts = openGymProgram.generated_at
          ? `<div class="ai-coach-timestamp">gegenereerd ${formatAdviceTimestamp(openGymProgram.generated_at)}</div>`
          : '';
        const eventDateLabel = openGymProgram.for_date === todayStr ? 'vandaag' : 'morgen';
        h += `<div class="recovery-card-wrapper">
          <div class="ai-coach-block">
            <div class="ai-coach-label">Open Gym Programma — ${eventDateLabel} ${openGymProgram.for_time}</div>
            ${ts}
            <div class="ai-coach-body">${safeMarkdown(openGymProgram.program_markdown)}</div>
          </div>
          ${aiGenButton('🏋️ Programma opnieuw genereren', 'generate_open_gym_program.yml', {})}
        </div>`;
      }

      h += `<div class="cards">`;
      displayItems.slice(0, 3).forEach((e, i) => {
        if (e._src === 'crossfit') {
          h += renderCard(e, 'active', i * 0.05, wodByDate[e.date] || []);
        } else if (e._src === 'run') {
          h += renderRunEventCard(e, i * 0.05, 'today');
        } else {
          h += renderPersonalEventCard(e, i * 0.05);
        }
      });
      h += `</div>`;

      // Running progress (defensie fitnesstest — twee doelen)
      const rawEst12m = runningPlanData?.estimated_12min_distance_m;
      const est12m = (rawEst12m && rawEst12m >= 1500 && rawEst12m <= 3500) ? rawEst12m : null;

      if (est12m) {
        const dStart=2100, dEis=2200, dStreef=2700;
        const pct    = Math.round((Math.min(Math.max(est12m,dStart),dStreef) - dStart) / (dStreef-dStart) * 100);
        const eisPct = Math.round((dEis-dStart)/(dStreef-dStart)*100);
        const nextRun = (runningPlanData?.workouts||[]).find(s => isUpcoming(s.date, s.time||(s.session==='speed'?'20:00':'09:00')));
        const statusLabel = est12m >= dEis
          ? (est12m >= dStreef ? `✓ Fase 1 + 2 gehaald` : `✓ Fase 1 · nog ${dStreef-est12m}m tot fase 2`)
          : `Nog ${dEis-est12m}m tot fase 1 eis`;
        h += `<div class="today-run-progress">
          <div class="run-progress-header">
            <span class="run-progress-title">Defensietest 12min</span>
            <span class="run-progress-badge">~${est12m}m</span>
          </div>
          <div class="run-progress-bar-wrapper">
            <div class="run-progress-markers">
              <span class="run-marker" style="left:0%">${dStart}m</span>
              <span class="run-marker accent" style="left:${eisPct}%;color:#ff9800">${dEis}m eis</span>
              <span class="run-marker" style="left:100%">${dStreef}m</span>
            </div>
            <div class="run-progress-track" style="position:relative">
              <div class="run-progress-fill" style="width:${pct}%"></div>
              <div style="position:absolute;top:0;bottom:0;left:${eisPct}%;width:2px;background:#ff9800;opacity:.7"></div>
            </div>
          </div>
          <div class="run-next">${statusLabel} · ${nextRun ? `Volgende: <span class="run-next-label">${formatDate(nextRun.date)} — ${escapeHtml(nextRun.name||nextRun.type||'Run')}</span>` : 'Geen run gepland'}</div>
        </div>`;
      }

      el.innerHTML = h;
    }

    function renderSchemaTab(allUpcoming, recentCancelled, pastItems, pendingSlots = [], familyOnlySlots = []) {
      const el = document.getElementById('schema-content');
      if (!el) return;
      let h = `<div class="tab-page-header">
        <div class="tab-page-title">Aankomend</div>
        <button class="add-event-btn" onclick="showAddEventForm()">+ Toevoegen</button>
      </div>
      <div id="addEventFormWrapper"></div>
      ${renderMonthQuotaSummary()}
      <div class="cards" id="upcomingCards">`;
      if (allUpcoming.length === 0) {
        h += `<div class="empty"><span class="empty-icon">📅</span>Geen aankomende events</div>`;
      } else {
        allUpcoming.forEach((e,i) => {
          if (e._src==='crossfit') h += renderCard(e,'active',i*0.05,wodByDate[e.date]);
          else if (e._src==='run') h += renderRunEventCard(e,i*0.05,'schema');
          else h += renderPersonalEventCard(e,i*0.05);
        });
      }
      h += `</div>`;
      if (recentCancelled.length > 0) {
        h += `<div class="section-title">Uitgeschreven</div><div class="cards">`;
        recentCancelled.forEach((e,i) => h += renderCard(e,'cancelled',i*0.05));
        h += `</div>`;
      }
      if (pastItems.length > 0) {
        h += `<div class="section-title">Geweest</div><div class="cards">`;
        pastItems.forEach((entry,i) => {
          if (entry.type==='class') h += renderPastCard(entry.item,i*0.05);
          else if (entry.type==='run') h += renderRunEventCard(entry.item,i*0.05,'schema');
          else if (entry.type==='personal') h += renderPersonalEventCard(entry.item,i*0.05);
          else h += renderActivityCard(entry.date,i*0.05,entry.runOnly,entry.excludeKeywords);
        });
        h += `</div>`;
      }
      if (pendingSlots.length > 0) {
        h += `<div class="section-title">Nog niet ingeschreven</div><div class="cards">`;
        const dayNlFull = ['Zondag','Maandag','Dinsdag','Woensdag','Donderdag','Vrijdag','Zaterdag'];
        pendingSlots.forEach((slot, i) => {
          const isExcl = !!exclusions[slot.key];
          const d = new Date(slot.date + 'T00:00:00');
          const dayName = dayNlFull[d.getDay()];
          const dateLabel = `${d.getDate()} ${MONTH_NL[d.getMonth()]}`;
          h += `<div class="card${isExcl ? ' cancelled' : ''}" style="animation-delay:${i*0.05}s;opacity:${isExcl?'0.55':'1'}">
            <div class="card-dot" style="background:${isExcl?'#ff6b6b':'var(--accent)'};opacity:${isExcl?'0.7':'0.35'}"></div>
            <div class="card-info">
              <div class="card-title">CrossFit WOD</div>
              <div class="card-meta"><span class="card-time">${slot.time}</span>&nbsp;·&nbsp;${isExcl ? '<span style="color:#ff6b6b">Overgeslagen</span>' : '<span style="color:var(--text-muted)">Nog niet ingeschreven</span>'}${renderMonthCountBadge(slot)}</div>
              <div style="margin-top:0.5rem">
                ${isExcl
                  ? `<button class="niet-gedaan-btn" onclick="removeExclusion('${slot.key}', this)">Toch inschrijven</button>`
                  : `<button class="niet-gedaan-btn" onclick="addExclusion('${slot.key}', this)">Overslaan</button>`
                }
              </div>
            </div>
            <div class="card-right">
              <div class="card-date${isExcl?' cancelled-date':''}">${dateLabel}</div>
              <div class="card-relative-day">${dayName}</div>
            </div>
          </div>`;
        });
        h += `</div>`;
      }
      if (familyOnlySlots.length > 0) {
        h += `<div class="section-title">Familie</div><div class="cards">`;
        const dayNlFull = ['Zondag','Maandag','Dinsdag','Woensdag','Donderdag','Vrijdag','Zaterdag'];
        familyOnlySlots.forEach((slot, i) => {
          const badges = slot.members.map(name =>
            `<span class="family-badge family-badge-${name.toLowerCase()}" title="${name}">${name[0]}</span>`
          ).join('');
          const d = new Date(slot.date + 'T00:00:00');
          const dateLabel = `${d.getDate()} ${MONTH_NL[d.getMonth()]}`;
          const dayName = dayNlFull[d.getDay()];
          h += `<div class="card family-only-card" style="animation-delay:${i*0.05}s">
            <div class="card-dot family-only-dot"></div>
            <div class="card-info">
              <div class="card-title">CrossFit WOD</div>
              <div class="card-meta"><span class="card-time">${slot.time}</span></div>
            </div>
            <div class="card-right">
              <div class="card-date">${dateLabel}</div>
              <div class="card-relative-day">${dayName}</div>
              <div class="family-badges">${badges}</div>
            </div>
          </div>`;
        });
        h += `</div>`;
      }
      el.innerHTML = h;
    }

    function renderStatsTab() {
      const el = document.getElementById('stats-content');
      if (!el) return;
      let h = `<div class="tab-page-header"><div class="tab-page-title">Kracht & PR's</div></div>`;
      h += renderHuppaOverview();
      if (Object.keys(barbellLifts).length > 0) {
        h += `<div class="section-title">Barbell Maxima</div>${renderBarbellSection()}`;
      }
      if (personalRecords.length > 0) {
        const sorted = [...personalRecords].sort((a,b) => (b.date||'').localeCompare(a.date||''));
        h += `<div class="section-title collapsible" onclick="toggleSection(this)">Persoonlijke Records</div><div class="collapsible-body"><div class="pr-list">`;
        sorted.forEach((pr,i) => {
          h += `<div class="pr-item" style="animation-delay:${i*0.03}s">
            <div class="pr-workout">${escapeHtml(pr.workout)}</div>
            ${pr.result?`<div class="pr-result">${escapeHtml(pr.result)}</div>`:''}
            ${pr.notes?`<div class="pr-notes">${escapeHtml(pr.notes)}</div>`:''}
            <div class="pr-date">${pr.date?formatPrDate(pr.date):'—'}</div>
          </div>`;
        });
        h += `</div></div>`;
      }
      if (benchmarkWorkouts.length > 0) {
        h += `<div class="section-title collapsible" onclick="toggleSection(this)">Benchmark Workouts</div><div class="collapsible-body">${renderBenchmarks(benchmarkWorkouts)}</div>`;
      }
      el.innerHTML = h;
    }

    // Huppa-lessen: abonnement, gevolgde lessen en credits per maand (uit Huppa).
    function renderHuppaOverview() {
      if (!huppaAccount) return '';
      const a = huppaAccount;
      const shortDate = iso => {
        if (!iso) return '—';
        const d = new Date(iso.slice(0, 10) + 'T12:00:00');
        return isNaN(d) ? '—' : `${d.getDate()} ${MONTH_NL[d.getMonth()]}`;
      };
      const quota = MONTHLY_CLASS_QUOTA;
      const rows = Object.entries(a.months || {})
        .sort((x, y) => y[0].localeCompare(x[0]))
        .slice(0, 6)
        .map(([m, v]) => {
          const att = v.attended || 0, late = v.late_cancellations || 0, ns = v.no_shows || 0;
          const credits = att + late + ns;
          const label = `${MONTH_NL_FULL[parseInt(m.slice(5, 7), 10) - 1]} ${m.slice(0, 4)}`;
          const cls = credits > quota ? ' over' : (credits === quota ? ' full' : '');
          return `<tr>
            <td>${label}</td><td>${att}</td><td>${late || '–'}</td><td>${ns || '–'}</td>
            <td class="huppa-credits${cls}">${credits}/${quota}</td>
          </tr>`;
        }).join('');
      return `<div class="section-title">Huppa-lessen</div>
        <div class="stats-row">
          <div class="stat-card"><div class="stat-value accent">${a.total_bookings ?? '—'}</div><div class="stat-label">Lessen totaal</div></div>
          <div class="stat-card"><div class="stat-value">${shortDate(a.last_check_in)}</div><div class="stat-label">Laatste check-in</div></div>
          <div class="stat-card"><div class="stat-value">${shortDate(a.membership?.next_payment_at)}</div><div class="stat-label">Volgende betaling</div></div>
        </div>
        ${rows ? `<table class="huppa-months">
          <thead><tr><th>Maand</th><th>Gevolgd</th><th>Late afm.</th><th>No-show</th><th>Credits</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>` : ''}
        <div class="huppa-meta">${escapeHtml(a.membership?.name || '')}${a.membership?.name ? ' · ' : ''}${escapeHtml(formatHuppaUpdated(a.updated_at))}</div>`;
    }

    function renderPlanTab() {
      const el = document.getElementById('plan-content');
      if (!el) return;
      let h = `<div class="tab-page-header"><div class="tab-page-title">Hardloopplan</div></div>`;
      // On-demand AI-acties (kostenbesparing: niets draait meer automatisch)
      h += `<div class="ai-gen-toolbar">
        ${aiGenButton('🏃 Genereer plan', 'generate_running_workout.yml', {})}
        ${aiGenButton('🔍 Review', 'review_running_workout.yml', { mode: 'auto' })}
        ${aiGenButton('📊 Analyse', 'analyze_running_workout.yml', { mode: 'analyze' })}
      </div>`;
      h += renderPerformanceCard();
      const planHtml = renderRunningPlanSection();
      h += planHtml || `<div class="empty">📋 Geen hardloopplan beschikbaar</div>`;
      el.innerHTML = h;
      initPerformanceChart();
    }

    function renderActiesTab(updatedAt) {
      const el = document.getElementById('acties-content');
      if (!el) return;
      const updLabel = updatedAt ? new Date(updatedAt).toLocaleString('nl-NL') : '—';
      const hasToken = !!localStorage.getItem('huppa_github_token');
      const hasGist = !!currentGistId;
      const isConfigured = hasToken && hasGist;
      const isPushSubscribed = !!localStorage.getItem('huppa_push_subscribed');

      let h = `<div class="tab-page-header">
        <div class="tab-page-title">Acties & Sync</div>
        <div class="acties-updated">Bijgewerkt · <span id="lastUpdated">${updLabel}</span></div>
      </div>`;

      if (!isConfigured) {
        h += `<div class="acties-config">
          ${!hasGist ? `<input type="text" id="gistId-vis" class="config-input" placeholder="Gist ID"
            onchange="document.getElementById('gistId').value=this.value;localStorage.setItem('huppa_gist_id',this.value);currentGistId=this.value.trim();loadData()">` : ''}
          <input type="password" id="githubToken-vis" class="config-input" placeholder="GitHub Token (github_pat_...)">
          <button class="workflow-btn" onclick="_saveActiesConfig()">Opslaan</button>
          ${renderTokenHelp()}
        </div>`;
      } else {
        h += `<details class="acties-token-details">
          <summary>⚙ Instellingen wijzigen</summary>
          <div class="acties-config">
            <input type="text" id="gistId-vis" class="config-input" placeholder="Gist ID" value="${escapeHtml(currentGistId)}"
              onchange="document.getElementById('gistId').value=this.value;localStorage.setItem('huppa_gist_id',this.value);currentGistId=this.value.trim()">
            <input type="password" id="githubToken-vis" class="config-input" placeholder="GitHub Token">
            <button class="workflow-btn" onclick="_saveActiesConfig()">Opslaan</button>
            ${renderTokenHelp()}
          </div>
        </details>`;
      }

      h += renderFreshnessBlock();
      h += renderLoadCard();
      h += renderInjuriesCard();
      h += renderVacationCard();

      const wfs = [
        { btnId:'signupBtn', statusId:'signupStatus', lastRunId:'signupLastRun', workflowFile:'autosignup.yml', icon:'⚡', title:'Inschrijven', desc:'Huppa auto-inschrijving & Google Calendar sync', fn:'triggerSignup()', cls:'' },
        { btnId:'syncBtn', statusId:'syncStatus', lastRunId:'syncLastRun', workflowFile:'fetch_sugarwod.yml', icon:'↻', title:'SugarWOD Sync', desc:'WOD, kracht, persoonlijke records, AI coaching', fn:'triggerSync()', cls:'info',
          extras:[{id:'skipAISync',label:'AI coaching overslaan'}] },
        { btnId:'healthBtn', statusId:'healthStatus', lastRunId:'healthLastRun', workflowFile:'fetch_health_data.yml', icon:'♥', title:'Health Refresh', desc:'Strava, Intervals.icu, Withings, omgevingsdata', fn:'triggerHealthRefresh()', cls:'purple',
          extras:[{id:'skipStravaHealth',label:'Strava overslaan'},{id:'skipIntervalsHealth',label:'Intervals.icu overslaan'},{id:'skipWithingsHealth',label:'Withings overslaan'}] },
        { btnId:'runningPlanBtn', statusId:'runningPlanStatus', lastRunId:'runningLastRun', workflowFile:'generate_running_workout.yml', icon:'🏃', title:'Hardloopplan', desc:'Nieuw hardloopschema genereren via Claude', fn:'triggerRunningPlan()', cls:'success' },
        { btnId:'repushBtn', statusId:'repushStatus', lastRunId:'repushLastRun', workflowFile:'repush_workouts.yml', icon:'↑', title:'Sync naar Garmin', desc:'Bestaande workouts opnieuw pushen naar intervals.icu / Garmin', fn:'triggerRepush()', cls:'success' },
        { btnId:'gcalSyncBtn', statusId:'gcalSyncStatus', lastRunId:'', workflowFile:'sync_to_gcal.yml', icon:'📅', title:'Sync naar Google Agenda', desc:'Hardloopworkouts en persoonlijke events toevoegen aan Google Agenda', fn:'triggerGcalSync()', cls:'info' },
        { btnId:'openGymBtn', statusId:'openGymStatus', lastRunId:'openGymLastRun', workflowFile:'generate_open_gym_program.yml', icon:'🏋️', title:'Open Gym Programma', desc:'Genereer een persoonlijk programma voor je eerstvolgende Open Gym sessie', fn:'triggerOpenGymProgram()', cls:'info' },
        { btnId:'homeWorkoutBtn', statusId:'homeWorkoutStatus', lastRunId:'homeWorkoutLastRun', workflowFile:'generate_home_workout.yml', icon:'🏠', title:'Thuistraining Plan', desc:'Genereer een gepersonaliseerd dagelijks thuistraining plan via Claude (HRV, TSB, schema)', fn:'triggerHomeWorkoutPlan()', cls:'info' },
        { btnId:'reviewRunBtn', statusId:'reviewRunStatus', lastRunId:'reviewRunLastRun', workflowFile:'review_running_workout.yml', icon:'🔍', title:'Review Hardloopplan', desc:'Beoordeel en pas hardloopworkouts aan op basis van herstel & belasting', fn:'triggerReviewRunning()', cls:'success',
          extras:[{id:'reviewModeDaily',label:'Dagelijkse review'},{id:'reviewModePrerun',label:'Pre-run briefing'}] },
        { btnId:'weeklyReviewBtn', statusId:'weeklyReviewStatus', lastRunId:'weeklyReviewLastRun', workflowFile:'weekly_review.yml', icon:'📈', title:'Weekreview', desc:'Samenvatting van de afgelopen 7 dagen + advies voor komende week (draait ook elke zondagavond)', fn:'triggerWeeklyReview()', cls:'info' },
        { btnId:'analyzeRunBtn', statusId:'analyzeRunStatus', lastRunId:'analyzeRunLastRun', workflowFile:'analyze_running_workout.yml', icon:'📊', title:'Analyseer Runs', desc:'Koppel voltooide runs aan het plan, gepland-vs-werkelijk analyse + voorstellen', fn:'triggerAnalyzeRunning()', cls:'success' },
      ];

      // Toon cleanup knop alleen als er geannuleerde workouts met events zijn
      const cancelledWithEvents = (runningPlanData?.workouts || []).filter(
        w => w.cancelled && (w.event_id || w.gcal_event_id)
      );
      if (cancelledWithEvents.length > 0) {
        wfs.push({ btnId:'cancelCleanupBtn', statusId:'cancelCleanupStatus', lastRunId:'', workflowFile:'reschedule_running_workout.yml', icon:'🗑', title:'Verwijder geannuleerde events', desc:`${cancelledWithEvents.length} geannuleerde workout${cancelledWithEvents.length > 1 ? 's' : ''} nog aanwezig in Google Agenda / intervals.icu`, fn:'triggerCancelCleanup()', cls:'danger' });
      }

      wfs.forEach(w => {
        const extras = (w.extras||[]).map(ex => `<label class="workflow-check"><input type="checkbox" id="${ex.id}"> ${ex.label}</label>`).join('');
        h += `<div class="workflow-card">
          <div class="workflow-title">${w.icon} ${w.title}</div>
          <div class="workflow-desc">${w.desc}</div>
          ${w.lastRunId ? `<div class="workflow-last-run" id="${w.lastRunId}"></div>` : ''}
          ${extras ? `<div class="workflow-extras">${extras}</div>` : ''}
          <div class="workflow-footer">
            <button id="${w.btnId}" class="workflow-btn ${w.cls}" onclick="${w.fn}">${w.icon} ${w.title}</button>
            <span id="${w.statusId}" class="workflow-status"></span>
          </div>
        </div>`;
      });

      if (!isPushSubscribed && isConfigured) {
        h += `<div class="workflow-card">
          <div class="workflow-title">🔔 Notificaties</div>
          <div class="workflow-desc">Ontvang push notificaties rechtstreeks op je telefoon (vervangt Pushover)</div>
          <div class="workflow-footer">
            <button class="workflow-btn info" onclick="subscribeToPush()">🔔 Notificaties inschakelen</button>
          </div>
        </div>`;
      } else if (isPushSubscribed) {
        h += `<div class="workflow-card">
          <div class="workflow-title">🔔 Notificaties</div>
          <div class="workflow-desc" style="color:var(--accent)">✅ Notificaties ingeschakeld op dit apparaat</div>
          <div class="workflow-footer">
            <button class="workflow-btn" onclick="subscribeToPush()" style="opacity:.6;font-size:.8rem">Opnieuw inschrijven</button>
          </div>
        </div>`;
      }

      h += `<div id="barbellStatus" class="barbell-status"></div>`;
      h += renderDataSourcesBlock();
      el.innerHTML = h;

      const savedTok = localStorage.getItem('huppa_github_token');
      const tokVis = document.getElementById('githubToken-vis');
      if (savedTok && tokVis) tokVis.value = savedTok;

      if (savedTok) loadWorkflowLastRuns(savedTok);
    }

    function _saveActiesConfig() {
      const gistVis = document.getElementById('gistId-vis');
      const tokVis = document.getElementById('githubToken-vis');
      if (gistVis && gistVis.value.trim()) {
        const g = gistVis.value.trim();
        document.getElementById('gistId').value = g;
        localStorage.setItem('huppa_gist_id', g);
        currentGistId = g;
      }
      if (tokVis && tokVis.value.trim()) {
        const t = tokVis.value.trim();
        document.getElementById('githubToken').value = t;
        localStorage.setItem('huppa_github_token', t);
      }
      loadData();
    }

