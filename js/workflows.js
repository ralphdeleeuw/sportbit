    // workflows.js — GitHub Actions starten en volgen vanuit de app.
    const GH_REPO = 'ralphdeleeuw/sportbit';

    function _ghToken() {
      return (document.getElementById('githubToken')?.value || '').trim()
          || (localStorage.getItem('huppa_github_token') || '').trim();
    }

    function _setStatus(el, msg, color) {
      if (!el) return;
      el.textContent = msg;
      el.style.color = color || 'var(--muted)';
    }

    function _isChecked(id) { return !!document.getElementById(id)?.checked; }

    // Start een workflow via workflow_dispatch; geeft de ruwe fetch-Response.
    function _dispatchRaw(token, workflowFile, inputs) {
      return fetch(
        `https://api.github.com/repos/${GH_REPO}/actions/workflows/${workflowFile}/dispatches`,
        {
          method: 'POST',
          headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
          body: JSON.stringify({ ref: 'main', inputs: inputs || {} }),
        }
      );
    }

    // Start een workflow via workflow_dispatch. Geeft {ok, status, message}.
    async function _dispatch(token, workflowFile, inputs) {
      const resp = await _dispatchRaw(token, workflowFile, inputs);
      if (resp.status === 204) return { ok: true, status: 204 };
      const body = await resp.json().catch(() => ({}));
      return { ok: false, status: resp.status, message: body.message || 'onbekend' };
    }

    // Generieke knop-handler: start de workflow, toont status bij de knop én in
    // de sync-balk, en laadt de data opnieuw zodra de run klaar is.
    async function runWorkflow({ workflowFile, label, inputs = {}, btn = null, statusEl = null, startMsg = 'Workflow starten…' }) {
      const token = _ghToken();
      if (!token) {
        _setStatus(statusEl, 'GitHub token vereist — stel in via Acties', 'var(--accent2)');
        if (!statusEl) showToast('Vul eerst je GitHub token in via Acties', { type: 'error' });
        return;
      }
      if (btn) { btn.disabled = true; btn.textContent = '⏳ Bezig…'; }
      _setStatus(statusEl, startMsg);
      syncBarUpdate(workflowFile, label, 'starten…');
      const triggerTime = new Date();
      try {
        const r = await _dispatch(token, workflowFile, inputs);
        if (!r.ok) {
          _setStatus(statusEl, `Fout ${r.status}: ${r.message}`, 'var(--accent2)');
          syncBarUpdate(workflowFile, label, `fout ${r.status}`, 'fail');
          if (btn) { btn.disabled = false; btn.textContent = label; }
          return;
        }
        _setStatus(statusEl, '⏳ In wachtrij…');
        await pollWorkflowRun(token, triggerTime, statusEl, btn, workflowFile, label);
      } catch (e) {
        _setStatus(statusEl, `Netwerkfout: ${e.message}`, 'var(--accent2)');
        syncBarUpdate(workflowFile, label, 'netwerkfout', 'fail');
        if (btn) { btn.disabled = false; btn.textContent = label; }
      }
    }

    // Knoppen in de Acties-tab: id's volgen het patroon <naam>Btn / <naam>Status.
    function _wfButton(prefix, workflowFile, label, inputs, startMsg) {
      return runWorkflow({
        workflowFile, label, inputs, startMsg,
        btn: document.getElementById(`${prefix}Btn`),
        statusEl: document.getElementById(`${prefix}Status`),
      });
    }

    function triggerSync() {
      return _wfButton('sync', 'fetch_sugarwod.yml', '↻ SugarWOD Sync',
        _isChecked('skipAISync') ? { skip_ai: true } : {});
    }

    function triggerHealthRefresh() {
      const inputs = {};
      if (_isChecked('skipStravaHealth')) inputs.skip_strava = true;
      if (_isChecked('skipIntervalsHealth')) inputs.skip_intervals = true;
      if (_isChecked('skipWithingsHealth')) inputs.skip_withings = true;
      return _wfButton('health', 'fetch_health_data.yml', '♥ Health Refresh', inputs, 'Health workflow starten…');
    }

    function triggerRunningPlan()    { return _wfButton('runningPlan', 'generate_running_workout.yml', '🏃 Hardloopplan', {}, 'Hardloopplan workflow starten…'); }
    function triggerRepush()         { return _wfButton('repush', 'repush_workouts.yml', '↑ Sync naar Garmin', {}, 'Repush workflow starten…'); }
    function triggerAnalyzeRunning() { return _wfButton('analyzeRun', 'analyze_running_workout.yml', '📊 Analyseer Runs', { mode: 'analyze' }, 'Analyse workflow starten…'); }
    function triggerCancelCleanup()  { return _wfButton('cancelCleanup', 'reschedule_running_workout.yml', '🗑 Verwijder geannuleerde events', {}, 'Events verwijderen…'); }
    function triggerGcalSync()       { return _wfButton('gcalSync', 'sync_to_gcal.yml', '📅 Sync naar Google Agenda', {}, 'Sync starten…'); }
    function triggerOpenGymProgram() { return _wfButton('openGym', 'generate_open_gym_program.yml', '🏋️ Open Gym Programma', {}, 'Programma genereren…'); }
    function triggerSignup()         { return _wfButton('signup', 'autosignup.yml', '⚡ Inschrijven', {}, 'Inschrijf-workflow starten…'); }
    function triggerWeeklyReview()   { return _wfButton('weeklyReview', 'weekly_review.yml', '📈 Weekreview', {}, 'Weekreview genereren…'); }

    function triggerReviewRunning() {
      const mode = _isChecked('reviewModePrerun') ? 'prerun' : _isChecked('reviewModeDaily') ? 'daily' : 'auto';
      return _wfButton('reviewRun', 'review_running_workout.yml', '🔍 Review', { mode }, 'Review workflow starten…');
    }

    function triggerHomeWorkoutPlan(ev) {
      if (ev) ev.stopPropagation();
      return _wfButton('homeWorkout', 'generate_home_workout.yml', '🏠 Thuistraining Plan', {}, 'Plan genereren…');
    }

    async function pollWorkflowRun(token, triggerTime, statusEl, btn, workflowFile = 'fetch_sugarwod.yml', btnLabel = '↻ Sync') {
      const headers = {
        Authorization: `token ${token}`,
        Accept: 'application/vnd.github+json',
      };
      const runsUrl = `https://api.github.com/repos/${GH_REPO}/actions/workflows/${workflowFile}/runs?event=workflow_dispatch&per_page=5`;
      const maxWaitMs = 10 * 60 * 1000; // 10 min timeout
      const pollInterval = 15000; // 15 sec
      const started = Date.now();
      const resetBtn = () => { if (btn) { btn.disabled = false; btn.textContent = btnLabel; } };
      const barLabel = btnLabel || workflowFile.replace('.yml', '').replace(/_/g, ' ');
      syncBarUpdate(workflowFile, barLabel, 'in wachtrij…');

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
                  _setStatus(statusEl, `✅ Klaar (${elapsed}s) — data opnieuw laden…`, '#4caf50');
                  syncBarUpdate(workflowFile, barLabel, 'data laden…');
                  resetBtn();
                  await new Promise(r => setTimeout(r, 1500));
                  await loadData();
                  let doneMsg = `✅ Data bijgewerkt (${elapsed}s)`;
                  if (workflowFile === 'review_running_workout.yml' && runningPlanData?.last_review_duration_s) {
                    doneMsg += ` — AI: ${runningPlanData.last_review_duration_s}s`;
                  }
                  // statusEl kan door de re-render vervangen zijn; zoek hem opnieuw op id.
                  _setStatus((statusEl && statusEl.id && document.getElementById(statusEl.id)) || statusEl, doneMsg, '#4caf50');
                  syncBarUpdate(workflowFile, barLabel, `klaar (${elapsed}s)`, 'ok');
                } else {
                  _setStatus(statusEl, `❌ Workflow mislukt: ${run.conclusion}`, 'var(--accent2)');
                  syncBarUpdate(workflowFile, barLabel, `mislukt (${run.conclusion})`, 'fail');
                  resetBtn();
                }
                return;
              } else if (run.status === 'in_progress') {
                _setStatus(statusEl, `⚙️ Bezig… (${elapsed}s)`);
                syncBarUpdate(workflowFile, barLabel, `bezig ${elapsed}s`);
              } else {
                _setStatus(statusEl, `⏳ In wachtrij… (${elapsed}s)`);
                syncBarUpdate(workflowFile, barLabel, `in wachtrij ${elapsed}s`);
              }
            }
          }
        } catch (_) { /* network blip, keep polling */ }

        await new Promise(r => setTimeout(r, pollInterval));
      }

      // Timeout
      _setStatus(statusEl, 'Timeout: workflow duurde te lang. Laad handmatig opnieuw.', 'var(--accent2)');
      syncBarUpdate(workflowFile, barLabel, 'timeout', 'fail');
      resetBtn();
    }

    // ── On-demand AI-generatie (kostenbesparing) ─────────────────────────────
    // AI-coaches draaien niet meer automatisch. Deze helpers plaatsen een knop
    // náást elk AI-blok (Vandaag/Schema/Hardlopen) die de bijbehorende workflow
    // on-demand start. De knop en zijn status-span (.ai-gen-status, gedeelde
    // .ai-gen-row parent) worden uit de klik afgeleid, zodat dezelfde functie
    // overal werkt zonder vaste element-IDs.
    function aiGenButton(label, workflowFile, inputs) {
      const inp = encodeURIComponent(JSON.stringify(inputs || {}));
      return `<div class="ai-gen-row">
        <button class="ai-gen-btn" data-wf="${workflowFile}" data-inputs="${inp}" data-label="${escapeHtml(label)}" onclick="triggerAiGenerate(event)">${label}</button>
        <span class="ai-gen-status"></span>
      </div>`;
    }

    async function triggerAiGenerate(ev) {
      if (ev) ev.stopPropagation();
      const btn = ev ? (ev.currentTarget || ev.target) : null;
      if (!btn) return;
      const row = btn.closest('.ai-gen-row');
      const statusEl = row ? row.querySelector('.ai-gen-status') : null;
      let inputs = {};
      try { inputs = JSON.parse(decodeURIComponent(btn.dataset.inputs || '%7B%7D')); } catch (_) {}
      return runWorkflow({ workflowFile: btn.dataset.wf, label: btn.dataset.label || btn.textContent, inputs, btn, statusEl });
    }

    async function loadWorkflowLastRuns(token) {
      if (!token) return;
      const headers = { Authorization: `token ${token}`, Accept: 'application/vnd.github+json' };
      const runs = [
        { id: 'signupLastRun',  file: 'autosignup.yml' },
        { id: 'syncLastRun',    file: 'fetch_sugarwod.yml' },
        { id: 'healthLastRun',  file: 'fetch_health_data.yml' },
        { id: 'runningLastRun',    file: 'generate_running_workout.yml' },
        { id: 'repushLastRun',     file: 'repush_workouts.yml' },
        { id: 'openGymLastRun',      file: 'generate_open_gym_program.yml' },
        { id: 'homeWorkoutLastRun',  file: 'generate_home_workout.yml' },
        { id: 'reviewRunLastRun',    file: 'review_running_workout.yml' },
        { id: 'weeklyReviewLastRun', file: 'weekly_review.yml' },
        { id: 'analyzeRunLastRun',   file: 'analyze_running_workout.yml' },
      ];
      await Promise.all(runs.map(async ({ id, file }) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = '…';
        try {
          const r = await fetch(
            `https://api.github.com/repos/${GH_REPO}/actions/workflows/${file}/runs?per_page=1`,
            { headers }
          );
          if (!r.ok) { el.textContent = ''; return; }
          const data = await r.json();
          const run = data.workflow_runs?.[0];
          if (!run) { el.textContent = '—'; return; }
          const icon = run.status !== 'completed' ? '⏳'
            : run.conclusion === 'success' ? '✅'
            : run.conclusion === 'failure' ? '❌' : '⚠️';
          el.textContent = `Laatste run: ${icon} ${relTime(run.updated_at || run.created_at)}`;
        } catch { el.textContent = ''; }
      }));
    }

