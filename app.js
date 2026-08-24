    const DAY_NL = ['Zo', 'Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za'];
    const MONTH_NL = ['jan', 'feb', 'mrt', 'apr', 'mei', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
    // Vaste CrossFit rooster — spiegelt SCHEDULE in autosignup.py (JS getDay: 0=Zo, 6=Za)
    const CROSSFIT_SCHEDULE = [[1,"20:00"],[3,"08:00"],[4,"20:00"],[0,"09:00"]];
    // Sportvrienden — alleen deze deelnemers tonen bij een les. Huppa levert
    // namen als "Erik H"; matchen gebeurt op voornaam + eerste letter achternaam,
    // zodat ook "Erik Huisman" matcht.
    const SPORT_FRIENDS = ['Erik H', 'Linda W', 'Laura D', 'Eva D', 'Robbert S', 'Stefan C'];
    const _FRIEND_KEYS = SPORT_FRIENDS.map(n => n.toLowerCase().replace(/\./g, '').replace(/\s+/g, ' ').trim());
    function isSportFriend(name) {
      const key = (name || '').toLowerCase().replace(/\./g, '').replace(/\s+/g, ' ').trim();
      return _FRIEND_KEYS.some(f => key === f || key.startsWith(f));
    }

    // Blessures — zie het blessure-blok verderop; hier gedeclareerd omdat de eerste
    // render (renderTodayTab / renderActiesTab) al draait voordat dat blok is bereikt.
    const INJURY_SEVERITIES = ['licht', 'matig', 'ernstig'];
    const INJURY_STATUSES = ['actief', 'herstellend', 'hersteld'];
    // Vervang dit door je eigen VAPID public key (gegenereerd met: vapid --gen && vapid --applicationServerKey)
    const VAPID_PUBLIC_KEY = 'BEHjNc5ry_se3HeXSfl2QIWOtkZIT69L5rVDNHxqNzZrL0hZ0az8InWjZw8g2IZhLT9_B28XaSWdrL64TcQKnHM';
    let currentGistId = '';

    // ── Tab system ────────────────────────────────────────────
    let _activeTab = localStorage.getItem('sb_tab') || 'today';

    function switchTab(tabId) {
      _activeTab = tabId;
      localStorage.setItem('sb_tab', tabId);
      document.querySelectorAll('.tab-screen').forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
      const screen = document.getElementById('tab-' + tabId);
      if (screen) { screen.classList.add('active'); screen.scrollTop = 0; }
    }

    // Activate saved tab on load (before data loads)
    switchTab(_activeTab);

    // ── Migrate legacy localStorage keys (SportBit → Huppa) ──
    ['gist_id', 'github_token', 'push_subscribed'].forEach(k => {
      const old = localStorage.getItem(`sportbit_${k}`);
      if (old && !localStorage.getItem(`huppa_${k}`)) {
        localStorage.setItem(`huppa_${k}`, old);
        localStorage.removeItem(`sportbit_${k}`);
      }
    });

    // ── Load saved Gist ID ────────────────────────────────────
    const savedGistId = localStorage.getItem('huppa_gist_id');
    if (savedGistId) {
      document.getElementById('gistId').value = savedGistId;
      loadData();
    } else {
      const todayEl = document.getElementById('today-content');
      if (todayEl) todayEl.innerHTML = `<div class="empty-state"><p>Ga naar <strong>Acties</strong> om je Gist ID en GitHub token in te stellen.</p></div>`;
    }

    function relTime(iso) {
      if (!iso) return '';
      const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
      if (mins < 2) return 'zojuist';
      if (mins < 60) return `${mins} min geleden`;
      const hrs = Math.round(mins / 60);
      if (hrs < 24) return `${hrs} uur geleden`;
      const days = Math.round(hrs / 24);
      return days === 1 ? 'gisteren' : `${days} dagen geleden`;
    }

    async function hardRefresh() {
      const btn = document.querySelector('.refresh-btn');
      if (btn) { btn.style.opacity = '0.4'; btn.style.pointerEvents = 'none'; }
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map(k => caches.delete(k)));
      }
      location.reload(true);
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
      if (!cap) return '';
      // Legacy format (SportBit): {current, max} — still supported for old data
      if (cap.max != null) {
        const pct = cap.current / cap.max;
        let cls = 'open';
        if (pct >= 1) cls = 'full';
        else if (pct >= 0.8) cls = 'near-full';
        return `<span class="capacity-badge ${cls}">${cap.current}/${cap.max}</span>`;
      }
      // Huppa format: {available, is_full}
      if (cap.is_full) return `<span class="capacity-badge full">vol</span>`;
      if (cap.available == null) return '';
      const cls = cap.available <= 3 ? 'near-full' : 'open';
      return `<span class="capacity-badge ${cls}">${cap.available} vrij</span>`;
    }

    // Deelnemers van een les: alleen de voornamen van sportvrienden, geen
    // avatars (Huppa levert namen als "Erik H." plus een optionele foto-URL).
    function renderParticipants(date, time) {
      const cap = classCapacity[`${date}_${time}`];
      const people = ((cap && cap.participants) || []).filter(p => isSportFriend(p.name));
      if (!people.length) return '';
      const names = people.map(p => escapeHtml((p.name || '').split(' ')[0])).join(', ');
      return `<div class="class-participants">
        <span class="participant-names">${names}</span>
      </div>`;
    }

    function renderFamilyBadges(date, time) {
      const members = familyBookings[`${date}_${time}`];
      if (!members || members.length === 0) return '';
      const badges = members.map(name =>
        `<span class="family-badge family-badge-${name.toLowerCase()}" title="${name}">${name[0]}</span>`
      ).join('');
      return `<div class="family-badges">${badges}</div>`;
    }

    function renderCard(item, type, delay, wods) {
      const cancelled = type === 'cancelled';
      const _cap = classCapacity[`${item.date}_${item.time}`];
      const _coach = _cap && _cap.trainers && _cap.trainers[0] ? _cap.trainers[0].split(' ')[0] : '';
      const metaHtml = `<div class="card-meta">
        <span class="card-time">${item.time}</span>
        ${_coach ? `<span class="card-coach">· ${escapeHtml(_coach)}</span>` : ''}
      </div>` + (cancelled ? '' : renderParticipants(item.date, item.time));

      // Open Gym: toon gegenereerd programma als beschikbaar
      // Zoek eerst op event_id (permanent opgeslagen in state), dan op datum als fallback
      const isOpenGym = !cancelled && (item.title || '').toLowerCase().includes('open gym');
      const _prog = isOpenGym
        ? (openGymProgramsByEventId[item.event_id]
           || (openGymProgram && openGymProgram.for_date === item.date ? openGymProgram : null))
        : null;
      const openGymProgramHtml = (() => {
        if (!_prog) return null;
        const ts = _prog.generated_at
          ? `<div class="ai-coach-timestamp">gegenereerd ${formatAdviceTimestamp(_prog.generated_at)}</div>`
          : '';
        return `<div class="card-wod">
          <div class="ai-coach-block" style="margin:0">
            <div class="ai-coach-label">Open Gym Programma</div>
            ${ts}
            <div class="ai-coach-body">${safeMarkdown(_prog.program_markdown)}</div>
          </div>
          ${aiGenButton('🏋️ Programma opnieuw genereren', 'generate_open_gym_program.yml', {})}
        </div>`;
      })();

      if (openGymProgramHtml) {
        const focusBadge = _prog.focus_summary
          ? `<div class="card-wod-preview" style="padding:0.25rem 0.8rem 0.1rem;font-size:0.72rem;color:var(--accent);opacity:0.85">${escapeHtml(_prog.focus_summary)}</div>`
          : '';
        return `
          <div class="card has-wod" style="animation-delay:${delay}s" onclick="toggleWod(this, event)">
            <div class="card-dot dot-active" style="background:#9b59b6"></div>
            <div class="card-info">
              <div class="card-header">
                <div class="card-header-left">
                  <div class="card-title">${escapeHtml(item.title)}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  <div class="card-date">${formatDate(item.date)}</div>
                  <div class="card-relative-day">${relativeDay(item.date)}</div>
                  ${renderFamilyBadges(item.date, item.time)}
                  <div class="wod-chevron">▾</div>
                </div>
              </div>
              ${focusBadge}
              ${openGymProgramHtml}
            </div>
          </div>`;
      }

      if (wods && wods.length > 0) {
        const sections = renderWodSections(wods, item.date);
        const envBadge = !cancelled ? renderEnvBadge(item.date) : '';
        return `
          <div class="card has-wod" data-wod-date="${item.date}" style="animation-delay:${delay}s" onclick="toggleWod(this, event)">
            <div class="card-dot dot-active"></div>
            <div class="card-info">
              <div class="card-header">
                <div class="card-header-left">
                  <div class="card-title">${escapeHtml(item.title)}</div>
                  ${metaHtml}
                </div>
                <div class="card-right">
                  <div class="card-date">${formatDate(item.date)}</div>
                  <div class="card-relative-day">${relativeDay(item.date)}</div>
                  ${renderFamilyBadges(item.date, item.time)}
                  <div class="wod-chevron">▾</div>
                </div>
              </div>
              <div class="card-wod">${envBadge}${sections}</div>
            </div>
          </div>`;
      }

      const undoBtn = cancelled && item.event_id ? `
        <div class="cancelled-undo" onclick="event.stopPropagation()">
          <button class="niet-gedaan-btn" id="undo-${item.event_id}"
            onclick="markOngedaanGemaakt('${item.event_id}','${item.date}','${item.time}','${escapeHtml(item.title)}',this)">
            Ongedaan maken
          </button>
        </div>` : '';

      return `
        <div class="card ${cancelled ? 'cancelled' : ''}" style="animation-delay:${delay}s" ${cancelled ? 'onclick="this.classList.toggle(\'open\')"' : ''}>
          <div class="card-dot ${cancelled ? 'dot-cancelled' : 'dot-active'}"></div>
          <div class="card-info">
            <div class="card-title">${escapeHtml(item.title)}</div>
            ${metaHtml}
            ${undoBtn}
          </div>
          <div class="card-right">
            <div class="card-date ${cancelled ? 'cancelled-date' : ''}">${formatDate(item.date)}</div>
            <div class="card-relative-day">${relativeDay(item.date)}</div>
            ${renderFamilyBadges(item.date, item.time)}
          </div>
        </div>`;
    }

    // Registreer service worker
    let swRegistration = null;
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sportbit/sw.js').then(reg => {
        swRegistration = reg;
      });
    }

    function _urlBase64ToUint8Array(base64String) {
      const padding = '='.repeat((4 - base64String.length % 4) % 4);
      const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
      const raw = atob(base64);
      return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
    }

    async function subscribeToPush() {
      if (!('Notification' in window) || !('PushManager' in window)) {
        alert('Push notificaties worden niet ondersteund door deze browser.');
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        alert('Notificatietoestemming geweigerd.');
        return;
      }
      if (!swRegistration) {
        swRegistration = await navigator.serviceWorker.ready;
      }
      try {
        const subscription = await swRegistration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: _urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
        });
        await _savePushSubscription(subscription);
        localStorage.setItem('huppa_push_subscribed', '1');
        renderActiesTab(null);
        alert('Notificaties ingeschakeld! 🎉');
      } catch (err) {
        console.error('Push subscribe mislukt:', err);
        alert('Inschrijven voor notificaties mislukt: ' + err.message);
      }
    }

    async function _savePushSubscription(subscription) {
      const token = document.getElementById('githubToken').value.trim();
      const gistId = currentGistId;
      if (!token || !gistId) throw new Error('GitHub token of Gist ID ontbreekt');
      await fetch(`https://api.github.com/gists/${gistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: { 'push_subscription.json': { content: JSON.stringify(subscription.toJSON(), null, 2) } },
        }),
      }).then(r => { if (!r.ok) throw new Error(`Gist PATCH mislukt: ${r.status}`); });
    }

    // ── SugarWOD ──────────────────────────────────────────────

    let wodByDate = {};
    let workoutPlans = {};
    let barbellLifts = {};
    let barbellLiftsHistory = []; // [{date, lifts: {...}}]
    let recoveryAdvice = null;
    let recoveryAdviceHistory = []; // [{date, advice, timestamp?}] laatste 3 dagen
    let recoveryAdviceFromHistory = false; // true als advies uit history komt i.p.v. vandaag
    let recoveryAdviceGeneratedAt = null; // ISO timestamp NL tijd
    let workoutPlansGeneratedAt = null; // ISO timestamp NL tijd
    let personalRecords = [];
    let benchmarkWorkouts = [];
    let workoutLog = {};   // {date: entry} from workout_log.json
    let stravaData = null; // Strava activiteiten data
    let healthInput = {}; // Subjectieve hersteldata {slaap, energie, spierpijn, stress}
    let healthHistory = []; // [{date, slaap, energie, spierpijn, stress}]
    let classCapacity = {}; // {"YYYY-MM-DD_HH:MM": {available, is_full, checked_at}}
    let exclusions = {};   // {"YYYY-MM-DD_HH:MM": {excluded_at}}
    let familyBookings = {}; // {"YYYY-MM-DD_HH:MM": ["Laura", "Eva"]}
    let personalEvents = []; // [{id, title, date, time?, location?, notes?, created_at}]
    let intervalsData = null;   // {wellness: {by_date: {...}}, activities: {by_date: {...}}, fetched_at}
    let withingsData = null;    // {measurements: [...], fetched_at}
    let deloadAlert = false;    // true als overtraining risico gedetecteerd
    let environmentalData = null; // {training_conditions: {...}, aqi: {...}, fetched_at}
    let runningPlanData = null; // {generated_at, week_number, workouts: [{date, type, name, description, total_duration_min}]}
    let runningAnalysisData = null; // {version, updated_at, by_date: {date: {completed, metrics, coach, verdict}}, pending_adjustments: [{id, target_date, status, workout}]}
    let openGymProgram = null; // {generated_at, for_date, for_time, event_title, program_markdown}
    let openGymProgramsByEventId = {}; // event_id → {program_markdown, focus_summary, generated_at}
    let homeWorkoutLog = {}; // {date: entry} from home_workout_log.json
    let homeWorkoutPlan = null; // {generated_at, date, coaching_note, intensity_level, exercises, squat, mobility, estimated_duration_min}
    let workoutOverrides = {}; // {date: {title: {original_description, original_athlete_notes, description, athlete_notes, deleted, modified_at}}}
    let activeChartLift = null;
    let liftChart = null;

    const MAIN_KEYWORDS = ['metcon', 'weightlifting', 'team metcon', 'strength', 'conditioning'];

    const HOME_WORKOUT = {
      label: 'Thuistraining',
      duration_min: 10,
      start_date: '2026-04-28',
      exercises: [
        { id: 'pushup_1', name: 'Pushups',  reps: 12, rest_s: 20 },
        { id: 'situp',    name: 'Sit-ups',  reps: 25, rest_s: 20 },
        { id: 'pushup_2', name: 'Pushups',  reps: 12, rest_s: 20 },
        { id: 'squat',    name: 'Squats',   reps: 20, rest_s: 20, variant_key: true },
        { id: 'pushup_3', name: 'Pushups',  reps: 12, rest_s: 0  },
      ],
      squat_progression: [
        { from_week:  1, variant: 'bw',            label: 'Bodyweight Squats',    sub: '',        sets: 1, reps: 20 },
        { from_week:  5, variant: 'goblet_12kg',    label: 'Goblet Squat',         sub: 'KB 12kg', sets: 1, reps: 20 },
        { from_week:  9, variant: 'goblet_2x12',    label: 'Goblet Squat',         sub: 'KB 12kg', sets: 2, reps: 12 },
        { from_week: 13, variant: 'db_goblet_12',   label: 'Goblet Squat',         sub: 'DB 12kg', sets: 2, reps: 15 },
        { from_week: 17, variant: 'db_goblet_16',   label: 'Goblet Squat',         sub: 'DB 16kg', sets: 2, reps: 12 },
        { from_week: 21, variant: 'db_front_2x8',   label: 'DB Front Squat',       sub: '2×8kg',   sets: 3, reps: 10 },
        { from_week: 25, variant: 'db_front_2x12',  label: 'DB Front Squat',       sub: '2×12kg',  sets: 3, reps: 8  },
        { from_week: 29, variant: 'db_lunge_2x8',   label: 'DB Alternating Lunge', sub: '2×8kg',   sets: 3, reps: 10 },
        { from_week: 33, variant: 'db_front_2x16',  label: 'DB Front Squat',       sub: '2×16kg',  sets: 3, reps: 6  },
      ],
    };

    const MOBILITY_CATALOG = [
      { id: 'mob_hip_flexor',   name: 'Heupbuiger Stretch',       duration: '45s/kant', keywords: ['squat', 'lunge', 'thruster', 'wallball', 'wall ball', 'run'],
        desc: 'Stap naar voren in een uitvalspas, achterste knie op de grond. Kantel het bekken naar voren en duw de heup naar de vloer tot je rek voelt in de voorkant van de heup. Verlost de heupbuigers na squats, lunges en hardlopen.' },
      { id: 'mob_pigeon',       name: 'Duif Pose (Pigeon)',        duration: '60s/kant', keywords: ['squat', 'hip', 'run', 'deadlift', 'kettlebell'],
        desc: 'Voorste been horizontaal voor je, achterste been gestrekt naar achter. Laat de heupen zakken en leun zo nodig voorover op je onderarmen. Opent de diepe heupspieren (piriformis) na squats en hardlopen.' },
      { id: 'mob_ankle',        name: 'Enkel Mobiliteit',          duration: '10r/kant', keywords: ['squat', 'run', 'box jump', 'double under'],
        desc: 'Voet plat op de grond, duw de knie langzaam over de teen naar voren, hak blijft de grond raken. Vergroot enkeldorsiflexie voor diepere squats en soepeler afwikkeling bij het lopen.' },
      { id: 'mob_quad',         name: 'Quad Stretch (staand)',     duration: '45s/kant', keywords: ['squat', 'lunge', 'run', 'bike'],
        desc: 'Staand één been naar achter buigen, enkel vasthouden. Rechte rug, knieën naast elkaar. Rekt de quadriceps en het kniegewricht na squats, lunges en fietsen.' },
      { id: 'mob_glute_bridge', name: 'Glute Bridge',              duration: '15 reps',  keywords: ['squat', 'deadlift', 'run', 'hip', 'lunge'],
        desc: 'Op rug liggen, knieën gebogen, voeten plat. Duw de heupen omhoog, knijp bovenaan de bilspieren samen, houd 1 seconde vast. Activeert en versterkt de gluteus voor betere hip-extensie en looploophouding.' },
      { id: 'mob_chest',        name: 'Deurpost Borststretch',     duration: '30s/kant', keywords: ['push', 'bench', 'dip', 'handstand'],
        desc: 'Onderarm verticaal tegen de deurpost, elleboog op schouderhoogte. Draai langzaam weg van de muur tot je rek voelt in de borst en schouder. Opent de borstkas na push-oefeningen.' },
      { id: 'mob_shoulder',     name: 'Schouder Openingsstretch',  duration: '30s/kant', keywords: ['shoulder', 'press', 'snatch', 'overhead', 'thruster', 'jerk'],
        desc: 'Arm horizontaal, gebruik een deurpost of muur voor weerstand terwijl je de romp wegdraait. Rekt de achterste schouderkapsel na persen en overhead-werk.' },
      { id: 'mob_wrist',        name: 'Pols Mobiliteit',           duration: '1 min',    keywords: ['push', 'clean', 'snatch', 'front squat', 'handstand'],
        desc: 'Vingers naar voren én naar achter op de vloer leunen, cirkels maken met de pols. Verbetert polsflexie/-extensie — essentieel voor front squats, handstands en clean.' },
      { id: 'mob_lat',          name: 'Lat Stretch aan Deur',      duration: '30s/kant', keywords: ['pull', 'row', 'rope climb', 'muscle'],
        desc: 'Houd de deurpost vast op schouderhoogte, laat het gewicht van je romp de lat uitrekken terwijl je de heup naar buiten duwt. Verlost de brede rugspier na pull-ups en roeien.' },
      { id: 'mob_hamstring',    name: 'Hamstring Stretch',         duration: '45s/kant', keywords: ['deadlift', 'rdl', 'run', 'swing', 'good morning'],
        desc: 'Leg zittend één been gestrekt, teen naar je toe, leun recht naar voren over het been. Rekt de hamstrings na deadlifts, kettlebell swings en hardlopen.' },
      { id: 'mob_cat_cow',      name: 'Cat-Cow',                   duration: '10 reps',  keywords: ['deadlift', 'back', 'situp', 'sit-up', 'ghd'],
        desc: 'Op handen en knieën: afwisselend de rug bollen (Cat) en hol trekken met hoofd omhoog (Cow), gelijkmatig adem. Mobiliseert de gehele wervelkolom na sit-ups en rug-belastend werk.' },
      { id: 'mob_thoracic',     name: 'Thoracale Rotatie',         duration: '10r/kant', keywords: ['row', 'press', 'snatch', 'back', 'shoulder'],
        desc: 'Zijligging, knieën 90°, onderste arm gestrekt. Draai de bovenste arm en schouder zo ver mogelijk naar achter zonder de heupen mee te draaien. Verbetert rotatie in de borstwervelkolom voor persen en roeien.' },
      { id: 'mob_calf',         name: 'Kuit Stretch',              duration: '45s/kant', keywords: ['run', 'box jump', 'double under', 'jump rope'],
        desc: 'Handen tegen de muur, één been naar achter met gestrekte knie en hak op de grond. Houd aan. Rekt de kuitspier (gastrocnemius) na hardlopen en springoefeningen.' },
      { id: 'mob_t_spine',      name: 'Foam Roller Ruggengraat',   duration: '1 min',    keywords: ['deadlift', 'row', 'back squat', 'bench'],
        desc: 'Foam roller dwars onder de borstwervelkolom, armen gekruist voor de borst. Laat segment voor segment de rug over de roller vallen. Mobiliseert de thoracale wervelkolom en verlicht spanning na zwaar rugwerk.' },
    ];

    function getProgramWeek() {
      const start = new Date(HOME_WORKOUT.start_date);
      const now   = new Date();
      const days  = Math.floor((now - start) / 86400000);
      return Math.max(1, Math.floor(days / 7) + 1);
    }

    function getCurrentSquatVariant() {
      const week = getProgramWeek();
      const prog = HOME_WORKOUT.squat_progression;
      let chosen = prog[0];
      for (const step of prog) {
        if (week >= step.from_week) chosen = step;
        else break;
      }
      return chosen;
    }

    function getWodText(dayOffset) {
      const dt = new Date();
      dt.setDate(dt.getDate() + dayOffset);
      const dateStr = dt.toISOString().slice(0, 10);
      // Only return WOD text for classes the user is actually attending
      const isSignedUp = dayOffset >= 0
        ? _upcomingCrossfit.some(e => e.date === dateStr)
        : _pastCrossfit.some(e => e.date === dateStr);
      if (!isSignedUp) return '';
      const wods = wodByDate[dateStr] || [];
      return wods.map(w => [w.title, w.description, w.scaling].filter(Boolean).join(' ')).join(' ').toLowerCase();
    }

    // Returns combined text from ALL activity sources: CrossFit, running plan, personal events, completed workouts
    function getAllActivityText(dayOffset) {
      const dt = new Date();
      dt.setDate(dt.getDate() + dayOffset);
      const dateStr = dt.toISOString().slice(0, 10);
      const parts = [];

      // CrossFit WOD (only if signed up)
      const isCFSignedUp = dayOffset >= 0
        ? _upcomingCrossfit.some(e => e.date === dateStr)
        : _pastCrossfit.some(e => e.date === dateStr);
      if (isCFSignedUp) {
        const wods = wodByDate[dateStr] || [];
        parts.push(wods.map(w => [w.title, w.description, w.scaling].filter(Boolean).join(' ')).join(' ').toLowerCase());
      }

      // Running plan workouts (planned or completed)
      (runningPlanData?.workouts || []).filter(w => w.date === dateStr).forEach(w => {
        parts.push([w.type, w.session, w.name, w.description].filter(Boolean).join(' ').toLowerCase());
        parts.push('run'); // ensure run-related mobility keywords match
      });

      // Personal events
      personalEvents.filter(e => e.date === dateStr).forEach(e => {
        parts.push([e.title, e.notes].filter(Boolean).join(' ').toLowerCase());
      });

      // Completed activities from Intervals / Strava
      const intervalsActs = ((intervalsData?.activities || {}).by_date || {})[dateStr] || [];
      const stravaActs = (stravaData?.activities_by_date || {})[dateStr] || [];
      [...intervalsActs, ...stravaActs].forEach(a => {
        parts.push([a.name, a.type].filter(Boolean).join(' ').toLowerCase());
      });

      return parts.join(' ');
    }

    // Returns load summary for a completed day (from Intervals / Strava)
    function getCompletedLoadForDay(dayOffset) {
      const dt = new Date();
      dt.setDate(dt.getDate() + dayOffset);
      const dateStr = dt.toISOString().slice(0, 10);
      const runTypes = ['run', 'running', 'trailrun', 'treadmill', 'jog'];
      const intervalsActs = ((intervalsData?.activities || {}).by_date || {})[dateStr] || [];
      const stravaActs = (stravaData?.activities_by_date || {})[dateStr] || [];
      let maxLoad = 0, totalDuration = 0, hasRun = false, hasCrossfit = false, hasLongRun = false;
      [...intervalsActs, ...stravaActs].forEach(a => {
        const tl = a.training_load || a.trimp || 0;
        if (tl > maxLoad) maxLoad = tl;
        totalDuration += a.duration_min || 0;
        const isRun = runTypes.some(rt => (a.type || '').toLowerCase().includes(rt));
        if (isRun) { hasRun = true; if ((a.duration_min || 0) > 45) hasLongRun = true; }
        else hasCrossfit = true;
      });
      return { maxLoad, totalDuration, hasRun, hasCrossfit, hasLongRun };
    }

    function getWorkoutModifications() {
      const todayText    = getAllActivityText(0);
      const tomorrowText = getAllActivityText(1);
      const upcomingText = todayText + ' ' + tomorrowText;
      const exercises    = HOME_WORKOUT.exercises.map(e => ({ ...e }));
      const squat        = getCurrentSquatVariant();
      let squatReps      = squat.reps;
      const notes        = [];         // adjustment notes (shown in orange banner)
      const recommendations = [];      // AI insights (shown in blue banner)

      // Reduce overlapping muscle groups based on upcoming CrossFit / running
      if (/squat|thruster|wall.?ball|lunge/.test(upcomingText)) {
        squatReps = Math.max(5, Math.round(squat.reps * 0.6));
        notes.push('Squats teruggeschroefd — squatwerk vandaag/morgen in schema');
      }
      if (/push.?up|push.?press|push.?jerk|bench press|handstand push|dip/.test(upcomingText)) {
        exercises.filter(e => e.id.startsWith('pushup')).forEach(e => {
          e.reps = Math.max(8, Math.round(e.reps * 0.6));
          e.adjusted = true;
        });
        notes.push('Pushups teruggeschroefd — duwwerk vandaag/morgen in schema');
      }

      // Recommendations: upcoming running workouts
      const todayStr    = new Date().toISOString().slice(0, 10);
      const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
      const day2Str     = new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 10);
      const day3Str     = new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10);

      const upcomingRuns = (runningPlanData?.workouts || []).filter(w =>
        w.date === todayStr || w.date === tomorrowStr
      );
      const soonRuns = (runningPlanData?.workouts || []).filter(w =>
        w.date === day2Str || w.date === day3Str
      );

      if (upcomingRuns.length > 0) {
        const isLong = upcomingRuns.some(w =>
          /long|lang|duur/.test([w.session, w.name, w.description].join(' ').toLowerCase())
        );
        const when = upcomingRuns[0].date === todayStr ? 'vandaag' : 'morgen';
        const label = upcomingRuns[0].name || upcomingRuns[0].session || 'hardlooptraining';
        if (isLong) {
          recommendations.push(`Lange duurloop ${when} — spaar de benen, doe squats op gevoel of sla ze over`);
        } else {
          recommendations.push(`Hardlooptraining ${when} (${label}) — houd energie over voor de run`);
        }
      } else if (soonRuns.length > 0) {
        const isLong = soonRuns.some(w =>
          /long|lang|duur/.test([w.session, w.name, w.description].join(' ').toLowerCase())
        );
        if (isLong) {
          const when = soonRuns[0].date === day2Str ? 'overmorgen' : 'over 3 dagen';
          recommendations.push(`Lange duurloop ${when} — train comfortabel, niet tot uitputting`);
        }
      }

      // Recommendations: recent completed workouts
      const yesterday  = getCompletedLoadForDay(-1);
      const dayBefore  = getCompletedLoadForDay(-2);
      if (yesterday.hasLongRun) {
        recommendations.push('Lange duurloop gisteren — prioriteit vandaag: herstel en mobiliteit');
      } else if (yesterday.hasCrossfit && yesterday.maxLoad > 80) {
        recommendations.push('Intensieve CrossFit gisteren — doe dit op 70–80% als je moe bent');
      } else if (yesterday.hasRun && yesterday.totalDuration > 40) {
        recommendations.push('Flinke hardloopsessie gisteren — geef de benen wat ruimte');
      }
      if (dayBefore.hasLongRun && !yesterday.hasLongRun) {
        recommendations.push('Lange duurloop eergisteren — squats op gevoel, herstel gaat voor');
      }

      // Recommendations: upcoming sport events
      [todayStr, tomorrowStr, day2Str, day3Str].forEach(d => {
        personalEvents.filter(e => e.date === d && /race|wedstrijd|hardloop|run|loop|triathlon|event/i.test(
          (e.title || '') + ' ' + (e.notes || '')
        )).forEach(e => {
          const when = d === todayStr ? 'vandaag' : d === tomorrowStr ? 'morgen' : 'binnenkort';
          recommendations.push(`${e.title} ${when} — bewaar energie voor het event`);
        });
      });

      return { exercises, notes, squatReps, squatSets: squat.sets, recommendations };
    }

    function getRelevantMobility() {
      const allText = [
        getAllActivityText(-2), getAllActivityText(-1), getAllActivityText(0),
        getAllActivityText(1),  getAllActivityText(2),
      ].join(' ');
      const defaults = ['mob_hip_flexor', 'mob_chest', 'mob_cat_cow'];

      const scored = MOBILITY_CATALOG.map(m => {
        const matchCount = m.keywords.filter(kw => allText.includes(kw)).length;
        let priority = 0;
        if (matchCount >= 2) priority = 2;
        else if (matchCount === 1) priority = 1;
        return { ...m, priority, matchCount };
      });

      const relevant = scored.filter(m => m.matchCount > 0 || defaults.includes(m.id));
      const result   = relevant.length > 0 ? relevant : scored.filter(m => defaults.includes(m.id));
      result.sort((a, b) => b.priority - a.priority || b.matchCount - a.matchCount);
      return result.slice(0, 6);
    }

    function getMobilityDesc(id) {
      return MOBILITY_CATALOG.find(x => x.id === id)?.desc || '';
    }

    function toggleMobInfo(e, btn) {
      e.preventDefault();
      e.stopPropagation();
      btn.closest('.hw-mob-item')?.classList.toggle('info-open');
    }

    // Load saved token
    const savedToken = localStorage.getItem('huppa_github_token');
    if (savedToken) document.getElementById('githubToken').value = savedToken;

    document.getElementById('githubToken').addEventListener('change', () => {
      const t = document.getElementById('githubToken').value.trim();
      if (t) localStorage.setItem('huppa_github_token', t);
    });

    // Render Acties tab so config inputs are always accessible regardless of data state
    renderActiesTab(null);

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
        try {
          const r = await fetch(f.raw_url, { headers: authHeaders || {} });
          if (r.ok) f.content = await r.text();
          else console.warn(`Gist-bestand ${f.filename}: raw_url gaf ${r.status}`);
        } catch (e) {
          console.warn(`Gist-bestand ${f.filename} kon niet volledig geladen worden:`, e);
        }
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

      localStorage.setItem('huppa_gist_id', gistId);
      currentGistId = gistId;

      const todayEl = document.getElementById('today-content');
      if (todayEl) todayEl.innerHTML = buildSkeleton();


      const token = document.getElementById('githubToken').value.trim();
      const authHeaders = token ? { Authorization: `token ${token}` } : {};

      try {
        // Single fetch — parse all files from one response
        const resp = await fetch(`https://api.github.com/gists/${gistId}`, { headers: authHeaders });
        if (!resp.ok) throw new Error(`GitHub API fout: ${resp.status}`);
        const gist = await resp.json();
        await hydrateTruncatedFiles(gist, authHeaders);

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

        // Bereken geplande slots die nog niet ingeschreven zijn (komende 14 dagen)
        const signedUpKeys = new Set(signedUp.map(e => `${e.date}_${e.time}`));
        const pendingSlots = [];
        for (let i = 1; i <= 14; i++) {
          const d = new Date(); d.setDate(d.getDate() + i);
          const dateStr = d.toISOString().slice(0, 10);
          for (const [jsDay, time] of CROSSFIT_SCHEDULE) {
            if (d.getDay() === jsDay && !signedUpKeys.has(`${dateStr}_${time}`)) {
              pendingSlots.push({ date: dateStr, time, key: `${dateStr}_${time}` });
            }
          }
        }
        pendingSlots.sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));

        // Bereken slots waar alleen familie ingeschreven is (niet Ralph zelf)
        const familyOnlySlots = Object.entries(familyBookings)
          .filter(([key]) => key.slice(0, 10) >= todayStr && !signedUpKeys.has(key))
          .map(([key, members]) => ({ date: key.slice(0, 10), time: key.slice(11), members }))
          .sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));

        // Render each tab
        renderTodayTab(upcoming, past, allUpcoming);
        renderSchemaTab(allUpcoming, recentCancelled, pastItems, pendingSlots, familyOnlySlots);
        renderStatsTab();
        renderPlanTab();
        renderActiesTab(gist.updated_at);

      } catch (e) {
        const el = document.getElementById('today-content');
        if (el) el.innerHTML = `<div class="error-msg">❌ ${e.message}</div>`;
      }
    }

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

      // Actieve blessures — zichtbaar bij de coaching die erop is aangepast
      const activeInjuries = getInjuries().filter(i => i.status !== 'hersteld');
      if (activeInjuries.length) {
        const items = activeInjuries.map(i => {
          const bits = [i.severity, i.status === 'herstellend' ? 'herstellend' : ''].filter(Boolean);
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
              <div class="card-meta"><span class="card-time">${slot.time}</span>&nbsp;·&nbsp;${isExcl ? '<span style="color:#ff6b6b">Overgeslagen</span>' : '<span style="color:var(--text-muted)">Nog niet ingeschreven</span>'}</div>
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
      const planHtml = renderRunningPlanSection();
      h += planHtml || `<div class="empty">📋 Geen hardloopplan beschikbaar</div>`;
      el.innerHTML = h;
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
          <input type="password" id="githubToken-vis" class="config-input" placeholder="GitHub Token (ghp_...)">
          <button class="workflow-btn" onclick="_saveActiesConfig()">Opslaan</button>
        </div>`;
      } else {
        h += `<details class="acties-token-details">
          <summary>⚙ Instellingen wijzigen</summary>
          <div class="acties-config">
            <input type="text" id="gistId-vis" class="config-input" placeholder="Gist ID" value="${escapeHtml(currentGistId)}"
              onchange="document.getElementById('gistId').value=this.value;localStorage.setItem('huppa_gist_id',this.value);currentGistId=this.value.trim()">
            <input type="password" id="githubToken-vis" class="config-input" placeholder="GitHub Token">
            <button class="workflow-btn" onclick="_saveActiesConfig()">Opslaan</button>
          </div>
        </details>`;
      }

      h += renderInjuriesCard();

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

    async function triggerReviewRunning() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('reviewRunStatus');
      const btn = document.getElementById('reviewRunBtn');
      const modeDaily = document.getElementById('reviewModeDaily').checked;
      const modePrerun = document.getElementById('reviewModePrerun').checked;

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '🔍 Bezig…';
      statusEl.textContent = 'Review workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();
      const mode = modePrerun ? 'prerun' : modeDaily ? 'daily' : 'auto';

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/review_running_workout.yml/dispatches',
          {
            method: 'POST',
            headers: {
              Authorization: `token ${token}`,
              Accept: 'application/vnd.github+json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main', inputs: { mode } }),
          }
        );

        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false;
          btn.textContent = '🔍 Review';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'review_running_workout.yml', '🔍 Review');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '🔍 Review';
      }
    }

    async function triggerRepush() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('repushStatus');
      const btn = document.getElementById('repushBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '↑ Bezig…';
      statusEl.textContent = 'Repush workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/repush_workouts.yml/dispatches',
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
          btn.textContent = '↑ Sync naar Garmin';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'repush_workouts.yml', '↑ Sync naar Garmin');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '↑ Sync naar Garmin';
      }
    }

    async function triggerAnalyzeRunning() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('analyzeRunStatus');
      const btn = document.getElementById('analyzeRunBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '📊 Bezig…';
      statusEl.textContent = 'Analyse workflow starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/analyze_running_workout.yml/dispatches',
          {
            method: 'POST',
            headers: {
              Authorization: `token ${token}`,
              Accept: 'application/vnd.github+json',
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main', inputs: { mode: 'analyze' } }),
          }
        );

        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false;
          btn.textContent = '📊 Analyseer Runs';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'analyze_running_workout.yml', '📊 Analyseer Runs');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '📊 Analyseer Runs';
      }
    }

    async function triggerCancelCleanup() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('cancelCleanupStatus');
      const btn = document.getElementById('cancelCleanupBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '🗑 Bezig…';
      statusEl.textContent = 'Events verwijderen…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/reschedule_running_workout.yml/dispatches',
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
          btn.textContent = '🗑 Verwijder geannuleerde events';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'reschedule_running_workout.yml', '🗑 Verwijder geannuleerde events');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '🗑 Verwijder geannuleerde events';
      }
    }

    async function triggerGcalSync() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('gcalSyncStatus');
      const btn = document.getElementById('gcalSyncBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '📅 Bezig…';
      statusEl.textContent = 'Sync starten…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/sync_to_gcal.yml/dispatches',
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
          btn.textContent = '📅 Sync naar Google Agenda';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'sync_to_gcal.yml', '📅 Sync naar Google Agenda');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '📅 Sync naar Google Agenda';
      }
    }

    async function triggerOpenGymProgram() {
      const token = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('openGymStatus');
      const btn = document.getElementById('openGymBtn');

      if (!token) {
        statusEl.textContent = 'Vul eerst je GitHub Token in (nodig om workflow te starten)';
        statusEl.style.color = 'var(--accent2)';
        return;
      }

      btn.disabled = true;
      btn.textContent = '🏋️ Bezig…';
      statusEl.textContent = 'Programma genereren…';
      statusEl.style.color = 'var(--muted)';

      const triggerTime = new Date();

      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/generate_open_gym_program.yml/dispatches',
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
          btn.textContent = '🏋️ Open Gym Programma';
          return;
        }

        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, 'generate_open_gym_program.yml', '🏋️ Open Gym Programma');

      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false;
        btn.textContent = '🏋️ Open Gym Programma';
      }
    }

    async function triggerHomeWorkoutPlan(ev) {
      if (ev) ev.stopPropagation();
      const token    = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('homeWorkoutStatus');
      const btn      = document.getElementById('homeWorkoutBtn');

      if (!token) {
        if (statusEl) { statusEl.textContent = 'GitHub token vereist'; statusEl.style.color = 'var(--accent2)'; }
        else alert('Vul eerst je GitHub Token in via Acties');
        return;
      }

      if (btn) { btn.disabled = true; btn.textContent = '🏠 Bezig…'; }
      if (statusEl) { statusEl.textContent = 'Plan genereren…'; statusEl.style.color = 'var(--muted)'; }

      const triggerTime = new Date();
      try {
        const resp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/generate_home_workout.yml/dispatches',
          {
            method: 'POST',
            headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref: 'main', inputs: {} }),
          }
        );
        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          if (statusEl) { statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`; statusEl.style.color = 'var(--accent2)'; }
          if (btn) { btn.disabled = false; btn.textContent = '🏠 Thuistraining Plan'; }
          return;
        }
        if (statusEl) { statusEl.textContent = '⏳ In wachtrij…'; statusEl.style.color = 'var(--muted)'; }
        if (btn) await pollWorkflowRun(token, triggerTime, statusEl, btn, 'generate_home_workout.yml', '🏠 Thuistraining Plan');
        else alert('Plan genereren gestart — ververs de pagina over ~30 seconden.');
      } catch (e) {
        if (statusEl) { statusEl.textContent = `Netwerkfout: ${e.message}`; statusEl.style.color = 'var(--accent2)'; }
        if (btn) { btn.disabled = false; btn.textContent = '🏠 Thuistraining Plan'; }
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
                  let doneMsg = `✅ Data bijgewerkt (${elapsed}s)`;
                  if (workflowFile === 'review_running_workout.yml' && runningPlanData?.last_review_duration_s) {
                    doneMsg += ` — AI: ${runningPlanData.last_review_duration_s}s`;
                  }
                  statusEl.textContent = doneMsg;
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
      const workflowFile = btn.dataset.wf;
      const label = btn.dataset.label || btn.textContent;
      let inputs = {};
      try { inputs = JSON.parse(decodeURIComponent(btn.dataset.inputs || '%7B%7D')); } catch (_) {}

      const token = (document.getElementById('githubToken')?.value || '').trim()
                 || (localStorage.getItem('huppa_github_token') || '').trim();

      if (!token) {
        if (statusEl) { statusEl.textContent = 'GitHub token vereist — stel in via Acties'; statusEl.style.color = 'var(--accent2)'; }
        else alert('Vul eerst je GitHub Token in via Acties');
        return;
      }
      if (!statusEl) return; // markup safeguard: pollWorkflowRun heeft een status-element nodig

      btn.disabled = true;
      btn.textContent = '⏳ Bezig…';
      statusEl.textContent = 'Workflow starten…';
      statusEl.style.color = 'var(--muted)';
      const triggerTime = new Date();

      try {
        const resp = await fetch(
          `https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/${workflowFile}/dispatches`,
          {
            method: 'POST',
            headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref: 'main', inputs }),
          }
        );
        if (resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          statusEl.textContent = `Fout ${resp.status}: ${body.message || 'onbekend'}`;
          statusEl.style.color = 'var(--accent2)';
          btn.disabled = false; btn.textContent = label;
          return;
        }
        statusEl.textContent = '⏳ In wachtrij…';
        statusEl.style.color = 'var(--muted)';
        await pollWorkflowRun(token, triggerTime, statusEl, btn, workflowFile, label);
      } catch (e) {
        statusEl.textContent = `Netwerkfout: ${e.message}`;
        statusEl.style.color = 'var(--accent2)';
        btn.disabled = false; btn.textContent = label;
      }
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
      ];
      await Promise.all(runs.map(async ({ id, file }) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = '…';
        try {
          const r = await fetch(
            `https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/${file}/runs?per_page=1`,
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
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
      const statusEl = document.getElementById('adjstatus-' + adjId);
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      try {
        setStatus('Opslaan…');
        await _patchAnalysisStatus(token, adjId, 'applied');
        setStatus('✓ Goedgekeurd — intervals.icu bijwerken…', '#4caf50');
        const triggerTime = new Date();
        const triggerResp = await fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/analyze_running_workout.yml/dispatches',
          {
            method: 'POST',
            headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref: 'main', inputs: { mode: 'apply' } }),
          }
        );
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
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
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

    // ── Blessures ─────────────────────────────────────────────
    // Opgeslagen in health_input.json (sleutel "injuries") — dezelfde bron die álle
    // AI-coaches lezen (WOD-plan, herstel-advies, Open Gym, thuistraining, hardlopen).
    // INJURY_SEVERITIES / INJURY_STATUSES staan bovenaan het bestand: de eerste render
    // draait al voordat dit blok is uitgevoerd.

    function _normaliseInjury(raw, idx) {
      if (typeof raw === 'string') {
        return { id: `inj-${idx}`, area: raw.trim(), description: '', severity: '',
                 status: 'actief', since: '', avoid: [], notes: '' };
      }
      if (!raw || typeof raw !== 'object') return null;
      const avoid = Array.isArray(raw.avoid)
        ? raw.avoid.filter(Boolean).map(String)
        : (raw.avoid ? String(raw.avoid).split(',').map(s => s.trim()).filter(Boolean) : []);
      return {
        id: String(raw.id || `inj-${idx}`),
        area: String(raw.area || '').trim(),
        description: String(raw.description || '').trim(),
        severity: INJURY_SEVERITIES.includes(raw.severity) ? raw.severity : '',
        status: INJURY_STATUSES.includes(raw.status) ? raw.status : 'actief',
        since: String(raw.since || ''),
        avoid,
        notes: String(raw.notes || '').trim(),
      };
    }

    function getInjuries() {
      const raw = healthInput?.injuries;
      if (!raw) return [];
      const items = typeof raw === 'string'
        ? raw.split(/[;\n]/).map(s => s.trim()).filter(Boolean)
        : (Array.isArray(raw) ? raw : [raw]);
      return items.map(_normaliseInjury).filter(x => x && (x.area || x.description));
    }

    function renderInjuriesCard() {
      const injuries = getInjuries();
      const active = injuries.filter(i => i.status !== 'hersteld');

      let rows = '';
      if (injuries.length === 0) {
        rows = `<div class="injury-empty">Geen blessures geregistreerd — de coaches trainen je zonder beperkingen.</div>`;
      } else {
        rows = injuries.map(inj => {
          const meta = [];
          if (inj.severity) meta.push(inj.severity);
          if (inj.since) meta.push(`sinds ${inj.since}`);
          if (inj.avoid.length) meta.push(`vermijden: ${inj.avoid.join(', ')}`);
          const opts = INJURY_STATUSES.map(s =>
            `<option value="${s}"${s === inj.status ? ' selected' : ''}>${s}</option>`).join('');
          return `<div class="injury-row${inj.status === 'hersteld' ? ' injury-resolved' : ''}">
            <div class="injury-main">
              <div class="injury-area">${escapeHtml(inj.area)}</div>
              ${inj.description ? `<div class="injury-desc">${escapeHtml(inj.description)}</div>` : ''}
              ${meta.length ? `<div class="injury-meta">${escapeHtml(meta.join(' · '))}</div>` : ''}
            </div>
            <div class="injury-actions">
              <select class="injury-status" onchange="setInjuryStatus('${escapeHtml(inj.id)}', this.value)">${opts}</select>
              <button class="injury-del" onclick="removeInjury('${escapeHtml(inj.id)}')" title="Verwijderen">✕</button>
            </div>
          </div>`;
        }).join('');
      }

      const sevOpts = ['<option value="">ernst…</option>']
        .concat(INJURY_SEVERITIES.map(s => `<option value="${s}">${s}</option>`)).join('');

      return `<div class="workflow-card" id="injuriesCard">
        <div class="workflow-title">🩹 Blessures${active.length ? ` <span class="injury-badge">${active.length}</span>` : ''}</div>
        <div class="workflow-desc">Wordt automatisch meegegeven aan álle AI-coaches: WOD-uitvoeringsplan, herstel-advies, Open Gym, thuistraining, hardloopschema en hardloop-review. Zet op <em>hersteld</em> om een blessure te bewaren als historie zonder dat de coaches er nog rekening mee houden.</div>
        <div class="injury-list">${rows}</div>
        <div class="injury-form">
          <input type="text" id="injuryArea" class="config-input" placeholder="Lichaamsdeel (bijv. linkerschouder)">
          <input type="text" id="injuryDesc" class="config-input" placeholder="Klacht (bijv. pijn bij overhead druk)">
          <div class="injury-form-row">
            <select id="injurySeverity" class="config-input injury-select">${sevOpts}</select>
            <input type="date" id="injurySince" class="config-input injury-select">
          </div>
          <input type="text" id="injuryAvoid" class="config-input" placeholder="Bewegingen vermijden, komma-gescheiden (optioneel)">
          <div class="workflow-footer">
            <button class="workflow-btn danger" onclick="addInjury()">+ Blessure toevoegen</button>
            <span id="injuryStatus" class="workflow-status"></span>
          </div>
        </div>
      </div>`;
    }

    function _refreshInjuriesCard(msg, color) {
      const card = document.getElementById('injuriesCard');
      if (card) card.outerHTML = renderInjuriesCard();
      const st = document.getElementById('injuryStatus');
      if (st && msg) {
        st.textContent = msg;
        st.style.color = color || '#00c853';
        setTimeout(() => { const e2 = document.getElementById('injuryStatus'); if (e2) e2.textContent = ''; }, 4000);
      }
    }

    async function _saveInjuries(list, msg) {
      const statusEl = document.getElementById('injuryStatus');
      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.style.color = 'var(--muted)'; }
      try {
        await _patchHealthInput({ injuries: list });
        _refreshInjuriesCard(msg || '✓ Opgeslagen');
      } catch(e) {
        if (statusEl) { statusEl.textContent = `Fout: ${e.message}`; statusEl.style.color = 'var(--accent2)'; }
        console.error(e);
      }
    }

    async function addInjury() {
      const area = (document.getElementById('injuryArea')?.value || '').trim();
      const desc = (document.getElementById('injuryDesc')?.value || '').trim();
      if (!area && !desc) {
        const st = document.getElementById('injuryStatus');
        if (st) { st.textContent = 'Vul minimaal een lichaamsdeel in'; st.style.color = 'var(--accent2)'; }
        return;
      }
      const avoid = (document.getElementById('injuryAvoid')?.value || '')
        .split(',').map(s => s.trim()).filter(Boolean);
      const entry = {
        id: String(Date.now()),
        area: area || desc,
        description: area ? desc : '',
        severity: document.getElementById('injurySeverity')?.value || '',
        status: 'actief',
        since: document.getElementById('injurySince')?.value || new Date().toISOString().slice(0, 10),
        avoid,
        notes: '',
      };
      await _saveInjuries([...getInjuries(), entry], '✓ Blessure toegevoegd — coaches houden hier rekening mee');
    }

    async function setInjuryStatus(id, status) {
      const list = getInjuries().map(i => i.id === id ? { ...i, status } : i);
      await _saveInjuries(list, status === 'hersteld' ? '✓ Gemarkeerd als hersteld' : '✓ Status bijgewerkt');
    }

    async function removeInjury(id) {
      const inj = getInjuries().find(i => i.id === id);
      if (inj && !confirm(`"${inj.area}" definitief verwijderen?`)) return;
      await _saveInjuries(getInjuries().filter(i => i.id !== id), '✓ Verwijderd');
    }

    async function _triggerRunGeneration(statusEl) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token) return;
      const setStatus = (msg, color) => { if (statusEl) { statusEl.textContent = msg; statusEl.style.color = color || 'var(--muted)'; } };
      setStatus('⏳ Plan hergeneren…');
      const triggerTime = new Date();
      const r = await fetch(
        'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/generate_running_workout.yml/dispatches',
        { method: 'POST', headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
          body: JSON.stringify({ ref: 'main', inputs: {} }) }
      );
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
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
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
        fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/fetch_health_data.yml/dispatches',
          {
            method: 'POST',
            headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref: 'main', inputs: {} }),
          }
        ).catch(() => {});

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
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
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
        fetch(
          'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/reschedule_running_workout.yml/dispatches',
          {
            method: 'POST',
            headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref: 'main', inputs: {} }),
          }
        ).catch(() => {});

        setTimeout(() => location.reload(), 800);
      } catch(e) {
        if (btn) { btn.disabled = false; btn.textContent = '✕ Bevestig annulering'; }
        setStatus(`❌ ${e.message}`, '#ff6b6b');
      }
    }

    async function undoCancelRun(workoutDate, cardId) {
      const token = document.getElementById('githubToken').value.trim();
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
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
      if (!token || !currentGistId) { alert('GitHub token vereist'); return; }
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
          fetch(
            'https://api.github.com/repos/ralphdeleeuw/sportbit/actions/workflows/sync_to_gcal.yml/dispatches',
            {
              method: 'POST',
              headers: { Authorization: `token ${gcalToken}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
              body: JSON.stringify({ ref: 'main', inputs: {} }),
            }
          ).catch(() => {});
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

    // ── Daily home workout ────────────────────────────────────────────────

    function renderHomeWorkoutCard() {
      const todayStr      = new Date().toISOString().slice(0, 10);
      const entry         = homeWorkoutLog[todayStr];
      const isDone        = entry && (entry.exercises_done || []).length > 0;
      const existingNotes = entry ? (entry.notes || '') : '';
      const doneMobility  = entry ? (entry.mobility_done || []) : [];
      const aiPlan        = (homeWorkoutPlan?.date === todayStr) ? homeWorkoutPlan : null;
      let fallbackAdjNotes   = [];
      let fallbackRecBanners = [];

      // ── Exercise rows ────────────────────────────────────────────────────────
      let exerciseRowsArr = [];

      if (aiPlan) {
        exerciseRowsArr = aiPlan.exercises.map(ex => {
          const repsLabel = ex.sets > 1 ? `${ex.sets}×${ex.reps} reps` : `${ex.reps} reps`;
          const isChecked = entry ? (entry.exercises_done || []).includes(ex.id) : false;
          const hasNote   = !!ex.adaptation_note;
          return `<label class="hw-exercise-row${isChecked ? ' checked' : ''}">
          <input type="checkbox" id="hwex-${ex.id}" value="${ex.id}"${isChecked ? ' checked' : ''}
                 onchange="this.closest('.hw-exercise-row').classList.toggle('checked', this.checked)">
          <div class="hw-exercise-info">
            <div class="hw-exercise-left">
              <span class="hw-exercise-name">${escapeHtml(ex.name)}</span>
              ${hasNote ? `<span class="hw-exercise-sub hw-ai-note">${escapeHtml(ex.adaptation_note)}</span>` : ''}
            </div>
            <div class="hw-reps-block${hasNote ? ' adjusted' : ''}">
              <span class="hw-reps-num">${repsLabel}</span>
            </div>
          </div>
        </label>`;
        });
        // Voeg squat-rij in na positie 2 (na pushup_2, voor pushup_3)
        const sq        = aiPlan.squat;
        const sqLabel   = sq.sets > 1 ? `${sq.sets}×${sq.reps} reps` : `${sq.reps} reps`;
        const sqChecked = entry ? (entry.exercises_done || []).includes('squat') : false;
        exerciseRowsArr.splice(3, 0, `<label class="hw-exercise-row${sqChecked ? ' checked' : ''}">
          <input type="checkbox" id="hwex-squat" value="squat"${sqChecked ? ' checked' : ''}
                 onchange="this.closest('.hw-exercise-row').classList.toggle('checked', this.checked)">
          <div class="hw-exercise-info">
            <div class="hw-exercise-left">
              <span class="hw-exercise-name">${escapeHtml(sq.label)}</span>
              ${sq.sub ? `<span class="hw-exercise-sub">${escapeHtml(sq.sub)}</span>` : ''}
              ${sq.note ? `<span class="hw-exercise-sub hw-ai-note">${escapeHtml(sq.note)}</span>` : ''}
            </div>
            <div class="hw-reps-block">
              <span class="hw-reps-num">${sqLabel}</span>
            </div>
          </div>
        </label>`);
      } else {
        const squat = getCurrentSquatVariant();
        const mods  = getWorkoutModifications();
        exerciseRowsArr = mods.exercises.map(ex => {
          const isSquat   = !!ex.variant_key;
          const name      = isSquat ? escapeHtml(squat.label) : escapeHtml(ex.name);
          const sub       = isSquat && squat.sub ? `<span class="hw-exercise-sub">${escapeHtml(squat.sub)}</span>` : '';
          const repsNum   = isSquat ? mods.squatReps : ex.reps;
          const repsLabel = isSquat && mods.squatSets > 1 ? `${mods.squatSets}×${repsNum} reps` : `${repsNum} reps`;
          const adjusted  = isSquat ? (mods.squatReps !== squat.reps) : !!ex.adjusted;
          const isChecked = entry ? (entry.exercises_done || []).includes(ex.id) : false;
          return `<label class="hw-exercise-row${isChecked ? ' checked' : ''}">
          <input type="checkbox" id="hwex-${ex.id}" value="${ex.id}"${isChecked ? ' checked' : ''}
                 onchange="this.closest('.hw-exercise-row').classList.toggle('checked', this.checked)">
          <div class="hw-exercise-info">
            <div class="hw-exercise-left">
              <span class="hw-exercise-name">${name}</span>
              ${sub}
            </div>
            <div class="hw-reps-block${adjusted ? ' adjusted' : ''}">
              <span class="hw-reps-num">${repsLabel}</span>
            </div>
          </div>
        </label>`;
        });
        // Banners voor fallback-modus
        fallbackAdjNotes    = mods.notes;
        fallbackRecBanners  = mods.recommendations;
      }

      const exerciseRows = exerciseRowsArr.join('');

      // ── Banners ──────────────────────────────────────────────────────────────
      let adjBanner = '';
      let recBanner = '';
      if (aiPlan) {
        if (aiPlan.coaching_note) {
          recBanner = `<div class="hw-recommendations"><span>💡 ${escapeHtml(aiPlan.coaching_note)}</span></div>`;
        }
        if (aiPlan.intensity_level === 'licht') {
          adjBanner = `<div class="hw-adj-banner"><span>↓ Licht schema vandaag</span></div>`;
        } else if (aiPlan.intensity_level === 'volledig') {
          adjBanner = `<div class="hw-adj-banner" style="border-color:var(--green,#4caf50);color:var(--green,#4caf50)"><span>↑ Vol schema — je bent goed uitgerust</span></div>`;
        }
      } else {
        adjBanner = fallbackAdjNotes.length
          ? `<div class="hw-adj-banner">${fallbackAdjNotes.map(n => `<span>↓ ${escapeHtml(n)}</span>`).join('')}</div>`
          : '';
        recBanner = fallbackRecBanners.length
          ? `<div class="hw-recommendations">${fallbackRecBanners.map(r => `<span>💡 ${escapeHtml(r)}</span>`).join('')}</div>`
          : '';
      }

      // ── Mobility rows ────────────────────────────────────────────────────────
      const mobilityItems = aiPlan ? aiPlan.mobility : getRelevantMobility();
      const mobilityRows = mobilityItems.map(m => {
        const isChecked     = doneMobility.includes(m.id);
        const priorityClass = m.priority === 2 ? ' hw-mob-priority-2' : m.priority === 1 ? ' hw-mob-priority-1' : '';
        const badge = m.priority === 2
          ? `<span class="hw-mob-badge hw-mob-badge-2">★★ Aanbevolen</span>`
          : m.priority === 1
          ? `<span class="hw-mob-badge hw-mob-badge-1">★ Aanbevolen</span>`
          : '';
        const desc = getMobilityDesc(m.id);
        const why  = (aiPlan && m.rationale) ? m.rationale : '';
        const hasInfo = !!(desc || why);
        return `<div class="hw-mob-item">
          <label class="hw-exercise-row hw-mob-row${priorityClass}${isChecked ? ' checked' : ''}">
            <input type="checkbox" id="hwmob-${m.id}" value="${m.id}"${isChecked ? ' checked' : ''}
                   onchange="this.closest('.hw-exercise-row').classList.toggle('checked', this.checked)">
            <div class="hw-exercise-info">
              <div class="hw-exercise-left">
                <span class="hw-exercise-name">${escapeHtml(m.name)}</span>
                ${badge}
                ${hasInfo ? `<button type="button" class="hw-info-btn" aria-label="Uitleg" onclick="toggleMobInfo(event, this)">ⓘ</button>` : ''}
              </div>
              <div class="hw-reps-block">
                <span class="hw-reps-num">${escapeHtml(m.duration)}</span>
              </div>
            </div>
          </label>
          ${hasInfo ? `<div class="hw-mob-info">
            ${desc ? `<div class="hw-mob-info-desc">${escapeHtml(desc)}</div>` : ''}
            ${why ? `<div class="hw-mob-info-why">Vandaag: ${escapeHtml(why)}</div>` : ''}
          </div>` : ''}
        </div>`;
      }).join('');

      const durationMin  = aiPlan?.estimated_duration_min ?? HOME_WORKOUT.duration_min;
      const aiIndicator  = aiPlan ? ' · AI' : '';

      return `
        <div class="hw-card${isDone ? ' hw-done' : ''}" onclick="toggleWod(this, event)">
          <div class="hw-card-bar"></div>
          <div class="hw-card-inner">
            <div class="hw-card-header">
              <div>
                <div class="hw-card-eyebrow">Dagelijkse routine · ~${durationMin} min${aiIndicator}</div>
                <div class="hw-card-title">Thuistraining</div>
              </div>
              <div class="hw-card-right">
                ${isDone ? '<div class="hw-done-badge">✓</div>' : ''}
                <div class="wod-chevron" style="color:var(--purple)">▾</div>
              </div>
            </div>
            <div class="card-wod" onclick="event.stopPropagation()">
              ${adjBanner}
              ${recBanner}
              <div class="hw-exercises" id="hw-exercises-${todayStr}">${exerciseRows}</div>
              <div class="hw-section-label">Stretch &amp; Mobiliteit <span class="hw-optional">(optioneel)</span></div>
              <div class="hw-exercises" id="hw-mob-${todayStr}">${mobilityRows}</div>
              <textarea class="log-textarea" id="hw-notes-${todayStr}"
                placeholder="Notities (bijv. squats voelden zwaar, knieën goed…)"
                style="margin-top:0.6rem">${escapeHtml(existingNotes)}</textarea>
              <div class="log-actions">
                <span class="log-status${isDone ? ' ok' : ''}" id="hw-status">${isDone ? '✓ Gedaan' : ''}</span>
                <button class="log-save-btn" onclick="saveHomeWorkout('${todayStr}')">Opslaan</button>
              </div>
              ${aiGenButton('🏠 Plan opnieuw genereren', 'generate_home_workout.yml', {})}
            </div>
          </div>
        </div>`;
    }

    async function saveHomeWorkout(date) {
      const token    = document.getElementById('githubToken').value.trim();
      const statusEl = document.getElementById('hw-status');

      if (!token) {
        if (statusEl) { statusEl.textContent = '⚠ Token nodig'; statusEl.className = 'log-status err'; }
        return;
      }

      const checks    = document.querySelectorAll(`#hw-exercises-${date} input[type="checkbox"]:checked`);
      const done      = Array.from(checks).map(cb => cb.value);
      const mobChecks = document.querySelectorAll(`#hw-mob-${date} input[type="checkbox"]:checked`);
      const mobDone   = Array.from(mobChecks).map(cb => cb.value);
      const notes     = (document.getElementById(`hw-notes-${date}`) || {}).value || '';
      const squat     = getCurrentSquatVariant();

      const newEntry = {
        date,
        exercises_done: done,
        mobility_done:  mobDone,
        squat_variant:  squat.variant,
        notes,
        logged_at: new Date().toISOString(),
      };

      if (statusEl) { statusEl.textContent = 'Opslaan…'; statusEl.className = 'log-status'; }

      try {
        const resp = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          headers: { Authorization: `token ${token}` },
        });
        if (!resp.ok) throw new Error(`GitHub API ${resp.status}`);
        const gist = await resp.json();

        let entries = [];
        const existing = gist.files['home_workout_log.json'];
        if (existing) {
          try { entries = JSON.parse(existing.content).entries || []; } catch(e) {}
        }

        entries = entries.filter(e => e.date !== date);
        entries.push(newEntry);
        entries.sort((a, b) => b.date.localeCompare(a.date));

        const patch = await fetch(`https://api.github.com/gists/${currentGistId}`, {
          method:  'PATCH',
          headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            files: { 'home_workout_log.json': { content: JSON.stringify({ entries }, null, 2) } }
          }),
        });
        if (!patch.ok) throw new Error(`Opslaan mislukt: ${patch.status}`);

        homeWorkoutLog[date] = newEntry;
        if (statusEl) { statusEl.textContent = '✓ Opgeslagen'; statusEl.className = 'log-status ok'; }

        const card = document.querySelector('.hw-card');
        if (card && done.length > 0) card.classList.add('hw-done');
      } catch(e) {
        if (statusEl) { statusEl.textContent = `❌ ${e.message}`; statusEl.className = 'log-status err'; }
      }
    }

    function escapeHtml(str) {
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function safeMarkdown(md) {
      const html = marked.parse(md || '');
      return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
    }
