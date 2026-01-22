# The Side Project

A generative text art installation using Qwen3 0.6B base model for infinite autoregressive generation. This work serves as a mirror piece to [Complimentary Machine](https://yanqihe.com/complimentary_machine).

## How It Works

1. Fetches streaming text from a Qwen3 0.6B base model backend
2. Displays generated text in real-time within a responsive centered square
3. Automatically resets when the screen fills up or window resizes

## Usage

### Backend

```bash
pip install -r requirements.txt
python app.py
```

The server runs on `http://localhost:7860`.

### Frontend

1. Update the `API_URL` in `simple.html` if needed:

```javascript
const API_URL = "http://localhost:7860";
```

2. Open `simple.html` in a browser

## Interaction

- **Click/Tap:** Restarts generation
- **Window resize:** Adapts square size, resets if content overflows

## Concept

This piece exists in dialogue with *Complimentary Machine*. Where the latter is an over-aligned instruct model that only flatters and pleases, *The Side Project* strips away all instruction-following structure, leaving only the raw transformer prediction loop feeding its own output back as input — a machine's monologue to itself.

## Links

- **Complimentary Machine:** [yanqihe.com/complimentary_machine](https://yanqihe.com/complimentary_machine)
