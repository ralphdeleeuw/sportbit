    // core.js — Constanten en algemene helpers (datums, kaarten, escapeHtml/safeMarkdown).
    const DAY_NL = ['Zo', 'Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za'];
    const MONTH_NL = ['jan', 'feb', 'mrt', 'apr', 'mei', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
    // Vaste CrossFit rooster — spiegelt SCHEDULE in autosignup.py (JS getDay: 0=Zo, 6=Za)
    const CROSSFIT_SCHEDULE = [[1,"20:00"],[3,"08:00"],[4,"20:00"],[0,"09:00"]];
    // Abonnement: maximaal aantal CrossFit-lessen per kalendermaand
    const MONTHLY_CLASS_QUOTA = 13;
    // Sportvrienden — alleen deze deelnemers tonen bij een les. Het naamformaat
    // van Huppa is al een paar keer gewisseld: "Erik H.", daarna alleen de
    // voornaam ("Erik"), sinds nov 2026 de volledige naam ("Erik Huisman",
    // "Eline de Roock"). Matchen gaat daarom op voornaam; hebben beide kanten
    // een achternaam, dan moet één van de achternaamdelen met dezelfde letter
    // beginnen. Tussenvoegsels tellen als los deel, zodat zowel "Laura D" als
    // "Laura L" op "Laura de Leeuw" matcht en "Erik Jansen" niet op "Erik H".
    const SPORT_FRIENDS = ['Erik H', 'Linda W', 'Laura D', 'Eva D', 'Robbert S', 'Stefan C'];
    function _nameParts(name) {
      const parts = (name || '').toLowerCase().replace(/\./g, '').split(/\s+/).filter(Boolean);
      return { first: parts[0] || '', initials: parts.slice(1).map(w => w[0]) };
    }
    const _FRIEND_KEYS = SPORT_FRIENDS.map(_nameParts).filter(f => f.first);
    function isSportFriend(name) {
      const p = _nameParts(name);
      if (!p.first) return false;
      // Ontbreekt aan één van beide kanten de achternaam, dan telt de voornaam.
      return _FRIEND_KEYS.some(f => f.first === p.first && (
        !p.initials.length || !f.initials.length || p.initials.some(i => f.initials.includes(i))
      ));
    }

    // Blessures — zie het blessure-blok verderop; hier gedeclareerd omdat de eerste
    // render (renderTodayTab / renderActiesTab) al draait voordat dat blok is bereikt.
    const INJURY_SEVERITIES = ['licht', 'matig', 'ernstig'];
    const INJURY_STATUSES = ['actief', 'herstellend', 'hersteld'];
    // Vervang dit door je eigen VAPID public key (gegenereerd met: vapid --gen && vapid --applicationServerKey)
    const VAPID_PUBLIC_KEY = 'BEHjNc5ry_se3HeXSfl2QIWOtkZIT69L5rVDNHxqNzZrL0hZ0az8InWjZw8g2IZhLT9_B28XaSWdrL64TcQKnHM';
    let currentGistId = '';

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
      if (diff === 0) return 'vandaag';
      if (diff === 1) return 'morgen';
      if (diff === 2) return 'overmorgen';
      if (diff === -1) return 'gisteren';
      if (diff > 1) return `over ${diff} dagen`;
      return `${Math.abs(diff)} dagen geleden`;
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

    // ── Maandtelling lessen (abonnement 13x per maand) ──────────
    // Bouwt per ingeschreven les een volgnummer binnen de kalendermaand,
    // zodat elke reservering toont de hoeveelste les van die maand het is.
    // Geplande maar nog niet ingeschreven slots tellen door in dezelfde reeks,
    // zodat je vooruit ziet waar je die maand op uitkomt. Overgeslagen slots
    // (exclusions) tellen niet mee. Late afmeldingen (< 1 uur van tevoren,
    // handmatig gemarkeerd met late_cancel) kosten wél een credit en tellen mee.
    function buildMonthlyClassIndex(signedUp, pendingSlots = [], cancelled = []) {
      monthlyClassIndex = {};
      monthlyClassTotals = {};
      monthlyProjectedTotals = {};
      monthlyLateCancelTotals = {};
      const entries = [
        ...signedUp
          .filter(e => e.date)
          .map(e => ({ date: e.date, time: e.time || '', key: e.event_id || `${e.date}_${e.time}`, pending: false })),
        ...cancelled
          .filter(e => e.date && e.late_cancel)
          .map(e => ({ date: e.date, time: e.time || '', key: e.event_id || `${e.date}_${e.time}`, pending: false, late: true })),
        ...pendingSlots
          .filter(sl => sl.date && !exclusions[sl.key])
          .map(sl => ({ date: sl.date, time: sl.time || '', key: sl.key, pending: true })),
      ].sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));

      for (const e of entries) {
        const month = e.date.slice(0, 7);
        monthlyProjectedTotals[month] = (monthlyProjectedTotals[month] || 0) + 1;
        if (!e.pending) monthlyClassTotals[month] = (monthlyClassTotals[month] || 0) + 1;
        if (e.late) monthlyLateCancelTotals[month] = (monthlyLateCancelTotals[month] || 0) + 1;
        monthlyClassIndex[e.key] = { index: monthlyProjectedTotals[month], month, pending: e.pending, late: !!e.late };
      }
    }

    function monthCountFor(item) {
      return monthlyClassIndex[item.event_id || `${item.date}_${item.time}`] || null;
    }

    function renderMonthCountBadge(item) {
      const info = monthCountFor(item);
      if (!info) return '';
      let cls = 'month-count-badge';
      if (info.pending) cls += ' pending';
      if (info.index > MONTHLY_CLASS_QUOTA) cls += ' over';
      const monthLabel = MONTH_NL[parseInt(info.month.slice(5, 7), 10) - 1];
      if (info.late) cls += ' late';
      const title = info.pending
        ? `Wordt les ${info.index} van ${MONTHLY_CLASS_QUOTA} in ${monthLabel} als je je inschrijft`
        : info.late
          ? `Late afmelding — kost credit ${info.index} van ${MONTHLY_CLASS_QUOTA} in ${monthLabel}`
          : `Les ${info.index} van ${MONTHLY_CLASS_QUOTA} in ${monthLabel}`;
      return `<span class="${cls}" title="${title}">${info.index}/${MONTHLY_CLASS_QUOTA}</span>`;
    }

    // Samenvatting van het maandtegoed voor de huidige maand.
    const MONTH_NL_FULL = ['januari','februari','maart','april','mei','juni',
                           'juli','augustus','september','oktober','november','december'];
    function renderMonthQuotaSummary() {
      const now = new Date();
      const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      const used = monthlyClassTotals[month] || 0;
      const projected = monthlyProjectedTotals[month] || used;
      const planned = projected - used;
      const left = MONTHLY_CLASS_QUOTA - projected;
      const pct = Math.min(100, Math.round(used / MONTHLY_CLASS_QUOTA * 100));
      const pctProjected = Math.min(100, Math.round(projected / MONTHLY_CLASS_QUOTA * 100));
      const cls = projected > MONTHLY_CLASS_QUOTA ? 'over' : (projected === MONTHLY_CLASS_QUOTA ? 'full' : '');
      const outlook = left > 0
        ? `nog ${left} te gaan`
        : (left === 0 ? 'tegoed precies op' : `${-left} boven je abonnement`);
      const late = monthlyLateCancelTotals[month] || 0;
      const usedLabel = late > 0
        ? `${used - late} ingeschreven + ${late} late afmelding${late > 1 ? 'en' : ''}`
        : `${used} ingeschreven`;
      const note = planned > 0
        ? `${usedLabel} + ${planned} gepland → ${projected}/${MONTHLY_CLASS_QUOTA} · ${outlook}`
        : `${usedLabel} · ${outlook}`;
      return `<div class="month-quota ${cls}">
        <div class="month-quota-head">
          <span class="month-quota-title">Lessen ${MONTH_NL_FULL[now.getMonth()]}</span>
          <span class="month-quota-count">${projected}/${MONTHLY_CLASS_QUOTA}</span>
        </div>
        <div class="month-quota-track">
          <div class="month-quota-fill projected" style="width:${pctProjected}%"></div>
          <div class="month-quota-fill" style="width:${pct}%"></div>
        </div>
        <div class="month-quota-note">${note}</div>
      </div>`;
    }

    function renderCard(item, type, delay, wods) {
      const cancelled = type === 'cancelled';
      const _cap = classCapacity[`${item.date}_${item.time}`];
      const _coach = _cap && _cap.trainers && _cap.trainers[0] ? _cap.trainers[0].split(' ')[0] : '';
      const metaHtml = `<div class="card-meta">
        <span class="card-time">${item.time}</span>
        ${_coach ? `<span class="card-coach">· ${escapeHtml(_coach)}</span>` : ''}
        ${cancelled && !item.late_cancel ? '' : renderMonthCountBadge(item)}
        ${cancelled && item.late_cancel ? '<span class="late-cancel-label">Late afmelding · kost credit</span>' : ''}
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
          <button class="niet-gedaan-btn" id="late-${item.event_id}"
            onclick="toggleLateCancel('${item.event_id}',${item.late_cancel ? 'false' : 'true'},this)">
            ${item.late_cancel ? 'Geen late afmelding' : 'Late afmelding (kost credit)'}
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
