"""
FastAPI server for The Side Project.
Streams generated tokens with latent-space coordinates via OSC.
"""

import json
import random
import time

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pythonosc import udp_client

from config import (
    SEEDS, MAX_TOKENS_BEFORE_RESET, TOP_P,
    DEFAULT_DELAY, DELAY_RANGE, API_HOST, API_PORT,
    OSC_TARGET_IP, OSC_TARGET_PORT,
)
from model import select_device, load_model, calibrate_pca

# --- Initialise ---
DEVICE = select_device()
tokenizer, model = load_model(DEVICE)
pca = calibrate_pca(model, tokenizer, DEVICE)
print(f"OSC Client targeting: {OSC_TARGET_IP}:{OSC_TARGET_PORT}")
osc_sender = udp_client.SimpleUDPClient(OSC_TARGET_IP, OSC_TARGET_PORT)

# --- Global State ---
current_delay = DEFAULT_DELAY

# --- FastAPI App ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request Models ---
class GenerateRequest(BaseModel):
    temp: float = 1.0
    context: int = 64
    delay: float = 0.05
    reset: bool = True


class DelayRequest(BaseModel):
    delay: float = 0.05


class ResetRequest(BaseModel):
    value: int = 1


# --- Endpoints ---
@app.post("/generate")
async def generate_endpoint(req: GenerateRequest):

    def iter_generation():
        global current_delay

        if req.reset:
            osc_sender.send_message("/reset", 1)

        seed_text = random.choice(SEEDS)
        inputs = tokenizer(text=seed_text, return_tensors="pt")
        input_ids = inputs.input_ids.to(DEVICE)
        current_count = 0

        yield json.dumps({"text": seed_text, "count": 0}) + "\n"

        while True:
            try:
                # Auto-reset when context gets too long
                if current_count >= MAX_TOKENS_BEFORE_RESET:
                    seed_text = random.choice(SEEDS)
                    inputs = tokenizer(text=seed_text, return_tensors="pt")
                    input_ids = inputs.input_ids.to(DEVICE)
                    current_count = 0
                    osc_sender.send_message("/reset", 1)
                    yield json.dumps({
                        "text": f"\n\n[AUTO-RESET: MEMORY FLUSH]\n{seed_text}",
                        "count": 0,
                    }) + "\n"
                    continue

                current_temp = req.temp
                max_ctx = max(1, req.context)

                # Sliding window
                if input_ids.shape[1] > max_ctx:
                    input_ids = input_ids[:, -max_ctx:]

                # Inference with hidden states for OSC
                with torch.no_grad():
                    outputs = model(input_ids=input_ids, output_hidden_states=True)
                    next_token_logits = outputs.logits[:, -1, :]

                    # Latent → PCA → OSC
                    last_hidden = outputs.hidden_states[-1][0, -1, :].cpu().float().numpy()
                    xyz = pca.transform([last_hidden])[0]

                    # Temperature
                    next_token_logits = next_token_logits / current_temp

                    # Top-P sampling (p=0.92)
                    sorted_logits, sorted_indices = torch.sort(next_token_logits, descending=True)
                    cumulative_probs = torch.softmax(sorted_logits, dim=-1).cumsum(dim=-1)
                    mask = cumulative_probs > TOP_P
                    mask[..., 1:] = mask[..., :-1].clone()
                    mask[..., 0] = 0
                    indices_to_remove = mask.scatter(1, sorted_indices, mask)
                    next_token_logits[indices_to_remove] = -float("inf")

                    probs = torch.softmax(next_token_logits, dim=-1)
                    next_token = torch.multinomial(probs, num_samples=1)
                    final_prob = probs[0, next_token[0].item()].item()

                    # Top-5 candidates
                    top_probs, top_indices = torch.topk(probs, k=5, dim=-1)
                    candidates = [
                        {
                            "token": tokenizer.decode([top_indices[0, i].item()], skip_special_tokens=True),
                            "prob": round(top_probs[0, i].item(), 4),
                        }
                        for i in range(5)
                    ]

                new_text = tokenizer.decode(next_token[0], skip_special_tokens=True)
                current_count += 1

                yield json.dumps({
                    "text": new_text,
                    "count": current_count,
                    "candidates": candidates,
                    "final_prob": round(final_prob, 6),
                }) + "\n"

                osc_sender.send_message("/latent/point", [
                    new_text,
                    float(xyz[0]),
                    float(xyz[1]),
                    float(xyz[2]),
                    current_count,
                ])

                input_ids = torch.cat([input_ids, next_token], dim=-1)

                delay_min, delay_max = DELAY_RANGE
                time.sleep(max(delay_min, min(delay_max, current_delay)))

            except Exception as e:
                print(f"Gen Error: {e}")
                break

    return StreamingResponse(iter_generation(), media_type="application/x-ndjson")


@app.post("/set-delay")
async def set_delay(req: DelayRequest):
    global current_delay
    delay_min, delay_max = DELAY_RANGE
    current_delay = max(delay_min, min(delay_max, req.delay))
    return {"status": "ok", "delay": current_delay}


@app.post("/reset")
async def reset_endpoint(req: ResetRequest):
    osc_sender.send_message("/reset", int(req.value))
    return {"status": "ok", "value": int(req.value)}


@app.get("/")
async def dashboard():
    return HTMLResponse(
        "<html><body style='font-family:monospace;background:#000;color:#0f0;padding:20px'>"
        "<h1>THE SIDE PROJECT - BACKEND</h1>"
        "<div>Status: ONLINE</div>"
        "</body></html>"
    )


if __name__ == "__main__":
    uvicorn.run(app, host=API_HOST, port=API_PORT)
