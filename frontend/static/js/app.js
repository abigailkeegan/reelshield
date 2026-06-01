let spoilerMode = false, debounce = null, currentTmdbId = null, selectedStar = null;
let currentMovie = null, currentWarningData = null;
const SEV  = {0:'None',1:'Mild',2:'Moderate',3:'Severe'};
const CATS = {
  violence_gore:'Violence & Gore', self_harm_suicide:'Self-Harm & Suicide',
  miscarriage_pregnancy_loss:'Miscarriage / Pregnancy Loss',
  sexual_content_nudity:'Sexual Content & Nudity', animal_abuse:'Animal Abuse',
  substances:'Substance Use', language:'Language',
  horror_intensity:'Horror / Intensity', flashing_lights:'Flashing Lights (Epilepsy Risk)'
};

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function announce(m){const r=document.getElementById('live');r.textContent='';setTimeout(()=>r.textContent=m,50);}

// ── Auth ──────────────────────────────────────────────────────
let currentUser = null;

async function checkAuth() {
  const res  = await fetch('/api/me');
  const data = await res.json();
  if (data.logged_in) {
    currentUser = data.username;
    showLoggedIn(data.username);
  }
}

function showLoggedIn(username) {
  document.getElementById('authStatus').innerHTML = `Logged in as <strong>${esc(username)}</strong>`;
  document.getElementById('authForm').style.display   = 'none';
  document.getElementById('authLogout').style.display = 'block';
  updateReviewForm();
  loadWatchlist();
  // Sync server-side sensitivities to local
  fetch('/api/profile/sensitivities').then(r=>r.json()).then(d=>{
    if (d.ok && d.sensitivities.length) {
      localSensitivities = d.sensitivities;
      localStorage.setItem('sensitivities', JSON.stringify(d.sensitivities));
    }
  });
}

function showLoggedOut() {
  currentUser = null;
  document.getElementById('authStatus').textContent   = 'Not logged in';
  document.getElementById('authForm').style.display   = 'flex';
  document.getElementById('authLogout').style.display = 'none';
  document.getElementById('watchlistSection').style.display = 'none';
  document.getElementById('wlBtn').style.display = 'none';
  updateReviewForm();
}

async function doLogin() {
  const username = document.getElementById('authUser').value.trim();
  const password = document.getElementById('authPass').value.trim();
  const msg      = document.getElementById('authMsg');
  if (!username || !password) { msg.textContent = 'Enter username and password.'; return; }
  const res  = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username, password})});
  const data = await res.json();
  if (data.ok) {
    currentUser = data.username;
    showLoggedIn(data.username);
    document.getElementById('authUser').value = '';
    document.getElementById('authPass').value = '';
    msg.textContent = '';
  } else {
    msg.textContent = data.error;
  }
}

async function doRegister() {
  const username = document.getElementById('authUser').value.trim();
  const password = document.getElementById('authPass').value.trim();
  const msg      = document.getElementById('authMsg');
  if (!username || !password) { msg.textContent = 'Enter username and password.'; return; }
  const res  = await fetch('/api/register', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username, password})});
  const data = await res.json();
  if (data.ok) {
    currentUser = data.username;
    showLoggedIn(data.username);
    document.getElementById('authUser').value = '';
    document.getElementById('authPass').value = '';
    msg.textContent = '';
  } else {
    msg.textContent = data.error;
  }
}

async function doLogout() {
  await fetch('/api/logout', {method:'POST'});
  showLoggedOut();
}

function updateReviewForm() {
  const inner = document.getElementById('reviewFormInner');
  const note  = document.getElementById('reviewLoginNote');
  if (currentUser) {
    inner.style.display = 'block';
    note.style.display  = 'none';
  } else {
    inner.style.display = 'none';
    note.style.display  = 'block';
  }
}

// ── Search ────────────────────────────────────────────────────
let pendingGenreNote = null;

document.getElementById('searchInput').addEventListener('input', e => {
  clearTimeout(debounce);
  const q        = e.target.value.trim();
  const genre_id = document.getElementById('genreSelect').value;
  if (q.length < 2) { document.getElementById('searchResults').innerHTML=''; document.getElementById('searchStatus').textContent=''; return; }
  document.getElementById('searchStatus').textContent = 'Searching...';
  const params = genre_id ? {query: q, genre_id} : {query: q};
  debounce = setTimeout(() => doSearch(params), 350);
});

function onGenreChange() {
  const genre_id = document.getElementById('genreSelect').value;
  const query    = document.getElementById('searchInput').value.trim();
  document.getElementById('searchResults').innerHTML = '';
  if (!genre_id) { document.getElementById('searchStatus').textContent = ''; return; }
  const label = document.getElementById('genreSelect').options[document.getElementById('genreSelect').selectedIndex].text;
  document.getElementById('searchStatus').textContent = query ? `Searching for "${query}" in ${label}...` : `Browsing ${label}...`;
  clearTimeout(debounce);
  const params = query ? {query, genre_id} : {genre_id};
  debounce = setTimeout(() => doSearch(params), 200);
}

async function doSearch(params) {
  const res  = await fetch('/api/search', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(params)});
  const data = await res.json();
  const results = data.results || data; // backwards compat if plain array
  pendingGenreNote = data.genre_note || null;
  document.getElementById('searchStatus').textContent = results.length ? `${results.length} result(s) found` : 'No results found';
  document.getElementById('searchResults').innerHTML = results.map(r => `
    <button class="rcard" onclick="loadMovie(${r.tmdb_id})" aria-label="Load ${esc(r.title)} (${r.year||'Unknown year'})">
      ${r.poster ? `<img src="${esc(r.poster)}" alt="${esc(r.title)} poster" loading="lazy">` : '<div class="no-poster" aria-hidden="true">No poster</div>'}
      <h3>${esc(r.title)}</h3><small>${r.year||'N/A'}</small>
    </button>`).join('');
}

// ── Load movie ────────────────────────────────────────────────
async function loadMovie(id) {
  currentTmdbId = id;
  document.getElementById('searchResults').innerHTML = '';
  document.getElementById('searchInput').value       = '';
  document.getElementById('searchStatus').textContent= '';
  document.getElementById('epiBar').style.display    = 'none';
  document.getElementById('main').classList.remove('visible');
  document.getElementById('recoSection').style.display   = 'none';
  document.getElementById('reviewSection').style.display = 'none';
  document.getElementById('twinsSection').style.display  = 'none';
  document.getElementById('loader').style.display = 'block';
  announce('Loading movie and generating content warnings, please wait.');
  const msgs = ['Fetching movie data...','Looking up cast & genres...','Asking Gemini AI...','Almost there...'];
  let mi = 0;
  const msgTimer = setInterval(() => {
    mi = (mi + 1) % msgs.length;
    document.getElementById('loaderMsg').textContent = msgs[mi];
  }, 3000);
  try {
    const res  = await fetch('/api/load_movie', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({tmdb_id:id, spoiler_mode:spoilerMode})});
    const data = await res.json();
    clearInterval(msgTimer);
    document.getElementById('loader').style.display = 'none';
    renderAll(data.movie, data.warnings, data.mpa_prediction || null);
    checkWatchlistStatus(id);
    loadReviews(id);
    loadExternalReviews(id);
    loadContentTwins(id);
    document.getElementById('recoSection').style.display   = 'block';
    document.getElementById('reviewSection').style.display = 'block';
    document.getElementById('recoResults').innerHTML = '';
    document.getElementById('recoMsg').textContent   = '';
    document.getElementById('avoidSelect').value     = '';
    updateReviewForm();
    const gnEl = document.getElementById('genreNote');
    if (pendingGenreNote) {
      gnEl.textContent = pendingGenreNote;
      gnEl.style.display = 'block';
      pendingGenreNote = null;
    } else {
      gnEl.style.display = 'none';
    }
  } catch(e) {
    clearInterval(msgTimer);
    document.getElementById('loader').style.display = 'none';
    announce('Error loading movie. Please try again.');
  }
}

function renderAll(movie, wd, mpaPrediction) {
  currentMovie       = movie;
  currentWarningData = wd;
  const tmdbGenres = movie.genres || [];
  const genres = tmdbGenres.map(g =>
    `<span class="badge">${esc(g)}</span>`
  ).join('');
  const cert   = movie.us_certification ? `<span class="badge">${esc(movie.us_certification)}</span>` : '';
  const rt     = movie.runtime_min ? `<span class="badge">${movie.runtime_min} min</span>` : '';
  let mpaBadge = '', mpaNote = '';
  if (mpaPrediction) {
    const pct = Math.round((mpaPrediction.confidence || 0) * 100);
    const BUCKET_TO_MPA = { family: 'G/PG', teen: 'PG-13', adult: 'R/NC-17' };
    const mpaEquiv = BUCKET_TO_MPA[mpaPrediction.label] || mpaPrediction.label;
    if (mpaPrediction.disagrees) {
      const title = `ML classifier predicts a ${mpaEquiv} content profile · ${pct}% confidence · disagrees with TMDB rating ${movie.us_certification || ''}`;
      mpaBadge = `<span class="badge badge-mpa-warn" title="${esc(title)}">&#9888;&#65039; Classifier predicts ${esc(mpaEquiv)} &middot; ${pct}%</span>`;
      mpaNote = `<p class="mpa-warn-note">Our ML classifier estimates this film's content profile better matches <strong>${esc(mpaEquiv)}</strong> than its official <strong>${esc(movie.us_certification || '')}</strong> rating.</p>`;
    } else {
      const title = `ML classifier predicts a ${mpaEquiv} content profile · ${pct}% confidence · TMDB had no rating for this film`;
      mpaBadge = `<span class="badge badge-predicted" title="${esc(title)}">&#10022; Predicted: ${esc(mpaEquiv)} &middot; ${pct}%</span>`;
      mpaNote = `<p class="predicted-genres-note">&#10022; Our ML classifier predicts a <strong>${esc(mpaEquiv)}</strong> content profile (TMDB had no MPA rating for this film).</p>`;
    }
  }
  document.getElementById('movieMeta').innerHTML =
    `<p class="movie-title">${esc(movie.title)} (${movie.year||'?'})</p>`+
    `<div class="meta-row">${cert}${mpaBadge}${rt}${genres}</div>`+
    mpaNote +
    (movie.overview ? `<p class="overview-blurb">${esc(movie.overview)}</p>` : '');
  document.getElementById('wpTitle').style.display = 'block';

  // Pick the right block. spoiler_full only exists on newly-generated rows
  // (post-spoiler-toggle-fix); old cached rows fall back to spoiler_free.
  const block = (spoilerMode && wd && wd.spoiler_full) ? wd.spoiler_full : (wd && wd.spoiler_free);
  const warnings = block || {};
  const ORDER    = ['flashing_lights','violence_gore','self_harm_suicide',
    'miscarriage_pregnancy_loss','animal_abuse','sexual_content_nudity','horror_intensity','substances','language'];
  const sorted   = ORDER
    .map(c => [c, warnings[c] || {severity:0, confidence:0, notes:''}])
    .sort((a,b) => { if(a[0]==='flashing_lights') return -1; if(b[0]==='flashing_lights') return 1; return b[1].severity - a[1].severity; });

  document.getElementById('wList').innerHTML = sorted.map(([cat, d]) => {
    const sev  = d.severity   || 0;
    const conf = d.confidence !== undefined ? d.confidence : 0;
    const label = CATS[cat] || cat;
    const icon  = cat === 'flashing_lights' && sev > 0 ? '&#9888;&#65039; ' : '';
    let confTxt, confCls;
    if (conf >= 0.95 && sev > 0)  { confTxt = '\u2714 Confirmed';        confCls = 'conf-ok'; }
    else if (conf >= 0.95)         { confTxt = '\u2714 Confirmed absent'; confCls = 'conf-ok'; }
    else                           { confTxt = `~${Math.round(conf*100)}% confidence`; confCls = ''; }
    const aria = `${label}: ${SEV[sev]}. ${confTxt}.${d.notes?' '+d.notes:''}`;
    return `<div class="witem s${sev}" role="listitem" aria-label="${esc(aria)}">` +
      `<div class="w-head"><span class="w-lbl">${icon}${esc(label)}</span><span class="w-badge">${SEV[sev]}</span></div>`+
      `<div class="conf ${confCls}">${confTxt}</div>`+
      (d.notes ? `<p class="w-notes">${esc(d.notes)}</p>` : '')+
      `<div class="fb-row">`+
      `<button class="fb-btn" onclick="submitFeedback('warning','up','${cat}',null,this)" aria-label="Mark ${esc(label)} warning as accurate">&#128077;</button>`+
      `<button class="fb-btn" onclick="submitFeedback('warning','down','${cat}',null,this)" aria-label="Mark ${esc(label)} warning as inaccurate">&#128078;</button>`+
      `</div>`+
      '</div>';
  }).join('');

  const fl = warnings.flashing_lights;
  if (fl && fl.severity > 0) {
    document.getElementById('epiBar').style.display = 'block';
    document.getElementById('epiNotes').textContent = fl.notes || '';
    announce('Epilepsy warning: this film contains flashing lights.');
  }

  document.getElementById('main').classList.add('visible');
  document.getElementById('chatBox').innerHTML = '<p style="color:var(--muted);font-size:.88rem;">Ask me anything about this film.</p>';
  announce(`Loaded ${movie.title}. Content warnings are displayed.`);
}

// ── Recommendations ───────────────────────────────────────────
async function fetchRecommendations() {
  const avoid = document.getElementById('avoidSelect').value;
  const msg   = document.getElementById('recoMsg');
  const box   = document.getElementById('recoResults');
  if (!avoid)           { msg.textContent = 'Please select a warning category first.'; return; }
  if (!currentTmdbId)   { msg.textContent = 'Load a movie first.'; return; }
  msg.textContent = 'Searching for similar movies...';
  box.innerHTML   = '';
  try {
    const res  = await fetch(`/api/recommendations/${currentTmdbId}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({avoid_category: avoid})
    });
    const data = await res.json();
    if (!data.ok) { msg.textContent = data.error; return; }
    if (!data.recommendations.length) {
      msg.textContent = 'No safe recommendations found for this selection.';
      return;
    }
    const catLabel = document.getElementById('avoidSelect').options[document.getElementById('avoidSelect').selectedIndex].text;
    msg.textContent = `${data.recommendations.length} similar movie(s) without ${catLabel}:`;
    box.innerHTML = data.recommendations.map(r => `
      <button class="rcard" onclick="loadMovie(${r.tmdb_id})" aria-label="Load ${esc(r.title)}">
        ${r.poster ? `<img src="${esc(r.poster)}" alt="${esc(r.title)} poster" loading="lazy">` : '<div class="no-poster">No poster</div>'}
        <h3>${esc(r.title)}</h3><small>${r.year||'N/A'}</small>
      </button>`).join('');
  } catch(e) {
    msg.textContent = 'Error fetching recommendations.';
  }
}

// ── External Reviews ──────────────────────────────────────────
// ── Content twins (K-Means cluster neighbors) ────────────────
async function loadContentTwins(tmdb_id) {
  const section = document.getElementById('twinsSection');
  try {
    const res  = await fetch(`/api/content_twins/${tmdb_id}`);
    const data = await res.json();
    if (!data.ok || !data.twins || !data.twins.length) {
      section.style.display = 'none';
      return;
    }
    const cname = data.cluster_name ? esc(data.cluster_name) : 'this content profile';
    document.getElementById('twinsHint').innerHTML =
      `Other films in the <strong>${cname}</strong> cluster, ranked by similarity of their warning profile. ` +
      `<span style="color:var(--muted)">Powered by a K-Means model trained on the cached library.</span>`;
    document.getElementById('twinsGrid').innerHTML = data.twins.map(t => `
      <button class="twin-card" role="listitem" onclick="loadMovie(${t.tmdb_id})" aria-label="Load ${esc(t.title)}">
        ${t.poster ? `<img src="${esc(t.poster)}" alt="${esc(t.title)} poster" loading="lazy">` : '<div class="no-poster-wide">No poster</div>'}
        <div class="twin-body">
          <p class="twin-title">${esc(t.title)}</p>
          <p class="twin-year">${esc(t.year || '')}</p>
          <p class="twin-dist">Δ ${t.distance.toFixed(2)}</p>
        </div>
      </button>`).join('');
    section.style.display = 'block';
  } catch (e) {
    section.style.display = 'none';
  }
}

async function loadExternalReviews(tmdb_id) {
  try {
    const res  = await fetch(`/api/external_reviews/${tmdb_id}`);
    const data = await res.json();

    // Ratings chips (IMDb, Rotten Tomatoes, Metacritic)
    const ratingsWrap = document.getElementById('extRatingsWrap');
    const ratingsBox  = document.getElementById('extRatings');
    if (data.ratings && data.ratings.length) {
      ratingsBox.innerHTML = data.ratings.map(r => `
        <div class="rating-chip">
          <div class="rc-source">${esc(r.source)}</div>
          <div class="rc-value">${esc(r.value)}</div>
        </div>`).join('');
      ratingsWrap.style.display = 'block';
    } else {
      ratingsWrap.style.display = 'none';
    }

    // Written critic reviews from TMDB
    const extWrap = document.getElementById('extReviewsWrap');
    const extList = document.getElementById('extReviewsList');
    if (data.reviews && data.reviews.length) {
      extList.innerHTML = data.reviews.map(r => {
        const stars = r.rating ? `${r.rating}/10` : '';
        return `<div class="ext-review-card">
          <div class="er-head">
            <span class="er-author">${esc(r.author)}</span>
            <span class="er-source">${esc(r.source)}</span>
            ${stars ? `<span class="er-rating">&#9733; ${esc(stars)}</span>` : ''}
          </div>
          <p class="er-text">${esc(r.excerpt)}</p>
          ${r.url ? `<a class="er-link" href="${esc(r.url)}" target="_blank" rel="noopener">Read full review</a>` : ''}
        </div>`;
      }).join('');
      extWrap.style.display = 'block';
    } else {
      extWrap.style.display = 'none';
    }
  } catch(e) {
    console.error('External reviews error:', e);
  }
}

// ── Reviews ───────────────────────────────────────────────────
function setStar(v) {
  selectedStar = v;
  document.querySelectorAll('.star').forEach(s => {
    s.classList.toggle('active', parseInt(s.dataset.v) <= v);
  });
}

async function submitReview() {
  const msg  = document.getElementById('reviewMsg');
  const text = document.getElementById('reviewTA').value.trim();
  if (!text) { msg.className='err'; msg.textContent='Review cannot be empty.'; return; }
  if (!currentTmdbId) return;
  const res  = await fetch(`/api/reviews/${currentTmdbId}`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({review_text: text, rating: selectedStar})
  });
  const data = await res.json();
  if (data.ok) {
    msg.className = 'ok'; msg.textContent = 'Review posted!';
    document.getElementById('reviewTA').value = '';
    selectedStar = null;
    document.querySelectorAll('.star').forEach(s => s.classList.remove('active'));
    loadReviews(currentTmdbId);
  } else {
    msg.className = 'err'; msg.textContent = data.error;
  }
}

async function loadReviews(tmdb_id) {
  const res     = await fetch(`/api/reviews/${tmdb_id}`);
  const reviews = await res.json();
  const list    = document.getElementById('reviewList');
  if (!reviews.length) {
    list.innerHTML = '<p class="no-reviews">No reviews yet. Be the first!</p>';
    return;
  }
  list.innerHTML = reviews.map(r => {
    const stars = r.rating ? '&#9733;'.repeat(r.rating) + '&#9734;'.repeat(5 - r.rating) : '';
    const date  = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';
    return `<div class="review-card">
      <div class="rv-head">
        <span class="rv-user">${esc(r.username)}</span>
        <span class="rv-stars">${stars}</span>
        <span class="rv-date">${date}</span>
      </div>
      <p class="rv-text">${esc(r.review_text)}</p>
    </div>`;
  }).join('');
}

// ── Spoiler toggle ────────────────────────────────────────────
function toggleSpoiler() {
  spoilerMode = !spoilerMode;
  document.getElementById('spBtn').setAttribute('aria-checked', String(spoilerMode));
  document.getElementById('spLbl').innerHTML = `Spoiler mode: <strong>${spoilerMode?'On':'Off'}</strong>`;
  announce(`Spoiler mode ${spoilerMode?'enabled':'disabled'}.`);
  // Re-render currently-loaded warnings so notes flip between blocks.
  // Chat replies pick up the new mode on the next message — they aren't re-fetched.
  if (currentMovie && currentWarningData) {
    renderAll(currentMovie, currentWarningData);
  }
}

// ── Feedback ──────────────────────────────────────────────────
async function submitFeedback(type, rating, category, chatText, btn) {
  if (!currentTmdbId) return;
  const row = btn.closest('.fb-row');
  if (row) row.querySelectorAll('.fb-btn').forEach(b => b.disabled = true);
  try {
    await fetch('/api/feedback', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({movie_id: currentTmdbId, category, feedback_type: type, rating, chat_message_text: chatText})
    });
    btn.classList.add(rating === 'up' ? 'voted-up' : 'voted-down');
  } catch { if (row) row.querySelectorAll('.fb-btn').forEach(b => b.disabled = false); }
}

// ── Chat ──────────────────────────────────────────────────────
async function sendMsg() {
  const inp = document.getElementById('chatIn');
  const msg = inp.value.trim();
  if (!msg) return;
  const box = document.getElementById('chatBox');
  const btn = document.getElementById('sendBtn');
  btn.disabled = true; inp.disabled = true;
  const u = document.createElement('div');
  u.className = 'msg u'; u.innerHTML = `<div class="msg-lbl">You</div>${esc(msg)}`;
  box.appendChild(u); inp.value = ''; box.scrollTop = 9999;
  try {
    const res  = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:msg, spoiler_mode:spoilerMode})});
    const data = await res.json();
    const a = document.createElement('div');
    a.className = 'msg a';
    const responseText = data.response;
    a.innerHTML = `<div class="msg-lbl">AI</div>${esc(responseText)}`;
    const fbRow = document.createElement('div'); fbRow.className = 'fb-row';
    ['up','down'].forEach(r => {
      const b = document.createElement('button');
      b.className = 'fb-btn'; b.textContent = r==='up'?'👍':'👎';
      b.setAttribute('aria-label', r==='up'?'Rate response helpful':'Rate response not helpful');
      b.addEventListener('click', () => submitFeedback('chat', r, null, responseText, b));
      fbRow.appendChild(b);
    });
    a.appendChild(fbRow);
    box.appendChild(a); box.scrollTop = 9999;
    announce('AI response received.');
  } catch { box.insertAdjacentHTML('beforeend','<div class="msg a">Error. Try again.</div>'); }
  btn.disabled = false; inp.disabled = false; inp.focus();
}
document.getElementById('chatIn').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
});

// ── Modal focus management ────────────────────────────────────
let _modalReturnFocus = null;
let _modalTrapHandler = null;

function _focusables(modal) {
  return modal.querySelectorAll(
    'button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
  );
}

function _openModal(modal, initialFocusEl) {
  _modalReturnFocus = document.activeElement;
  modal.classList.add('open');
  (initialFocusEl || _focusables(modal)[0] || modal).focus();
  _modalTrapHandler = e => {
    if (e.key !== 'Tab') return;
    const f = _focusables(modal);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
    else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
  };
  modal.addEventListener('keydown', _modalTrapHandler);
}

function _closeModal(modal) {
  modal.classList.remove('open');
  if (_modalTrapHandler) { modal.removeEventListener('keydown', _modalTrapHandler); _modalTrapHandler = null; }
  if (_modalReturnFocus && typeof _modalReturnFocus.focus === 'function') _modalReturnFocus.focus();
  _modalReturnFocus = null;
}

// ── Prompt editor ─────────────────────────────────────────────
function _setPromptEditable(editable) {
  const show = (id, on) => { const el = document.getElementById(id); if (el) el.hidden = !on; };
  // Locked notice only when editing is disabled; editor controls only when enabled.
  show('promptLocked', !editable);
  show('promptHint', editable);
  show('promptTokenLabel', editable);
  show('promptToken', editable);
  show('promptSaveBtn', editable);
  show('promptResetBtn', editable);
  document.getElementById('promptTA').readOnly = !editable;
}
async function openPromptEditor() {
  const res  = await fetch('/api/prompt');
  const data = await res.json();
  document.getElementById('promptTA').value      = data.prompt;
  document.getElementById('promptMsg').textContent = '';
  _setPromptEditable(data.editable !== false);
  _openModal(document.getElementById('promptModal'), document.getElementById('promptTA'));
}
function closePromptEditor() { _closeModal(document.getElementById('promptModal')); }
async function savePrompt() {
  const prompt = document.getElementById('promptTA').value;
  const token  = document.getElementById('promptToken').value;
  const res    = await fetch('/api/prompt', {method:'POST', headers:{'Content-Type':'application/json', 'X-Admin-Token':token}, body:JSON.stringify({prompt})});
  const data   = await res.json();
  const msg    = document.getElementById('promptMsg');
  if (data.ok) { msg.className='modal-msg ok'; msg.textContent=data.message; setTimeout(closePromptEditor, 1500); }
  else          { msg.className='modal-msg err'; msg.textContent=data.error; }
}
async function resetPrompt() {
  const token = document.getElementById('promptToken').value;
  const res   = await fetch('/api/prompt/reset', {method:'POST', headers:{'X-Admin-Token':token}});
  const data  = await res.json();
  const msg   = document.getElementById('promptMsg');
  if (data.ok) { document.getElementById('promptTA').value = data.prompt; msg.className='modal-msg ok'; msg.textContent='Reset to default prompt.'; }
  else          { msg.className='modal-msg err'; msg.textContent=data.error; }
}
document.getElementById('promptModal').addEventListener('click', e => {
  if (e.target === document.getElementById('promptModal')) closePromptEditor();
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const pm = document.getElementById('promptModal');
  const sm = document.getElementById('sensitivityModal');
  if (pm.classList.contains('open')) closePromptEditor();
  else if (sm.classList.contains('open')) closeSensitivityEditor();
});

// ── Discover (merged mood + warning avoidance) ───────────────
let selectedMoodInput = null;

// Build avoid checkboxes
// Tracks avoid categories in the exact order the user checked them
let avoidSelectionOrder = [];

(function buildAvoidGrid() {
  const grid = document.getElementById('avoidGrid');
  grid.innerHTML = Object.entries(CATS).map(([k, v]) =>
    `<label class="avoid-item">
      <input type="checkbox" class="avoid-chk" value="${k}" onchange="enforceAvoidLimit(this)">
      ${esc(v)}
    </label>`).join('');
})();

function enforceAvoidLimit(checkbox) {
  if (checkbox) {
    const val = checkbox.value;
    if (checkbox.checked) {
      if (!avoidSelectionOrder.includes(val)) avoidSelectionOrder.push(val);
    } else {
      avoidSelectionOrder = avoidSelectionOrder.filter(v => v !== val);
    }
  }
  const checked = document.querySelectorAll('.avoid-chk:checked');
  const msg     = document.getElementById('avoidLimitMsg');
  if (checked.length >= 3) {
    document.querySelectorAll('.avoid-chk:not(:checked)').forEach(c => c.disabled = true);
    msg.textContent = 'Maximum 3 selected. First picked = highest priority.';
  } else {
    document.querySelectorAll('.avoid-chk').forEach(c => c.disabled = false);
    msg.textContent = '';
  }
}

function selectMood(btn) {
  const wasSelected = btn.classList.contains('selected');
  document.querySelectorAll('.mood-option').forEach(b => {
    b.classList.remove('selected');
    b.setAttribute('aria-pressed', 'false');
  });
  // Picking a preset clears any custom text the user typed.
  const customInput = document.getElementById('moodCustom');
  if (customInput) customInput.value = '';
  if (wasSelected) {
    selectedMoodInput = null;
    return;
  }
  btn.classList.add('selected');
  btn.setAttribute('aria-pressed', 'true');
  selectedMoodInput = btn.dataset.mood;
}

function onMoodCustomInput() {
  // Typing a custom mood clears any selected preset chip.
  document.querySelectorAll('.mood-option').forEach(b => {
    b.classList.remove('selected');
    b.setAttribute('aria-pressed', 'false');
  });
  selectedMoodInput = null;
}

function renderMoodProfile(p) {
  if (!p) { document.getElementById('moodProfileBox').style.display = 'none'; return; }
  document.getElementById('moodSummaryText').textContent = p.mood_summary || '';
  const ceilingLabels = {low:'Low-key',medium:'Some depth OK',high:'Ready for intensity',intense:'Full emotional range'};
  document.getElementById('moodCeilingText').textContent =
    `Emotional ceiling: ${ceilingLabels[p.emotional_ceiling] || p.emotional_ceiling}`;
  document.getElementById('moodTonesGood').innerHTML =
    (p.recommended_tones || []).map(t => `<span class="mp-tone-good">${esc(t)}</span>`).join('');
  document.getElementById('moodTonesBad').innerHTML =
    (p.avoid_tones || []).map(t => `<span class="mp-tone-bad">${esc(t)}</span>`).join('');
  document.getElementById('moodProfileBox').style.display = 'block';
}

async function discoverMovies() {
  // avoidSelectionOrder preserves the exact order the user checked each box
  const avoid_categories = avoidSelectionOrder.filter(v =>
    document.querySelector(`.avoid-chk[value="${v}"]:checked`)
  );
  const msg  = document.getElementById('discoverMsg');
  const grid = document.getElementById('discoverGrid');
  const btn  = document.getElementById('discoverBtn');
  const customMood = (document.getElementById('moodCustom')?.value || '').trim();
  const moodToSend = customMood || selectedMoodInput || '';
  msg.textContent = moodToSend
    ? 'Interpreting your mood and ranking by mood → selection order…'
    : 'Ranking movies by your selection order…';
  grid.innerHTML = '';
  btn.disabled   = true;
  document.getElementById('moodProfileBox').style.display = 'none';
  try {
    const res  = await fetch('/api/discover', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        mood_input:               moodToSend,
        avoid_categories:         avoid_categories,
        avoid_categories_ordered: avoid_categories,   // selection-order array used by backend ranking
        sensitivities:            localSensitivities
      })
    });
    const data = await res.json();
    if (!data.ok) { msg.textContent = data.error; return; }
    if (data.mood_profile) renderMoodProfile(data.mood_profile);
    if (!data.recommendations.length) {
      msg.textContent = 'No matches found. Try loading more movies first.';
      return;
    }
    const hasMood = !!moodToSend;
    msg.textContent = `${data.recommendations.length} movie(s) found:`;
    grid.innerHTML = data.recommendations.map(r => `
      <div class="mood-rec-card" role="listitem">
        ${r.poster ? `<img src="${esc(r.poster)}" alt="${esc(r.title)} poster" loading="lazy">` : '<div class="no-poster-wide">No poster</div>'}
        <div class="mood-rec-body">
          <div class="mr-scores">
            <span class="mr-score-chip mr-final">&#9733; ${typeof r.final_score==='number'?r.final_score.toFixed(1):r.final_score||'?'}</span>
            <span class="mr-score-chip mr-safety">Safe ${r.safety_score||'?'}</span>
            ${hasMood && r.mood_score!=null ? `<span class="mr-score-chip mr-mood-s">Mood ${r.mood_score}</span>` : ''}
          </div>
          <p class="mr-title">${esc(r.title)}</p>
          ${r.mood_match_reason ? `<p class="mr-match">${esc(r.mood_match_reason)}</p>` : ''}
          ${r.safety_note ? `<p class="mr-safe">&#10003; ${esc(r.safety_note)}</p>` : ''}
          ${r.watch_confidence ? `<p class="mr-confidence">${esc(r.watch_confidence)}</p>` : ''}
          <button class="btn btn-sm btn-ghost mr-load" onclick="loadMovie(${r.tmdb_id})">View Full Warnings</button>
        </div>
      </div>`).join('');
  } catch(e) {
    msg.textContent = 'Error fetching recommendations.';
  } finally {
    btn.disabled = false;
  }
}

// ── Group Watch ───────────────────────────────────────────────
let groupMembers  = [];
let mergedProfile = null;

(function buildMemberSensGrid() {
  const grid = document.getElementById('memberSensGrid');
  grid.innerHTML = Object.entries(CATS).map(([k, v]) =>
    `<label class="member-sens-item">
      <input type="checkbox" class="msens" value="${k}">
      ${esc(v)}
    </label>`).join('');
})();

function addMember() {
  const name = document.getElementById('memberName').value.trim();
  const msg  = document.getElementById('addMemberMsg');
  msg.textContent = '';
  if (!name) { msg.textContent = 'Enter a name for this member.'; return; }
  const sens = [...document.querySelectorAll('.msens:checked')].map(i => i.value);
  groupMembers.push({name, sensitivities: sens});
  document.getElementById('memberName').value = '';
  document.querySelectorAll('.msens').forEach(i => i.checked = false);
  renderMemberList();
  document.getElementById('mergeBtn').disabled     = groupMembers.length < 1;
  document.getElementById('groupRecBtn').disabled  = true;
  document.getElementById('mergedProfile').style.display = 'none';
  mergedProfile = null;
}

function removeMember(idx) {
  groupMembers.splice(idx, 1);
  renderMemberList();
  document.getElementById('mergeBtn').disabled    = groupMembers.length < 1;
  document.getElementById('groupRecBtn').disabled = true;
  document.getElementById('mergedProfile').style.display = 'none';
  mergedProfile = null;
}

function renderMemberList() {
  const list = document.getElementById('memberList');
  if (!groupMembers.length) { list.innerHTML = '<p style="font-size:.83rem;color:var(--muted);font-style:italic">No members yet.</p>'; return; }
  list.innerHTML = groupMembers.map((m, i) => `
    <div class="member-card">
      <div class="mc-info">
        <p class="mc-name">${esc(m.name)}</p>
        <p class="mc-sens">${m.sensitivities.length ? m.sensitivities.map(s=>esc(CATS[s]||s)).join(', ') : 'No specific sensitivities'}</p>
      </div>
      <button class="mc-remove" onclick="removeMember(${i})" aria-label="Remove ${esc(m.name)}">✕</button>
    </div>`).join('');
}

async function mergeGroupProfiles() {
  const btn = document.getElementById('mergeBtn');
  const msg = document.getElementById('mergeMsg');
  msg.textContent = '';
  btn.disabled = true; btn.textContent = 'Merging...';
  try {
    const res  = await fetch('/api/group/merge', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({members: groupMembers})
    });
    const data = await res.json();
    if (!data.ok) { msg.textContent = data.error || 'Could not merge profiles.'; return; }
    mergedProfile = data.merged;
    renderMergedProfile(data.merged);
    document.getElementById('groupRecBtn').disabled = false;
  } catch(e) {
    msg.textContent = 'Error merging profiles.';
  } finally {
    btn.disabled = false; btn.textContent = '⚙ Merge Profiles';
  }
}

function renderMergedProfile(m) {
  document.getElementById('mpSummary').textContent = m.group_summary || '';
  document.getElementById('mpTags').innerHTML = (m.merged_sensitivities || []).map(s => {
    const hp  = (m.high_priority || []).includes(s);
    const lbl = CATS[s] || s;
    return `<span class="mp-tag ${hp ? 'mp-tag-high' : 'mp-tag-normal'}">${esc(lbl)}${hp?' ★':''}</span>`;
  }).join('');
  document.getElementById('mpAvoid').innerHTML = (m.avoid_genres || []).map(g =>
    `<span class="mp-avoid">${esc(g)}</span>`).join('');
  document.getElementById('mpReco').innerHTML = (m.recommended_genres || []).map(g =>
    `<span class="mp-reco">${esc(g)}</span>`).join('');
  document.getElementById('mergedProfile').style.display = 'block';
}

async function findGroupMovies() {
  const msg  = document.getElementById('groupRecMsg');
  if (!mergedProfile) { msg.textContent = 'Merge profiles first.'; return; }
  const mood = document.getElementById('moodSelect').value;
  const grid     = document.getElementById('groupRecGrid');
  const btn      = document.getElementById('groupRecBtn');
  msg.textContent = 'Searching for group-safe movies...';
  grid.innerHTML  = '';
  btn.disabled    = true;
  try {
    const res  = await fetch('/api/group/recommend', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        merged_profile: mergedProfile,
        mood,
        members: groupMembers   // ordered list used for group-priority weighting
      })
    });
    const data = await res.json();
    if (!data.ok) { msg.textContent = data.error; return; }
    if (!data.recommendations.length) { msg.textContent = 'No group-safe movies found. Try loading more movies first.'; return; }
    msg.textContent = `${data.recommendations.length} movie(s) safe for everyone in the group:`;
    grid.innerHTML = data.recommendations.map(r => `
      <div class="group-rec-card" role="listitem">
        ${r.poster ? `<img src="${esc(r.poster)}" alt="${esc(r.title)} poster" loading="lazy">` : '<div class="no-poster-wide">No poster</div>'}
        <div class="group-rec-body">
          <span class="gr-score">${r.group_score}/100</span>
          <p class="gr-title">${esc(r.title)}</p>
          <p class="gr-vibe">${esc(r.vibe||'')}</p>
          <p class="gr-safe">&#10003; ${esc(r.why_safe||'')}</p>
          ${r.one_concern ? `<p class="gr-concern">&#9888; ${esc(r.one_concern)}</p>` : ''}
          <p class="gr-conf conf-${r.confidence||'medium'}">Confidence: ${esc(r.confidence||'medium')}</p>
          <button class="btn btn-sm btn-ghost gr-load" onclick="loadMovie(${r.tmdb_id})">View Full Warnings</button>
        </div>
      </div>`).join('');
  } catch(e) {
    msg.textContent = 'Error fetching recommendations.';
  } finally {
    btn.disabled = false;
  }
}

// ── Sensitivity Profile ───────────────────────────────────────
const SENS_LABELS = {
  violence_gore:'Violence & Gore', self_harm_suicide:'Self-Harm & Suicide',
  miscarriage_pregnancy_loss:'Miscarriage / Pregnancy Loss',
  sexual_content_nudity:'Sexual Content & Nudity', animal_abuse:'Animal Abuse',
  substances:'Substance Use', language:'Language',
  horror_intensity:'Horror / Intensity', flashing_lights:'Flashing Lights'
};
let localSensitivities = JSON.parse(localStorage.getItem('sensitivities') || '[]');

function openSensitivityEditor() {
  const grid = document.getElementById('sensGrid');
  grid.innerHTML = Object.entries(SENS_LABELS).map(([k, v]) => `
    <label class="sens-item">
      <input type="checkbox" value="${k}" ${localSensitivities.includes(k) ? 'checked' : ''}>
      ${esc(v)}
    </label>`).join('');
  document.getElementById('sensMsg').textContent = '';
  const modal = document.getElementById('sensitivityModal');
  _openModal(modal, grid.querySelector('input') || modal.querySelector('.btn'));
}

function closeSensitivityEditor() {
  _closeModal(document.getElementById('sensitivityModal'));
}

async function saveSensitivities() {
  const checked = [...document.querySelectorAll('#sensGrid input:checked')].map(i => i.value);
  localSensitivities = checked;
  localStorage.setItem('sensitivities', JSON.stringify(checked));
  const msg = document.getElementById('sensMsg');
  if (currentUser) {
    const res  = await fetch('/api/profile/sensitivities', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sensitivities: checked})
    });
    const data = await res.json();
    if (data.ok) { msg.className='modal-msg ok'; msg.textContent='Profile saved!'; }
    else          { msg.className='modal-msg err'; msg.textContent=data.error; }
  } else {
    msg.className='modal-msg ok'; msg.textContent='Saved locally (log in to persist across devices).';
  }
  setTimeout(closeSensitivityEditor, 1200);
}

document.getElementById('sensitivityModal').addEventListener('click', e => {
  if (e.target === document.getElementById('sensitivityModal')) closeSensitivityEditor();
});

// ── Watchlist ─────────────────────────────────────────────────
async function checkWatchlistStatus(tmdb_id) {
  if (!currentUser) { document.getElementById('wlBtn').style.display='none'; return; }
  const res  = await fetch(`/api/watchlist/check/${tmdb_id}`);
  const data = await res.json();
  setWatchlistButtonState(data.in_watchlist);
}

function setWatchlistButtonState(inList) {
  const btn = document.getElementById('wlBtn');
  btn.style.display       = 'block';
  btn.dataset.inList      = inList ? '1' : '0';
  btn.textContent         = inList ? '★ Remove from Watchlist' : '☆ Add to Watchlist';
  btn.setAttribute('aria-label', inList ? 'Remove from watchlist' : 'Add to watchlist');
  btn.className           = inList ? 'btn btn-sm btn-danger' : 'btn btn-sm btn-ghost';
}

async function toggleWatchlist() {
  if (!currentUser || !currentTmdbId) return;
  const btn    = document.getElementById('wlBtn');
  const inList = btn.dataset.inList === '1';
  const method = inList ? 'DELETE' : 'POST';
  await fetch(`/api/watchlist/${currentTmdbId}`, {method});
  checkWatchlistStatus(currentTmdbId);
  loadWatchlist();
}

async function loadWatchlist() {
  if (!currentUser) { document.getElementById('watchlistSection').style.display='none'; return; }
  const res  = await fetch('/api/watchlist');
  const data = await res.json();
  if (!data.ok || !data.watchlist.length) {
    document.getElementById('watchlistSection').style.display = data.ok ? 'none' : 'none';
    return;
  }
  document.getElementById('watchlistSection').style.display = 'block';
  renderWatchlistGrid(data.watchlist.map(m => ({...m, watchlist_badge:null, one_liner:null})));
}

function badgeClass(badge) {
  if (!badge) return '';
  if (badge.includes('Safe'))   return 'wl-badge-safe';
  if (badge.includes('Mild'))   return 'wl-badge-mild';
  return 'wl-badge-strong';
}

function renderWatchlistGrid(movies, ranked=false) {
  const grid = document.getElementById('wlGrid');
  grid.innerHTML = movies.map((m, i) => `
    <div class="wl-card" role="listitem">
      ${ranked ? `<span class="wc-rank">${m.rank || i+1}</span>` : ''}
      <button class="wc-remove" onclick="removeFromWatchlist(${m.tmdb_id})" aria-label="Remove ${esc(m.title||'')}">✕</button>
      <button class="wl-card-btn" onclick="loadMovie(${m.tmdb_id})">
        ${m.poster ? `<img src="${esc(m.poster)}" alt="${esc(m.title||'')} poster" loading="lazy">` : '<div class="no-poster">No poster</div>'}
        <p class="wc-title">${esc(m.title||'Unknown')}</p>
        <p class="wc-year">${m.year||'N/A'}</p>
        ${m.watchlist_badge ? `<p class="wc-badge ${badgeClass(m.watchlist_badge)}">${esc(m.watchlist_badge)}</p>` : ''}
        ${m.one_liner ? `<p class="wc-one-liner">${esc(m.one_liner)}</p>` : ''}
        ${m.match_reason ? `<p class="wc-one-liner">${esc(m.match_reason)}</p>` : ''}
      </button>
    </div>`).join('');
}

async function removeFromWatchlist(tmdb_id) {
  await fetch(`/api/watchlist/${tmdb_id}`, {method:'DELETE'});
  if (currentTmdbId === tmdb_id) checkWatchlistStatus(tmdb_id);
  loadWatchlist();
}

async function rankWatchlist() {
  const msg = document.getElementById('wlRankMsg');
  msg.textContent = 'Asking Gemini to rank your watchlist...';
  document.getElementById('wlRankBtn').disabled = true;
  try {
    const res  = await fetch('/api/watchlist/rank', {method:'POST', headers:{'Content-Type':'application/json'}});
    const data = await res.json();
    if (!data.ok) { msg.textContent = data.error; return; }
    if (!data.ranked.length) { msg.textContent = 'Your watchlist is empty.'; return; }
    msg.textContent = `Ranked ${data.ranked.length} movie(s) for your sensitivity profile.`;
    renderWatchlistGrid(data.ranked, true);
  } catch(e) {
    msg.textContent = 'Error ranking watchlist.';
  } finally {
    document.getElementById('wlRankBtn').disabled = false;
  }
}

// ── Init ──────────────────────────────────────────────────────
checkAuth();
