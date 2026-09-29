# The Side Project

A generative text art installation using [Qwen3 0.6B Base](https://huggingface.co/Qwen/Qwen3-0.6B-Base) (`Qwen/Qwen3-0.6B-Base`) for infinite autoregressive generation. This work serves as a mirror piece to [Complimentary Machine](https://yanqihe.com/complimentary_machine).

## How It Works

1. Fetches streaming text from a Qwen3 0.6B base model backend
2. Displays generated text in real-time within a responsive centered square
3. Automatically resets when the screen fills up or window resizes

## Usage

### Backend

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
HF_HOME="$PWD/cache/huggingface" python app.py
```

The server runs on `http://localhost:7860`. The first run downloads the model into the ignored `cache/` directory. Later runs reuse it. On Apple Silicon, the backend uses MPS when available.

### Frontend

1. Update the `API_URL` in `main.html` if needed:

```javascript
const API_URL = "http://localhost:7860";
```

2. In another terminal, serve this directory:

```bash
.venv/bin/python -m http.server 8080 --bind 127.0.0.1
```

3. Open [main.html](http://localhost:8080/main.html) in a browser. Optionally open [monitor.html](http://localhost:8080/monitor.html) in the same browser to see token candidates and probabilities.

Generation starts from a random letter or digit, without a chat template. The current frontend uses a 10-token sliding context and picks a temperature between 0.5 and 1.5 on each reset.

## Interaction

- **Click/Tap:** Restarts generation
- **Window resize:** Adapts square size, resets if content overflows

## Concept

This piece exists in dialogue with *Complimentary Machine*. Where the latter is an over-aligned instruct model that only flatters and pleases, *The Side Project* strips away all instruction-following structure, leaving only the raw transformer prediction loop feeding its own output back as input — a machine's monologue to itself.

## Links

- **Complimentary Machine:** [yanqihe.com/complimentary_machine](https://yanqihe.com/complimentary_machine)
