# The Side Project

An interactive art installation that streams AI-generated text token by token, visualising the model's latent space in real time through TouchDesigner via OSC.

## How It Works

1. **Qwen3-0.6B** generates text one token at a time
2. Each token's hidden state is projected to 3D via PCA and sent over **OSC** to **TouchDesigner**
3. A browser page (`main.html`) displays the growing text on a white canvas
4. A second page (`monitor.html`) shows the current token with a probability flicker animation
5. When the canvas overflows, it auto-prints to a **Brother QL-600** label printer and resets

## Project Structure

```
├── app.py              # FastAPI server — generation + OSC streaming
├── config.py           # All configuration in one place
├── model.py            # Model loading, device selection, PCA calibration
├── print_server.py     # Flask server — Brother QL label printing
├── requirements.txt
├── TD_LATENT.toe       # TouchDesigner project file
└── web/                # Frontend
    ├── main.html       # Main display (white canvas)
    ├── monitor.html    # Probability monitor (big token + candidates)
    ├── shared.css
    ├── main.css / main.js
    ├── monitor.css / monitor.js
    ├── unifont.otf
    ├── favicon.png
    └── cm_qr.svg
```

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
# Start the generation server (port 7860)
python app.py

# (Optional) Start the print server (port 5001)
python print_server.py
```

Then open `web/main.html` and `web/monitor.html` in a browser.

## Configuration

Edit `config.py`, or override OSC target at launch:

```bash
OSC_TARGET_IP=192.168.1.100 python app.py
```
