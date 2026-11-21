    // data.js — loadData: Gist ophalen en alle tabs renderen.
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

    // Of er al iets (vers of uit de lokale cache) op het scherm staat.
    let _lastGist = null;   // laatst gerenderde Gist (voor afgeleide features)
    let _dataRendered = false;
    let _loadDataBusy = null;

    // Laadt de Gist. Eerst (bij opstarten) direct de lokaal bewaarde versie
    // tonen, daarna op de achtergrond verversen. Lukt het ophalen niet (offline,
    // slecht bereik), dan blijft de laatst bekende data staan met een banner.
    async function loadData() {
      if (_loadDataBusy) return _loadDataBusy;
      _loadDataBusy = _loadDataInner().finally(() => { _loadDataBusy = null; });
      return _loadDataBusy;
    }

    async function _loadDataInner() {
      const gistId = document.getElementById('gistId').value.trim();
      if (!gistId) return;

      localStorage.setItem('huppa_gist_id', gistId);
      currentGistId = gistId;

      if (!_dataRendered) {
        const cached = await gistCacheGet(gistId);
        if (cached) {
          try { renderFromGist(cached); _dataRendered = true; }
          catch (e) { console.warn('Gecachte data kon niet gerenderd worden:', e); }
        }
        if (!_dataRendered) {
          const todayEl = document.getElementById('today-content');
          if (todayEl) todayEl.innerHTML = buildSkeleton();
        }
      }

      const token = document.getElementById('githubToken').value.trim();
      const authHeaders = token ? { Authorization: `token ${token}` } : {};

      let gist;
      try {
        // Single fetch — parse all files from one response
        const resp = await fetch(`https://api.github.com/gists/${gistId}`, { headers: authHeaders, cache: 'no-store' });
        if (!resp.ok) throw new Error(`GitHub API fout: ${resp.status}`);
        gist = await resp.json();
        await hydrateTruncatedFiles(gist, authHeaders);
      } catch (e) {
        if (_dataRendered) {
          const cached = await gistCacheGet(gistId);
          setOfflineBanner(cached?.updated_at || new Date().toISOString());
          return;
        }
        const el = document.getElementById('today-content');
        if (el) el.innerHTML = `<div class="error-msg">❌ ${escapeHtml(e.message)}</div>`;
        return;
      }

      try {
        renderFromGist(gist);
        _dataRendered = true;
        setOfflineBanner(null);
        gistCacheSet(gistId, gist);
      } catch (e) {
        const el = document.getElementById('today-content');
        if (el) el.innerHTML = `<div class="error-msg">❌ ${escapeHtml(e.message)}</div>`;
      }
    }

    // Parse + render alle tabs uit één Gist-object (vers of uit de cache).
    function renderFromGist(gist) {
        _lastGist = gist;
        // Parse all file types from this single response
        parseGistFiles(gist);

        const stateFile = gist.files['sportbit_state.json'];
        if (!stateFile) throw new Error('sportbit_state.json niet gevonden in Gist');

        const state = JSON.parse(stateFile.content);

        // Bouw lookup van Open Gym programma's op basis van event_id (opgeslagen door generate_open_gym_program.py)
        openGymProgramsByEventId = {};
        for (const [id, info] of Object.entries(state.signed_up || {})) {
          if (info.program_markdown) {
            openGymProgramsByEventId[id] = {
              program_markdown: info.program_markdown,
              focus_summary: info.focus_summary || '',
              generated_at: info.program_generated_at || '',
            };
          }
        }

        // Include event_id in each item so the "Niet gedaan" button can patch the state
        const signedUp = Object.entries(state.signed_up || {}).map(([id, info]) => ({...info, event_id: id}));
        const cancelled = Object.entries(state.cancelled || {}).map(([id, info]) => ({...info, event_id: id}));

        signedUp.sort((a, b) => a.date.localeCompare(b.date));
        cancelled.sort((a, b) => a.date.localeCompare(b.date));

        const upcoming = signedUp.filter(e => isUpcoming(e.date, e.time));
        const past = signedUp.filter(e => !isUpcoming(e.date, e.time));


        const lastUpdatedEl = document.getElementById('lastUpdated');
        if (lastUpdatedEl) lastUpdatedEl.textContent = new Date(gist.updated_at).toLocaleString('nl-NL');

        // Build shared data structures
        _upcomingCrossfit = upcoming;
        _pastCrossfit     = past;
        const cutoffRun = (() => { const d = new Date(); d.setDate(d.getDate() + 14); return d.toISOString().slice(0, 10); })();
        const upcomingPersonal = personalEvents.filter(e => isUpcoming(e.date, e.time || null));
        const upcomingRuns = runningPlanData
          ? (runningPlanData.workouts || [])
              .filter(s => { const t = s.time || (s.session === 'speed' ? '20:00' : '09:00'); return isUpcoming(s.date, t) && s.date <= cutoffRun; })
              .map(s => ({ ...s, _src: 'run' }))
          : [];
        const allUpcoming = [
          ...upcoming.map(e => ({ ...e, _src: 'crossfit' })),
          ...upcomingPersonal.map(e => ({ ...e, _src: 'personal' })),
          ...upcomingRuns,
        ].sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));

        const todayStr = new Date().toISOString().slice(0, 10);
        const maxDateStr = (() => { const d = new Date(); d.setDate(d.getDate() + 8); return d.toISOString().slice(0, 10); })();
        const recentCancelled = cancelled.filter(e => e.date >= todayStr && e.date <= maxDateStr);

        const classDates = new Set(signedUp.map(e => e.date));
        const cutoff21 = new Date(); cutoff21.setDate(cutoff21.getDate() - 21);
        const cutoffStr = cutoff21.toISOString().slice(0, 10);
        const activityDates = new Set([
          ...Object.keys((intervalsData?.activities || {}).by_date || {}),
          ...Object.keys((stravaData?.activities_by_date) || {}),
        ]);
        const planDates = new Set((runningPlanData?.workouts || []).map(s => s.date));
        const _runTypes2 = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
        const runActivityDates2 = new Set();
        Object.keys((intervalsData?.activities || {}).by_date || {}).forEach(d2 => {
          const a2 = ((intervalsData.activities || {}).by_date || {})[d2] || [];
          if (a2.some(a => _runTypes2.some(rt => (a.type || '').toLowerCase().includes(rt)))) runActivityDates2.add(d2);
        });
        Object.keys(stravaData?.activities_by_date || {}).forEach(d2 => {
          if (runActivityDates2.has(d2)) return;
          const a2 = (stravaData.activities_by_date || {})[d2] || [];
          if (a2.some(a => _runTypes2.some(rt => (a.type || '').toLowerCase().includes(rt)))) runActivityDates2.add(d2);
        });
        // Per datum de keywords van handmatige personal events (zelfde datumbereik als
        // waarmee ze in pastItems komen). Een activiteit die hierdoor al onder een
        // personal-event-kaart gekoppeld wordt, mag niet ook als losse orphan-kaart
        // verschijnen — dat zou een dubbele kaart voor dezelfde activiteit geven.
        const personalClaimedKeywordsByDate = {};
        personalEvents.forEach(e => {
          if (e.date < cutoffStr || isUpcoming(e.date, e.time || null)) return;
          const kw = personalTypeKeywords[e.title];
          if (!kw) return;
          (personalClaimedKeywordsByDate[e.date] ||= new Set());
          kw.forEach(k => personalClaimedKeywordsByDate[e.date].add(k));
        });
        // Blijft er na het wegfilteren van geclaimde types nog een activiteit over?
        const _hasUnclaimedActivity = (d, runOnly, excl) => {
          if (!excl || !excl.length) return true;
          const types = [
            ...(((intervalsData?.activities || {}).by_date || {})[d] || []),
            ...((stravaData?.activities_by_date || {})[d] || []),
          ].map(a => (a.type || '').toLowerCase())
           .filter(t => !runOnly || _runTypes2.some(rt => t.includes(rt)));
          return types.some(t => !excl.some(k => t.includes(k)));
        };
        // Orphan activities: no class + no plan → show all; run on class day → show run-only
        const orphanEntries = [];
        Array.from(activityDates).forEach(d => {
          if (planDates.has(d) || d < cutoffStr || d > todayStr) return;
          const excl = personalClaimedKeywordsByDate[d] ? Array.from(personalClaimedKeywordsByDate[d]) : null;
          const runOnly = classDates.has(d);
          if (runOnly && !runActivityDates2.has(d)) return;
          if (!_hasUnclaimedActivity(d, runOnly, excl)) return;
          orphanEntries.push({ date: d, runOnly, excludeKeywords: excl });
        });
        const pastRuns = runningPlanData
          ? (runningPlanData.workouts || []).filter(s => { const t = s.time || (s.session === 'speed' ? '20:00' : '09:00'); return s.date >= cutoffStr && !isUpcoming(s.date, t); })
          : [];
        const pastItems = [
          ...past.slice(-5).map(e => ({ type: 'class', date: e.date, item: e })),
          ...orphanEntries.map(({ date: d, runOnly, excludeKeywords }) => ({ type: 'activity', date: d, runOnly, excludeKeywords })),
          ...pastRuns.map(s => ({ type: 'run', date: s.date, item: s })),
          ...personalEvents.filter(e => !isUpcoming(e.date, e.time || null) && e.date >= cutoffStr).map(e => ({ type: 'personal', date: e.date, item: e })),
        ].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 8);

        // Bereken geplande slots die nog niet ingeschreven zijn. De kaarten tonen
        // 21 dagen vooruit; voor de maandtelling kijken we door tot het einde van
        // de huidige maand, zodat de prognose de hele maand dekt.
        const signedUpKeys = new Set(signedUp.map(e => `${e.date}_${e.time}`));
        const _now = new Date();
        const _daysLeftInMonth = new Date(_now.getFullYear(), _now.getMonth() + 1, 0).getDate() - _now.getDate();
        const _horizon = Math.max(21, _daysLeftInMonth);
        const allPendingSlots = [];
        for (let i = 1; i <= _horizon; i++) {
          const d = new Date(); d.setDate(d.getDate() + i);
          const dateStr = d.toISOString().slice(0, 10);
          for (const [jsDay, time] of CROSSFIT_SCHEDULE) {
            if (d.getDay() === jsDay && !signedUpKeys.has(`${dateStr}_${time}`) && !isOnVacation(dateStr)) {
              allPendingSlots.push({ date: dateStr, time, key: `${dateStr}_${time}`, withinWindow: i <= 21 });
            }
          }
        }
        allPendingSlots.sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
        const pendingSlots = allPendingSlots.filter(sl => sl.withinWindow);

        // Bereken slots waar alleen familie ingeschreven is (niet Ralph zelf)
        const familyOnlySlots = Object.entries(familyBookings)
          .filter(([key]) => key.slice(0, 10) >= todayStr && !signedUpKeys.has(key))
          .map(([key, members]) => ({ date: key.slice(0, 10), time: key.slice(11), members }))
          .sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));

        // Volgnummer per kalendermaand voor het abonnement (13x per maand),
        // inclusief de geplande slots waar nog niet op ingeschreven is
        buildMonthlyClassIndex(signedUp, allPendingSlots);

        // Render each tab
        renderTodayTab(upcoming, past, allUpcoming);
        renderSchemaTab(allUpcoming, recentCancelled, pastItems, pendingSlots, familyOnlySlots);
        renderStatsTab();
        renderPlanTab();
        renderActiesTab(gist.updated_at);
    }

