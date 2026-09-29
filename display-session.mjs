// Change the behavior of a display round here; page layout stays in the HTML files.
const TEMP_MIN = 0.5;
const TEMP_MAX = 1.5;
const CONTEXT = 10;
const DELAY_MIN = 0.1;
const DELAY_MAX = 1.0;

const PROTOCOL = 'sideproject-display-v1';
const CHANNEL = 'sideproject';

async function* readRecords(body, signal) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (signal.aborted) return;
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline;
      while ((newline = pending.indexOf('\n')) !== -1) {
        const line = pending.slice(0, newline).trim();
        pending = pending.slice(newline + 1);
        if (line) yield JSON.parse(line);
        if (signal.aborted) return;
      }
      if (done) {
        if (pending.trim()) yield JSON.parse(pending);
        return;
      }
    }
  } finally {
    try { await reader.cancel(); } catch { /* Fetch may already have been aborted. */ }
    reader.releaseLock();
  }
}

export class DisplaySession {
  #url;
  #render;
  #savePage;
  #fetch;
  #channel;
  #random;
  #onError;
  #source = crypto.randomUUID();
  #number = 0;
  #round = null;
  #closed = false;

  constructor({
    url = 'http://localhost:7860',
    render,
    savePage = () => {},
    fetch: fetchRequest = globalThis.fetch.bind(globalThis),
    channel = new BroadcastChannel(CHANNEL),
    random = Math.random,
    onError = error => console.error('Display session:', error),
  }) {
    this.#url = url;
    this.#render = render;
    this.#savePage = savePage;
    this.#fetch = fetchRequest;
    this.#channel = channel;
    this.#random = random;
    this.#onError = onError;
    channel.addEventListener('message', this.#answerSnapshot);
  }

  #answerSnapshot = ({ data }) => {
    if (data?.protocol === PROTOCOL && data.type === 'snapshot-request' && this.#round) {
      this.#publish('snapshot', this.#round, data.requester);
    }
  };

  #publish(type, round, target) {
    this.#channel.postMessage({
      protocol: PROTOCOL,
      type,
      source: this.#source,
      round: round.number,
      sequence: round.sequence,
      settings: round.settings,
      record: round.record,
      target,
    });
  }

  #isCurrent(round) {
    return !this.#closed && this.#round === round && !round.controller.signal.aborted;
  }

  // Resolves when this request ends, not when its next display round ends.
  restart() {
    if (this.#closed) return Promise.resolve();
    const previous = this.#round;
    if (previous) {
      previous.controller.abort();
      if (previous.text.trim()) {
        // The view freezes its page synchronously, then prints in the background.
        try { this.#savePage(previous.text); } catch (error) { this.#onError(error); }
      }
    }

    const temp = Math.round((TEMP_MIN + this.#random() * (TEMP_MAX - TEMP_MIN)) * 100) / 100;
    const delay = DELAY_MAX - (temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * (DELAY_MAX - DELAY_MIN);
    const round = {
      number: ++this.#number,
      settings: { temp, context: CONTEXT, delay },
      controller: new AbortController(),
      text: '',
      record: null,
      sequence: 0,
    };
    this.#round = round;
    this.#render('');
    this.#publish('reset', round);
    return this.#consume(round);
  }

  async #consume(round) {
    try {
      const response = await this.#fetch(`${this.#url}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...round.settings, reset: true }),
        signal: round.controller.signal,
      });
      if (!this.#isCurrent(round)) {
        await response.body?.cancel();
        return;
      }
      if (!response.ok || !response.body) throw new Error(`HTTP error: ${response.status}`);

      for await (const record of readRecords(response.body, round.controller.signal)) {
        if (!this.#isCurrent(round)) return;
        if (typeof record?.text !== 'string') throw new Error('Generation record has no text');
        round.text += record.text;
        round.record = record;
        round.sequence += 1;
        const overflow = this.#render(round.text);
        if (!this.#isCurrent(round)) return;

        // Deliver the old round's last token BEFORE announcing a new round.
        this.#publish('token', round);
        if (overflow) {
          void this.restart();
          return;
        }
      }
    } catch (error) {
      if (this.#isCurrent(round)) this.#onError(error);
    }
  }

  close() {
    this.#closed = true;
    this.#round?.controller.abort();
    this.#channel.removeEventListener('message', this.#answerSnapshot);
    this.#channel.close();
  }
}

// Monitors join the active round; they never start their own model request.
export function observeDisplaySession({
  onReset,
  onToken,
  channel = new BroadcastChannel(CHANNEL),
}) {
  const requester = crypto.randomUUID();
  let current = null;
  let sequence = -1;

  const receive = ({ data }) => {
    if (data?.protocol !== PROTOCOL || !['reset', 'token', 'snapshot'].includes(data.type)) return;
    if (data.target && data.target !== requester) return;

    const sameSource = current?.source === data.source;
    if (current && !sameSource && data.type !== 'reset') return;
    if (sameSource && data.round < current.round) return;
    const newRound = !sameSource || data.round !== current.round;
    if (!newRound && data.sequence <= sequence) return;

    if (newRound) {
      current = { source: data.source, round: data.round };
      sequence = -1;
      onReset(data.settings);
    }
    sequence = data.sequence;
    if (data.record) onToken(data.record);
  };

  channel.addEventListener('message', receive);
  channel.postMessage({ protocol: PROTOCOL, type: 'snapshot-request', requester });
  return () => {
    channel.removeEventListener('message', receive);
    channel.close();
  };
}
