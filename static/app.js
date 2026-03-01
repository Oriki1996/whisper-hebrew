/* app.js — whisper-hebrew Web UI logic */
'use strict';

// ── Markdown renderer (zero dependencies) ─────────────────────────────────────
function _renderMarkdown(md) {
  let html = md
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm,  '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,    '<em>$1</em>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm,'<li>$1</li>');

  // Wrap consecutive <li> in <ul>
  html = html.replace(/(<li>[\s\S]*?<\/li>)(\s*<li>[\s\S]*?<\/li>)*/g, m => `<ul>${m}</ul>`);

  // Paragraphs
  html = html.split(/\n{2,}/)
    .map(b => {
      const t = b.trim();
      if (!t) return '';
      if (/^<(h[23]|ul|li)/.test(t)) return t;
      return `<p>${t.replace(/\n/g, ' ')}</p>`;
    })
    .join('\n');

  return html;
}

// ── State ─────────────────────────────────────────────────────────────────────
let currentFile    = null;
let currentResult  = null;
let currentJobId   = null;
let currentLectureId = null;
let segmentSpans   = [];
let activeSpanEl   = null;

// WaveSurfer instance
let ws             = null;

// Speaker colour mapping
const _speakerColors = ['speaker-0', 'speaker-1', 'speaker-2', 'speaker-3'];
const _speakerMap    = {};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const dropZone          = document.getElementById('drop-zone');
const fileInput         = document.getElementById('file-input');
const fileInfo          = document.getElementById('file-info');
const startBtn          = document.getElementById('start-btn');
const modelSelect       = document.getElementById('model-select');
const langSelect        = document.getElementById('lang-select');
const fixToggle         = document.getElementById('fix-toggle');
const diarizeToggle     = document.getElementById('diarize-toggle');
const batchBtn          = document.getElementById('batch-btn');
const folderInput       = document.getElementById('folder-input');
const batchModel        = document.getElementById('batch-model');
const batchFix          = document.getElementById('batch-fix-toggle');
const apiKeyInput       = document.getElementById('api-key-input');
const saveKeyBtn        = document.getElementById('save-key-btn');
const keyStatus         = document.getElementById('key-status');
const progressSec       = document.getElementById('progress-section');
const progressBar       = document.getElementById('progress-bar');
const progressPct       = document.getElementById('progress-pct');
const progressLbl       = document.getElementById('progress-label');
const progressMsg       = document.getElementById('progress-msg');
const progressAria      = document.getElementById('progress-bar-aria');
const resultSec         = document.getElementById('result-section');
const transcriptContainer = document.getElementById('transcript-container');
const waveformWrap      = document.getElementById('waveform-wrap');
const waveformEl        = document.getElementById('waveform');
const wsPlayBtn         = document.getElementById('ws-play-btn');
const wsTime            = document.getElementById('ws-time');
const playerWrap        = document.getElementById('player-wrap');
const mediaPlayer       = document.getElementById('media-player');
const insightsBtn       = document.getElementById('insights-btn');
const ankiBtn           = document.getElementById('anki-btn');
const obsidianBtn       = document.getElementById('obsidian-btn');
const copyBtn           = document.getElementById('copy-btn');
const dlTxtBtn          = document.getElementById('download-txt-btn');
const dlSrtBtn          = document.getElementById('download-srt-btn');
const badgeFixed        = document.getElementById('badge-fixed');
const badgeRaw          = document.getElementById('badge-raw');
const insightsSec       = document.getElementById('insights-section');
const insightsBody      = document.getElementById('insights-body');
const insightsSpinner   = document.getElementById('insights-spinner');

// Library
const libraryLoading    = document.getElementById('library-loading');
const libraryEmpty      = document.getElementById('library-empty');
const libraryGrid       = document.getElementById('library-grid');
const searchInput       = document.getElementById('search-input');
const searchMode        = document.getElementById('search-mode');
const searchBtn         = document.getElementById('search-btn');
const searchResults     = document.getElementById('search-results');

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => {
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(p => {
      p.classList.remove('active');
      p.hidden = true;
    });
    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
    const panel = document.getElementById('tab-' + tab.dataset.tab);
    panel.classList.add('active');
    panel.hidden = false;

    if (tab.dataset.tab === 'library') loadLibrary();
  });
});

// ── Drop Zone ─────────────────────────────────────────────────────────────────
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) setFile(f);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

function setFile(f) {
  currentFile = f;
  fileInfo.textContent = `📄 ${f.name} — ${(f.size / 1024 / 1024).toFixed(1)} MB`;
  fileInfo.classList.remove('hidden');
  startBtn.disabled = false;
}

// ── Single transcribe ─────────────────────────────────────────────────────────
startBtn.addEventListener('click', async () => {
  if (!currentFile) return;
  const form = new FormData();
  form.append('file', currentFile);
  form.append('model', modelSelect.value);
  form.append('lang', langSelect.value === 'auto' ? '' : langSelect.value);
  form.append('fix', fixToggle.checked ? 'true' : 'false');
  form.append('diarize', diarizeToggle.checked ? 'true' : 'false');
  await startJob(form, 'מתמלל...');
});

// ── Batch ─────────────────────────────────────────────────────────────────────
batchBtn.addEventListener('click', async () => {
  const folder = folderInput.value.trim();
  if (!folder) { alert('נא להזין נתיב תיקייה'); return; }
  const form = new FormData();
  form.append('folder', folder);
  form.append('model', batchModel.value);
  form.append('fix', batchFix.checked ? 'true' : 'false');
  await startJob(form, 'מעבד תיקייה...');
});

// ── Job runner ────────────────────────────────────────────────────────────────
async function startJob(form, label) {
  resultSec.classList.add('hidden');
  insightsSec.classList.add('hidden');
  progressSec.classList.remove('hidden');
  setProgress(0, label, '');

  try {
    const res  = await fetch('/api/transcribe', { method: 'POST', body: form });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    currentJobId = data.job_id;
    await streamProgress(currentJobId);
  } catch (e) {
    setProgress(0, 'שגיאה', e.message);
  }
}

async function streamProgress(jobId) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/progress/${jobId}`);
    es.onmessage = ({ data }) => {
      try {
        const ev = JSON.parse(data);
        setProgress(ev.progress / 100, progressLbl.textContent, ev.msg || '');
        if (ev.done) {
          es.close();
          if (ev.error) {
            setProgress(0, 'שגיאה', ev.error);
            reject(new Error(ev.error));
          } else {
            setProgress(1, 'הושלם!', '');
            if (ev.result && !ev.result.batch) showResult(ev.result);
            else if (ev.result?.batch)          showBatchResult(ev.result);
            resolve();
          }
        }
      } catch (_) {}
    };
    es.onerror = () => { es.close(); reject(new Error('חיבור נפסק')); };
  });
}

function setProgress(pct, label, msg) {
  const p = Math.round(pct * 100);
  progressBar.style.width = p + '%';
  progressPct.textContent = p + '%';
  progressLbl.textContent = label;
  progressMsg.textContent = msg;
  progressAria.setAttribute('aria-valuenow', p);
}

// ── Result display ────────────────────────────────────────────────────────────
function showResult(result) {
  currentResult    = result;
  currentLectureId = result.lecture_id || null;

  badgeFixed.classList.toggle('hidden', !result.fixed);
  badgeRaw.classList.toggle('hidden', result.fixed);

  // Show Anki/Obsidian buttons if lecture is in library
  ankiBtn.classList.toggle('hidden', !currentLectureId);
  obsidianBtn.classList.toggle('hidden', !currentLectureId);

  // ── Media / WaveSurfer ──────────────────────────────────────────────────────
  if (result.audio_url) {
    const isVideo = /\.(mp4|mkv|webm|mov)$/i.test(result.audio_url);
    if (!isVideo && typeof WaveSurfer !== 'undefined') {
      _initWaveSurfer(result.audio_url);
    } else {
      // Fallback: plain video element
      waveformWrap.classList.add('hidden');
      mediaPlayer.src = result.audio_url;
      playerWrap.classList.remove('hidden');
    }
  } else {
    waveformWrap.classList.add('hidden');
    playerWrap.classList.add('hidden');
  }

  _renderSegments(result.segments || []);
  resultSec.classList.remove('hidden');
  transcriptContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── WaveSurfer ────────────────────────────────────────────────────────────────
function _initWaveSurfer(url) {
  playerWrap.classList.add('hidden');
  waveformWrap.classList.remove('hidden');

  if (ws) { ws.destroy(); ws = null; }

  ws = WaveSurfer.create({
    container:      waveformEl,
    waveColor:      'rgba(200,129,58,0.5)',
    progressColor:  '#c8813a',
    cursorColor:    '#fff',
    height:         80,
    barWidth:       2,
    barGap:         1,
    barRadius:      2,
    normalize:      true,
    backend:        'WebAudio',
    url,
  });

  ws.on('ready', () => {
    wsPlayBtn.textContent = '▶ נגן';
    _updateWsTime();
  });

  ws.on('audioprocess', () => {
    _updateWsTime();
    _syncSegmentsWs(ws.getCurrentTime());
  });

  ws.on('seek', () => {
    _syncSegmentsWs(ws.getCurrentTime());
  });

  ws.on('play',  () => { wsPlayBtn.textContent = '⏸ השהה'; });
  ws.on('pause', () => { wsPlayBtn.textContent = '▶ נגן'; });
  ws.on('finish',() => { wsPlayBtn.textContent = '▶ נגן'; });
}

wsPlayBtn.addEventListener('click', () => {
  if (ws) ws.playPause();
});

function _updateWsTime() {
  if (!ws) return;
  const cur = ws.getCurrentTime();
  const dur = ws.getDuration() || 0;
  wsTime.textContent = `${_fmt(cur)} / ${_fmt(dur)}`;
}

function _fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ── Segments ──────────────────────────────────────────────────────────────────
function _renderSegments(segments) {
  transcriptContainer.innerHTML = '';
  segmentSpans = [];
  activeSpanEl = null;
  Object.keys(_speakerMap).forEach(k => delete _speakerMap[k]);

  if (!segments.length) {
    transcriptContainer.textContent = currentResult?.text || '';
    return;
  }

  // Collect unique speakers for colour assignment
  let speakerIdx = 0;
  segments.forEach(seg => {
    const spk = seg.speaker_id || '';
    if (spk && !(spk in _speakerMap)) {
      _speakerMap[spk] = speakerIdx++ % _speakerColors.length;
    }
  });

  const fragment = document.createDocumentFragment();
  let lastSpeaker = null;

  for (const seg of segments) {
    const spk = seg.speaker_id || '';

    // Speaker label on speaker change
    if (spk && spk !== lastSpeaker) {
      const badge = document.createElement('span');
      badge.className = `speaker-badge ${_speakerColors[_speakerMap[spk] ?? 0]}`;
      badge.textContent = spk.replace('SPEAKER_', 'דובר ');
      fragment.appendChild(document.createElement('br'));
      fragment.appendChild(badge);
      lastSpeaker = spk;
    }

    const span = document.createElement('span');
    span.className    = 'segment';
    span.dataset.start = seg.start;
    span.dataset.end   = seg.end;
    span.textContent   = seg.text.trim();
    span.title         = _fmt(seg.start);

    span.addEventListener('click', () => {
      if (ws) {
        ws.seekTo(seg.start / (ws.getDuration() || 1));
        ws.play();
      } else {
        mediaPlayer.currentTime = seg.start;
        mediaPlayer.play();
      }
    });

    fragment.appendChild(span);
    fragment.appendChild(document.createTextNode(' '));
    segmentSpans.push(span);
  }
  transcriptContainer.appendChild(fragment);
}

// ── Audio sync (video fallback) ───────────────────────────────────────────────
mediaPlayer.addEventListener('timeupdate', () => {
  _syncSegmentsWs(mediaPlayer.currentTime);
});

function _syncSegmentsWs(t) {
  if (activeSpanEl) {
    const s = parseFloat(activeSpanEl.dataset.start);
    const e = parseFloat(activeSpanEl.dataset.end);
    if (t >= s && t < e) return;
    activeSpanEl.classList.remove('active-segment');
    activeSpanEl = null;
  }
  for (const span of segmentSpans) {
    const s = parseFloat(span.dataset.start);
    const e = parseFloat(span.dataset.end);
    if (t >= s && t < e) {
      span.classList.add('active-segment');
      span.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      activeSpanEl = span;
      break;
    }
  }
}

function showBatchResult(result) {
  resultSec.classList.remove('hidden');
  waveformWrap.classList.add('hidden');
  playerWrap.classList.add('hidden');
  transcriptContainer.innerHTML = '';
  transcriptContainer.textContent =
    `הושלם!\n\nעובדו: ${result.processed} קבצים\nדולגו: ${result.skipped} קבצים\n\nהקבצים שמורים בתיקיית output/`;
  badgeFixed.classList.add('hidden');
  badgeRaw.classList.add('hidden');
  segmentSpans = [];
}

// ── Copy / Download ───────────────────────────────────────────────────────────
function _fullText() {
  return currentResult?.text || transcriptContainer.textContent;
}

copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(_fullText())
    .then(() => flashBtn(copyBtn, '✅ הועתק!'))
    .catch(() => {});
});

dlTxtBtn.addEventListener('click', () => {
  if (!currentResult) return;
  const filename = currentResult.txt_path?.split(/[/\\]/).pop() || 'transcript.txt';
  downloadText(_fullText(), filename);
});

dlSrtBtn.addEventListener('click', () => {
  if (!currentResult?.srt_path) return;
  const name = currentResult.srt_path.split(/[/\\]/).pop();
  window.open('/output/' + name);
});

function downloadText(text, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  a.download = filename;
  a.click();
}

function flashBtn(btn, text) {
  const orig = btn.textContent;
  btn.textContent = text;
  setTimeout(() => { btn.textContent = orig; }, 1800);
}

// ── Anki export ───────────────────────────────────────────────────────────────
ankiBtn.addEventListener('click', async () => {
  if (!currentLectureId) return;
  // First ensure insights exist; if not, generate them
  try {
    const res = await fetch(`/api/library/${currentLectureId}/anki`);
    if (res.ok) {
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `anki_${currentLectureId}.csv`;
      a.click();
    } else {
      const d = await res.json();
      alert(d.error || 'שגיאה בייצוא Anki');
    }
  } catch (e) {
    alert('שגיאת חיבור: ' + e.message);
  }
});

// ── Obsidian export ───────────────────────────────────────────────────────────
obsidianBtn.addEventListener('click', async () => {
  if (!currentLectureId) return;
  try {
    const res = await fetch(`/api/library/${currentLectureId}/obsidian`);
    if (res.ok) {
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      flashBtn(obsidianBtn, '✅ הועתק!');
    } else {
      alert('שגיאה בייצוא Obsidian');
    }
  } catch (e) {
    alert('שגיאת חיבור: ' + e.message);
  }
});

// ── AI Insights ───────────────────────────────────────────────────────────────
insightsBtn.addEventListener('click', async () => {
  const text = _fullText();
  if (!text) return;

  insightsSec.classList.remove('hidden');
  insightsBody.innerHTML = '';
  insightsSpinner.classList.remove('hidden');
  insightsBtn.disabled = true;
  insightsSec.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    // If we have a lecture in DB, save insights there too
    const endpoint = currentLectureId
      ? `/api/library/${currentLectureId}/insights`
      : '/api/insights';
    const body = currentLectureId ? '{}' : JSON.stringify({ text });

    const res  = await fetch(endpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });
    const data = await res.json();

    if (data.ok) {
      _renderInsights(data.data);
      // After insights saved, show Anki export button
      if (currentLectureId) ankiBtn.classList.remove('hidden');
    } else {
      insightsBody.innerHTML = `<p class="insights-error">שגיאה: ${data.error}</p>`;
    }
  } catch (e) {
    insightsBody.innerHTML = `<p class="insights-error">שגיאת חיבור: ${e.message}</p>`;
  } finally {
    insightsSpinner.classList.add('hidden');
    insightsBtn.disabled = false;
  }
});

function _renderInsights(d) {
  const sections = [];

  if (d.summary) {
    sections.push(`<h2>סיכום תמציתי</h2><p>${d.summary}</p>`);
  }

  if (d.key_terms?.length) {
    const items = d.key_terms.map(t =>
      `<li><strong>${t.term}</strong> — ${t.definition}</li>`
    ).join('');
    sections.push(`<h2>מושגי מפתח</h2><ul>${items}</ul>`);
  }

  if (d.anki_cards?.length) {
    const rows = d.anki_cards.map((c, i) =>
      `<tr><td class="anki-q">${i + 1}. ${c.front}</td><td class="anki-a">${c.back}</td></tr>`
    ).join('');
    sections.push(`
      <h2>שאלות לתרגול (Anki)</h2>
      <table class="anki-table"><thead>
        <tr><th>שאלה</th><th>תשובה</th></tr>
      </thead><tbody>${rows}</tbody></table>`);
  }

  if (d.citations?.length) {
    const items = d.citations.map(c => {
      let ref = `<strong>${c.author || ''}</strong>`;
      if (c.title)   ref += `, <em>${c.title}</em>`;
      if (c.year)    ref += ` (${c.year})`;
      if (c.context) ref += ` — ${c.context}`;
      return `<li>${ref}</li>`;
    }).join('');
    sections.push(`<h2>מקורות שהוזכרו</h2><ul>${items}</ul>`);
  }

  insightsBody.innerHTML = sections.join('');
}

// ── Library ───────────────────────────────────────────────────────────────────
async function loadLibrary() {
  libraryLoading.classList.remove('hidden');
  libraryEmpty.classList.add('hidden');
  libraryGrid.classList.add('hidden');

  try {
    const res      = await fetch('/api/library');
    const lectures = await res.json();

    libraryLoading.classList.add('hidden');

    if (!lectures.length) {
      libraryEmpty.classList.remove('hidden');
      return;
    }

    libraryGrid.innerHTML = '';
    for (const lec of lectures) {
      libraryGrid.appendChild(_makeLectureCard(lec));
    }
    libraryGrid.classList.remove('hidden');
  } catch (e) {
    libraryLoading.textContent = 'שגיאה בטעינת ספרייה: ' + e.message;
  }
}

function _durStr(sec) {
  if (!sec) return '';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function _makeLectureCard(lec) {
  const card = document.createElement('div');
  card.className = 'lecture-card';

  const date = lec.date || lec.created_at?.slice(0, 10) || '';
  const dur  = _durStr(lec.duration);

  card.innerHTML = `
    <p class="lecture-card-title">${lec.filename}</p>
    <p class="lecture-card-meta">
      ${lec.course_name ? `<strong>${lec.course_name}</strong><br>` : ''}
      ${lec.lecturer   ? `${lec.lecturer}<br>` : ''}
      ${date ? date + (dur ? '  ·  ' : '') : ''}${dur}
    </p>
    <div class="lecture-card-actions">
      <button class="btn-secondary btn-sm" data-action="open">📖 פתח</button>
      <button class="btn-secondary btn-sm" data-action="insights">✨ נתח</button>
      <button class="btn-secondary btn-sm" data-action="anki">⬇ Anki</button>
      <button class="btn-secondary btn-sm" data-action="obsidian">📝 Obsidian</button>
      <button class="btn-secondary btn-sm" data-action="delete" style="color:var(--error)">🗑</button>
    </div>`;

  card.querySelector('[data-action="open"]').addEventListener('click', () => _openLibraryLecture(lec.id));
  card.querySelector('[data-action="insights"]').addEventListener('click', () => _analyseLibraryLecture(lec.id));
  card.querySelector('[data-action="anki"]').addEventListener('click', () => _downloadAnki(lec.id));
  card.querySelector('[data-action="obsidian"]').addEventListener('click', () => _downloadObsidian(lec.id));
  card.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    if (!confirm(`למחוק את "${lec.filename}"?`)) return;
    await fetch(`/api/library/${lec.id}`, { method: 'DELETE' });
    card.remove();
    if (!libraryGrid.children.length) {
      libraryGrid.classList.add('hidden');
      libraryEmpty.classList.remove('hidden');
    }
  });

  return card;
}

async function _openLibraryLecture(lid) {
  try {
    const res  = await fetch(`/api/library/${lid}`);
    const data = await res.json();
    if (!data.lecture) return;

    currentResult    = { text: data.lecture.full_fixed_text || data.lecture.full_raw_text || '' };
    currentLectureId = lid;

    // Switch to single tab and show result
    document.querySelector('[data-tab="single"]').click();
    badgeFixed.classList.toggle('hidden', !data.lecture.full_fixed_text);
    badgeRaw.classList.toggle('hidden',   !!data.lecture.full_fixed_text);
    ankiBtn.classList.remove('hidden');
    obsidianBtn.classList.remove('hidden');

    waveformWrap.classList.add('hidden');
    playerWrap.classList.add('hidden');

    _renderSegments(
      (data.segments || []).map(s => ({
        start:      s.start_time,
        end:        s.end_time,
        text:       s.text,
        speaker_id: s.speaker_id || '',
      }))
    );

    resultSec.classList.remove('hidden');
    transcriptContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Show stored insights if available
    if (data.insights) {
      insightsBody.innerHTML = '';
      _renderInsights(data.insights);
      insightsSec.classList.remove('hidden');
    }
  } catch (e) {
    alert('שגיאה בפתיחת הרצאה: ' + e.message);
  }
}

async function _analyseLibraryLecture(lid) {
  insightsSec.classList.remove('hidden');
  insightsBody.innerHTML = '';
  insightsSpinner.classList.remove('hidden');

  try {
    const res  = await fetch(`/api/library/${lid}/insights`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const data = await res.json();
    if (data.ok) {
      _renderInsights(data.data);
      // Switch to single tab to show results
      document.querySelector('[data-tab="single"]').click();
      insightsSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      insightsBody.innerHTML = `<p class="insights-error">שגיאה: ${data.error}</p>`;
    }
  } catch (e) {
    insightsBody.innerHTML = `<p class="insights-error">שגיאת חיבור: ${e.message}</p>`;
  } finally {
    insightsSpinner.classList.add('hidden');
  }
}

async function _downloadAnki(lid) {
  const res = await fetch(`/api/library/${lid}/anki`);
  if (res.ok) {
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `anki_${lid}.csv`;
    a.click();
  } else {
    const d = await res.json().catch(() => ({}));
    alert(d.error || 'אין כרטיסיות. יש להריץ ניתוח הרצאה תחילה.');
  }
}

async function _downloadObsidian(lid) {
  const res = await fetch(`/api/library/${lid}/obsidian`);
  if (res.ok) {
    const text = await res.text();
    await navigator.clipboard.writeText(text);
    alert('ה-Markdown הועתק ללוח!');
  } else {
    alert('שגיאה בייצוא Obsidian');
  }
}

// ── Search ────────────────────────────────────────────────────────────────────
searchBtn.addEventListener('click', doSearch);
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

async function doSearch() {
  const q = searchInput.value.trim();
  if (!q) return;

  searchResults.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem">מחפש...</p>';
  searchResults.classList.remove('hidden');

  try {
    const res  = await fetch('/api/search', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q, mode: searchMode.value, top_k: 12 }),
    });
    const hits = await res.json();

    if (!hits.length) {
      searchResults.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem">לא נמצאו תוצאות</p>';
      return;
    }

    searchResults.innerHTML = '';
    for (const hit of hits) {
      const item = document.createElement('div');
      item.className = 'search-result-item';
      const score = hit.score ? `${Math.round(hit.score * 100)}%` : '';
      item.innerHTML = `
        <div class="search-result-source">
          ${hit.filename} ${hit.course_name ? '· ' + hit.course_name : ''}
          · <span style="font-family:monospace">${_fmt(hit.start_time || 0)}</span>
          ${hit.match_type === 'semantic' ? ' · 🔎 סמנטי' : ' · 🔤 לקסיקלי'}
        </div>
        <div class="search-result-text">${hit.text}</div>
        ${score ? `<span class="search-result-score">דמיון: ${score}</span>` : ''}`;
      item.addEventListener('click', () => _openLibraryLecture(hit.lecture_id));
      searchResults.appendChild(item);
    }
  } catch (e) {
    searchResults.innerHTML = `<p class="insights-error">שגיאה: ${e.message}</p>`;
  }
}

// ── Settings ──────────────────────────────────────────────────────────────────
saveKeyBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  if (!key) return;
  try {
    const res  = await fetch('/api/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anthropic_key: key }),
    });
    const data = await res.json();
    if (data.ok) {
      showStatus(keyStatus, 'המפתח נשמר בהצלחה', 'success');
      apiKeyInput.value = '';
    } else {
      showStatus(keyStatus, data.error || 'שגיאה', 'error');
    }
  } catch (e) {
    showStatus(keyStatus, e.message, 'error');
  }
});

fetch('/api/settings').then(r => r.json()).then(d => {
  if (d.has_key) apiKeyInput.placeholder = d.masked || 'מוגדר';
}).catch(() => {});

function showStatus(el, msg, type) {
  el.textContent = msg;
  el.className   = 'status-msg ' + type;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

// ── Anki table CSS (injected once) ───────────────────────────────────────────
(function () {
  const s = document.createElement('style');
  s.textContent = `
    .anki-table { width:100%; border-collapse:collapse; font-size:.88rem; margin:8px 0 16px; direction:rtl; }
    .anki-table th { background:rgba(200,129,58,.12); color:var(--primary); padding:6px 10px; text-align:right; }
    .anki-table td { padding:6px 10px; border-bottom:1px solid var(--border); vertical-align:top; }
    .anki-q { font-weight:600; width:45%; }
    .anki-a { color:var(--text-muted); }
  `;
  document.head.appendChild(s);
})();
