// Elements
const tokenDisplay = document.getElementById('current-token');
const candidatesDisplay = document.getElementById('candidates');
const statusDisplay = document.getElementById('status');
const metaDisplay = document.getElementById('meta');

// BroadcastChannel for syncing with main
const channel = new BroadcastChannel('sideproject');

// Timing
let lastTokenTime = 0;
let estimatedInterval = 100;

// Queue for incoming data
const dataQueue = [];
let isAnimating = false;
let streamVersion = 0;

// Opacity levels for candidates (index 0 = highest prob, index 4 = lowest prob)
const OPACITY_LEVELS = [0.9, 0.7, 0.5, 0.4, 0.3];

function renderCandidates(candidates) {
  if (!candidates || candidates.length === 0) {
    candidatesDisplay.innerHTML = '';
    return;
  }

  candidatesDisplay.innerHTML = candidates.map((c, i) => `
    <div class="candidate" style="opacity: ${OPACITY_LEVELS[i] || 0.3}">
      <span class="candidate-token">${escapeHtml(formatToken(c.token))}</span>
      <span class="candidate-prob">${(c.prob * 100).toFixed(1)}%</span>
    </div>
  `).join('');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatToken(token) {
  if (token === null || token === undefined) return '\u00b7';
  if (token.length === 0) return '\u00b7';
  const normalized = token.replace(/\n/g, '\u00b7');
  if (/^\s+$/.test(normalized)) {
    return normalized.replace(/\s/g, '\u00b7');
  }
  return normalized;
}

function formatProb(prob) {
  if (typeof prob !== 'number' || Number.isNaN(prob)) return '';
  return `${(prob * 100).toFixed(2)}%`;
}

function updateMeta(temp, context, delay) {
  const tempText = typeof temp === 'number' ? temp.toFixed(2) : '--';
  const ctxText = Number.isFinite(context) ? context : '--';
  const delayText = typeof delay === 'number' ? `${Math.round(delay * 1000)}ms` : '--';
  metaDisplay.textContent = `TEMP ${tempText} | CTX ${ctxText} | DELAY ${delayText}`;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Animate flicker effect: low prob -> high prob -> final
async function animateToken(data, availableTime, version) {
  const { text, candidates, final_prob } = data;
  if (version !== streamVersion) return;

  const finalCandidate = {
    token: text || '\u00b7',
    prob: typeof final_prob === 'number' ? final_prob : 0,
  };

  const dedupedCandidates = Array.isArray(candidates)
    ? candidates.filter((c) => c && c.token !== text)
    : [];

  const displayCandidates = [finalCandidate, ...dedupedCandidates].slice(0, 5);

  if (!displayCandidates || displayCandidates.length === 0) {
    tokenDisplay.textContent = formatToken(text);
    tokenDisplay.style.opacity = 1;
    return;
  }

  renderCandidates(displayCandidates);

  // Sort candidates: lowest prob first (reverse order)
  const sortedCandidates = [...displayCandidates].reverse();
  const numSteps = sortedCandidates.length + 1;
  const stepDuration = Math.max(20, Math.floor(availableTime * 0.8 / numSteps));

  // Flicker from lowest prob to highest prob
  for (let i = 0; i < sortedCandidates.length; i++) {
    if (version !== streamVersion) return;
    const candidate = sortedCandidates[i];
    const opacity = OPACITY_LEVELS[sortedCandidates.length - 1 - i] || 0.3;

    tokenDisplay.textContent = formatToken(candidate.token);
    tokenDisplay.style.opacity = opacity;
    await sleep(stepDuration);
  }

  // Settle on final token
  if (version !== streamVersion) return;
  tokenDisplay.textContent = formatToken(text);
  tokenDisplay.style.opacity = 1;
}

async function processQueue() {
  if (isAnimating || dataQueue.length === 0) return;

  isAnimating = true;
  const version = streamVersion;

  while (dataQueue.length > 0) {
    if (version !== streamVersion) break;
    const data = dataQueue.shift();
    const availableTime = Math.max(50, Math.min(500, estimatedInterval));
    await animateToken(data, availableTime, version);
  }

  isAnimating = false;
}

// Color invert effect
function flashInvert() {
  document.body.classList.add('inverted');
  setTimeout(() => {
    document.body.classList.remove('inverted');
  }, 150);
}

// Listen for messages
channel.onmessage = (event) => {
  const data = event.data;

  if (data.type === 'reset') {
    flashInvert();
    streamVersion += 1;
    dataQueue.length = 0;
    tokenDisplay.textContent = '?';
    candidatesDisplay.innerHTML = '';
    lastTokenTime = 0;
    updateMeta(data.temp, data.context, data.delay);
    return;
  }

  const now = performance.now();

  if (lastTokenTime > 0) {
    const interval = now - lastTokenTime;
    estimatedInterval = estimatedInterval * 0.7 + interval * 0.3;
  }
  lastTokenTime = now;

  statusDisplay.textContent = `RECEIVING... (${Math.round(estimatedInterval)}ms)`;
  dataQueue.push(data);
  processQueue();
};

// Initial state
tokenDisplay.textContent = '?';
updateMeta();
