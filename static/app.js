/* app.js — whisper-hebrew Web UI logic */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let currentFile    = null;
let currentResult  = null;
let currentJobId   = null;
let segmentSpans   = [];   // array of all .segment elements in render order
let activeSpanEl   = null; // currently highlighted span

// ── DOM refs ──────────────────────────────────────────────────────────────────
const dropZone          = document.getElementById('drop-zone');
const fileInput         = document.getElementById('file-input');
const fileInfo          = document.getElementById('file-info');
const startBtn          = document.getElementById('start-btn');
const modelSelect       = document.getElementById('model-select');
const langSelect        = document.getElementById('lang-select');
const fixToggle         = document.getElementById('fix-toggle');
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
const playerWrap        = document.getElementById('player-wrap');
const mediaPlayer       = document.getElementById('media-player');
const copyBtn           = document.getElementById('copy-btn');
const dlTxtBtn          = document.getElementById('download-txt-btn');
const dlSrtBtn          = document.getElementById('download-srt-btn');
const badgeFixed        = document.getElementById('badge-fixed');
const badgeRaw          = document.getElementById('badge-raw');

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

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

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
  progressSec.classList.remove('hidden');
  setProgress(0, label, '');

  try {
    const res = await fetch('/api/transcribe', { method: 'POST', body: form });
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
            if (ev.result && !ev.result.batch) {
              showResult(ev.result);
            } else if (ev.result && ev.result.batch) {
              showBatchResult(ev.result);
            }
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
  currentResult = result;

  // Badges
  badgeFixed.classList.toggle('hidden', !result.fixed);
  badgeRaw.classList.toggle('hidden', result.fixed);

  // Media player
  if (result.audio_url) {
    mediaPlayer.src = result.audio_url;
    playerWrap.classList.remove('hidden');
  } else {
    playerWrap.classList.add('hidden');
  }

  // Build interactive transcript from segments
  _renderSegments(result.segments || []);

  resultSec.classList.remove('hidden');
  transcriptContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function _renderSegments(segments) {
  transcriptContainer.innerHTML = '';
  segmentSpans = [];
  activeSpanEl = null;

  if (!segments.length) {
    transcriptContainer.textContent = currentResult?.text || '';
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const seg of segments) {
    const span = document.createElement('span');
    span.className = 'segment';
    span.dataset.start = seg.start;
    span.dataset.end   = seg.end;
    span.textContent   = seg.text.trim();
    span.title         = _formatTime(seg.start);

    span.addEventListener('click', () => {
      mediaPlayer.currentTime = seg.start;
      mediaPlayer.play();
    });

    fragment.appendChild(span);
    fragment.appendChild(document.createTextNode(' '));
    segmentSpans.push(span);
  }
  transcriptContainer.appendChild(fragment);
}

function _formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ── Audio sync: highlight active segment ──────────────────────────────────────
mediaPlayer.addEventListener('timeupdate', () => {
  const t = mediaPlayer.currentTime;

  // Fast path: still inside the current active segment
  if (activeSpanEl) {
    const s = parseFloat(activeSpanEl.dataset.start);
    const e = parseFloat(activeSpanEl.dataset.end);
    if (t >= s && t < e) return;
    activeSpanEl.classList.remove('active-segment');
    activeSpanEl = null;
  }

  // Find the new active segment (linear scan — fast enough for typical lecture size)
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
});

function showBatchResult(result) {
  resultSec.classList.remove('hidden');
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
  // Always use the stored result text (not DOM, which may be truncated)
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

// ── Settings ──────────────────────────────────────────────────────────────────
saveKeyBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  if (!key) return;
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
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

// Load masked key on startup
fetch('/api/settings').then(r => r.json()).then(d => {
  if (d.has_key) {
    apiKeyInput.placeholder = d.masked || 'מוגדר';
  }
}).catch(() => {});

function showStatus(el, msg, type) {
  el.textContent = msg;
  el.className = 'status-msg ' + type;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}
