    // homeworkout.js — Dagelijkse thuistraining.
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

