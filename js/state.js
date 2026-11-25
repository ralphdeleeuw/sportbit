    // state.js — Globale app-state en vaste catalogi (thuistraining, mobiliteit).
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
    let monthlyClassIndex = {}; // event_id of "date_time" → {index, month, pending}
    let monthlyClassTotals = {}; // "YYYY-MM" → aantal ingeschreven lessen
    let monthlyProjectedTotals = {}; // "YYYY-MM" → ingeschreven + nog te boeken geplande lessen
    let monthlyLateCancelTotals = {}; // "YYYY-MM" → late afmeldingen (kosten een credit)
    let exclusions = {};   // {"YYYY-MM-DD_HH:MM": {excluded_at}}
    let familyBookings = {}; // {"YYYY-MM-DD_HH:MM": ["Laura", "Eva"]}
    let huppaAccount = null; // Huppa-maandoverzicht: abonnement, late afmeldingen, no-shows, historie
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
    let wodFetchedAt = null;      // sugarwod_wod.json fetched_at (laatste run van fetch_sugarwod.py)
    let sugarwodFetchedAt = null; // laatste échte SugarWOD-scrape
    let workflowStatus = {};      // workflow_status.json — {workflow: {last_failure, run_url, ...}}
    let weeklyReview = null;      // weekly_review.json — {latest, history}
    let vacations = [];           // sportbit_state.json → vacations [{from, to, note}]
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

