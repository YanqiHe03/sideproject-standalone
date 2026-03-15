// Configuration
const API_URL = "http://localhost:7860";
const PRINT_URL = "http://localhost:5001";
const TEMP_MIN = 0.5;
const TEMP_MAX = 1.5;
const CONTEXT = 10;
const DELAY_MIN = 0.1;
const DELAY_MAX = 1.0;

// Elements
const canvas = document.getElementById('canvas');

// State
let abortController = null;
let text = '';
let currentDelay = 0.05;
let currentTemp = TEMP_MIN;
let printServerAvailable = null;

// BroadcastChannel for syncing with monitor
const channel = new BroadcastChannel('sideproject');

// Check if print server is available
async function checkPrintServer() {
  try {
    const response = await fetch(`${PRINT_URL}/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(2000)
    });
    printServerAvailable = response.ok;
    console.log('Print server:', printServerAvailable ? 'available' : 'not available');
  } catch (e) {
    printServerAvailable = false;
    console.log('Print server: not available (will use browser print)');
  }
}

// Print function - captures canvas screenshot and sends to print server
async function printCanvas() {
  if (!text.trim()) return;

  if (printServerAvailable) {
    try {
      const screenshot = await html2canvas(canvas, {
        backgroundColor: '#ffffff',
        scale: 2,
      });
      const imageData = screenshot.toDataURL('image/png');

      const response = await fetch(`${PRINT_URL}/print-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: imageData }),
        signal: AbortSignal.timeout(15000)
      });
      if (response.ok) {
        console.log('Printed canvas screenshot via print_server');
        return;
      }
    } catch (e) {
      console.error('Print server error:', e);
    }
  }
}

function pickRandomTemp() {
  const raw = TEMP_MIN + Math.random() * (TEMP_MAX - TEMP_MIN);
  return Math.round(raw * 100) / 100;
}

function delayFromTemp(temp) {
  const t = Math.min(TEMP_MAX, Math.max(TEMP_MIN, temp));
  const ratio = (t - TEMP_MIN) / (TEMP_MAX - TEMP_MIN);
  return DELAY_MAX - ratio * (DELAY_MAX - DELAY_MIN);
}

// Resize canvas to be a centered square
function resizeCanvas() {
  const size = Math.min(window.innerWidth, window.innerHeight) * 0.95;
  canvas.style.width = size + 'px';
  canvas.style.height = size + 'px';

  if (canvas.scrollHeight > canvas.clientHeight) {
    startStream();
  }
}

// Check if content overflows
function checkOverflow() {
  if (canvas.scrollHeight > canvas.clientHeight) {
    startStream();
  }
}

// Start streaming from API
async function startStream() {
  if (text.trim()) {
    printCanvas();
  }

  if (abortController) {
    abortController.abort();
  }

  abortController = new AbortController();
  text = '';
  canvas.textContent = '';

  currentTemp = pickRandomTemp();
  currentDelay = delayFromTemp(currentTemp);

  channel.postMessage({
    type: 'reset',
    temp: currentTemp,
    context: CONTEXT,
    delay: currentDelay
  });

  try {
    const response = await fetch(`${API_URL}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temp: currentTemp, context: CONTEXT, delay: currentDelay, reset: true }),
      signal: abortController.signal
    });

    if (!response.ok || !response.body) {
      throw new Error(`HTTP error: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let isFirst = true;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n').filter(line => line.trim());

      for (const line of lines) {
        try {
          const data = JSON.parse(line);
          if (data.text) {
            if (isFirst) {
              text = data.text;
              isFirst = false;
            } else {
              text += data.text;
            }
            canvas.textContent = text;
            checkOverflow();
            channel.postMessage(data);
          }
        } catch (e) {
          // JSON parse error, skip
        }
      }
    }
  } catch (error) {
    if (error.name === 'AbortError') return;
    console.error('Stream error:', error);
  }
}

// Event listeners
window.addEventListener('resize', resizeCanvas);
canvas.addEventListener('click', startStream);
canvas.addEventListener('touchstart', (e) => {
  e.preventDefault();
  startStream();
});

// Initialize
checkPrintServer();
resizeCanvas();
startStream();
