<p align="center">
  <img src="public/tsp_logo.png" alt="The Side Project logo: tsp inside a white square on black" width="320">
</p>

# The Side Project

A generative text installation using [Qwen3 0.6B Base](https://huggingface.co/Qwen/Qwen3-0.6B-Base). A random character becomes a stream of text, displayed one token at a time in a white square. The model keeps only a small window of its own output as context and continues predicting what comes next.

This piece exists in dialogue with [Complimentary Machine](https://yanqihe.com/complimentary_machine). Where the latter is an over-aligned instruct model that only flatters and pleases, *The Side Project* uses a base model without a chat template or system prompt — a machine's monologue to itself.

## The loop

1. Start with a random uppercase letter or digit.
2. Predict and sample the next token using the most recent 10 tokens as context.
3. Display it, then feed it back into the next prediction. Special tokens such as `<|endoftext|>` remain visible; they do not stop the loop.
4. Start a new stream when the square fills up or someone clicks or taps it. Each new stream picks a new temperature: higher temperatures also produce shorter pauses between tokens.

Resizing keeps the square fitted to the window and restarts generation only if the text overflows. Independently, the backend flushes its context after 4,000 generated tokens and starts from another random character.

## Run locally

Use Python 3.12. The backend automatically selects Apple Silicon MPS, NVIDIA CUDA, or CPU, in that order.

### 1. Start the model

From the repository directory:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
HF_HOME="$PWD/cache/huggingface" python -m uvicorn app:app --host 127.0.0.1 --port 7860
```

The first run downloads `Qwen/Qwen3-0.6B-Base` into the ignored `cache/` directory. Later runs reuse the weights. Wait for the model and PCA calibration to finish and the server to report that it is running.

### 2. Open the display

In a second terminal, from the same directory:

```bash
.venv/bin/python -m http.server 8080 --bind 127.0.0.1
```

Open **[the text display](http://localhost:8080/main.html)**. Generation starts automatically; click or tap the white square to restart it.

Optionally open **[the probability monitor](http://localhost:8080/monitor.html)** in another tab or window of the same browser. It shows the current token, the top five sampling candidates and their probabilities, and the stream's temperature, context length, and requested delay. Open the monitor before the display, or restart the display after opening it, so it receives the current settings.

Both pages must use the same origin, including hostname and port, because they communicate through `BroadcastChannel`.

## Current settings

These are the settings sent by `main.html`; the backend's API defaults differ.

| Setting | Value | Where to change it |
| --- | --- | --- |
| Model | `Qwen/Qwen3-0.6B-Base` | `MODEL_DIR` in `app.py` |
| Initial seed | One character from `A–Z` or `0–9` | `SEEDS` in `app.py` |
| Sliding context | 10 tokens | `CONTEXT` in `main.html` |
| Temperature | Random value from 0.5 to 1.5 per new stream | `TEMP_MIN`, `TEMP_MAX` in `main.html` |
| Pause between tokens | 1.0 s at temperature 0.5; 0.1 s at temperature 1.5, interpolated linearly | `DELAY_MIN`, `DELAY_MAX`, `delayFromTemp()` in `main.html` |
| Top-p sampling | 0.92 | Sampling loop in `app.py` |
| Special tokens | Visible in text and candidate lists | `skip_special_tokens=False` in `app.py` |
| Backend context reset | After 4,000 generated tokens | `MAX_TOKENS_BEFORE_RESET` in `app.py` |

The backend uses the `delay` supplied with each `/generate` request. The actual interval also includes inference and other processing time; the monitor displays the requested pause, not a measured token interval. If the backend is on another machine, update `API_URL` in `main.html` and bind the backend to an appropriate network interface.

## Installation connections

### TouchDesigner / OSC

`app.py` projects the last input token's final-layer hidden state into three dimensions using PCA and sends OSC messages alongside generation. Set `OSC_TARGET_IP` and `OSC_TARGET_PORT` in `app.py` to match the receiver. The repository includes [TD_LATENT.toe](TD_LATENT.toe).

| OSC address | Payload |
| --- | --- |
| `/latent/point` | Generated token text, x, y, z, token count |
| `/reset` | Integer reset signal |

### Label printing

[print_server.py](print_server.py) provides the optional Brother QL printing service on port 5001. Before using a printer, set `PRINTER_MODEL` and `PRINTER_IDENTIFIER` to match the connected hardware; USB access and drivers depend on the operating system.

In the activated environment:

```bash
pip install flask flask-cors
python print_server.py
```

Start the print service before opening or reloading the text display. The display checks for it at startup and, when available, sends a screenshot of the current square before each frontend restart. Screenshot capture uses `html2canvas` loaded from a CDN. Without the print service, text generation still runs and printing is skipped.

## Repository

| File | Role |
| --- | --- |
| [app.py](app.py) | Local model, streaming generation, sampling, and OSC output |
| [main.html](main.html) | Text display, temperature / delay mapping, and print requests |
| [monitor.html](monitor.html) | Live token and probability display |
| [print_server.py](print_server.py) | Optional label printing service |
| [TD_LATENT.toe](TD_LATENT.toe) | TouchDesigner project |
| [public/tsp_logo.png](public/tsp_logo.png) | Project logo and browser icon |
| [public/unifont.otf](public/unifont.otf) | Display font |
