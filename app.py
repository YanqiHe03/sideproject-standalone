import torch
import random
import time
import uvicorn
import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from transformers import AutoTokenizer, AutoModelForCausalLM
from pydantic import BaseModel
from pythonosc import udp_client
from sklearn.decomposition import PCA
import json

# --- Configuration ---
MODEL_DIR = "Qwen/Qwen3-0.6B" 
SEEDS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
MAX_TOKENS_BEFORE_RESET = 4000

# --- OSC Configuration ---
OSC_TARGET_IP = "100.89.121.111"
OSC_TARGET_PORT = 7000

# --- Device Selection (Auto-detect: MPS > CUDA > CPU) ---
if torch.backends.mps.is_available():
    DEVICE = torch.device("mps")
    print("Using MPS (Apple Silicon GPU)")
elif torch.cuda.is_available():
    DEVICE = torch.device("cuda")
    print("Using CUDA (NVIDIA GPU)")
else:
    DEVICE = torch.device("cpu")
    print("Using CPU")

# --- Global State ---
current_delay = 0.5  # seconds between tokens (can be updated via /set-delay)
pca = None  # Will be initialized after model loading
osc_sender = None  # Will be initialized after config 

# --- Model Loading ---
print(f"Loading Model: {MODEL_DIR}...")
try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        trust_remote_code=True,
        torch_dtype=torch.float32,
    ).to(DEVICE)
    model.eval()
except Exception as e:
    print(f"Error loading model: {e}")

# --- OSC Client ---
print(f"OSC Client targeting: {OSC_TARGET_IP}:{OSC_TARGET_PORT}")
osc_sender = udp_client.SimpleUDPClient(OSC_TARGET_IP, OSC_TARGET_PORT)

# --- PCA Calibration ---
print("Calibrating Latent Space (PCA)...")
calibration_sentences = [
    "The quick brown fox jumps over the lazy dog.",
    "Artificial intelligence is a branch of computer science.",
    "I am a machine and I am thinking.",
    "Logic, emotion, data, vector, tensor, matrix.",
]
cal_vectors = []
with torch.no_grad():
    for sent in calibration_sentences:
        inputs = tokenizer(sent, return_tensors="pt")
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}  # Move to device
        outputs = model(**inputs, output_hidden_states=True)
        hidden = outputs.hidden_states[-1].squeeze(0).cpu().float().numpy()
        cal_vectors.append(hidden)
all_cal_data = np.concatenate(cal_vectors, axis=0)
pca = PCA(n_components=3)
pca.fit(all_cal_data)
print("PCA Calibrated.")

# --- FastAPI App ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    temp: float = 1.0
    context: int = 64
    delay: float = 0.05  # seconds between tokens
    reset: bool = True 

@app.post("/generate")
async def generate_endpoint(req: GenerateRequest):
    
    def iter_generation():
        # --- Exact Logic from live_base_server.py text_generator() ---
        
        if req.reset:
            osc_sender.send_message("/reset", 1)

        # 1. Initial Seed (Equivalent to state["reset_trigger"] logic)
        seed_text = random.choice(SEEDS)
        inputs = tokenizer(text=seed_text, return_tensors="pt")
        input_ids = inputs.input_ids.to(DEVICE)  # Move to device 
        
        current_count = 0
        
        # Send initial seed
        yield json.dumps({"text": seed_text, "count": 0}) + "\n"
        
        while True:
            try:
                # Check Reset Limit
                if current_count >= MAX_TOKENS_BEFORE_RESET:
                    seed_text = random.choice(SEEDS)
                    inputs = tokenizer(text=seed_text, return_tensors="pt")
                    input_ids = inputs.input_ids.to(DEVICE)  # Move to device
                    current_count = 0
                    
                    reset_msg = f"\n\n[AUTO-RESET: MEMORY FLUSH]\n{seed_text}"
                    osc_sender.send_message("/reset", 1)
                    yield json.dumps({"text": reset_msg, "count": 0}) + "\n"
                    continue

                # 2. Get Current State (from params)
                current_temp = req.temp
                max_ctx = max(1, req.context)
                
                # 3. Sliding Window
                if input_ids.shape[1] > max_ctx:
                    input_ids = input_ids[:, -max_ctx:]
                    
                # 4. Manual Inference (with hidden states for OSC)
                with torch.no_grad(): 
                    outputs = model(input_ids=input_ids, output_hidden_states=True)
                    next_token_logits = outputs.logits[:, -1, :]
                    
                    # Extract latent for OSC
                    last_hidden = outputs.hidden_states[-1][0, -1, :].cpu().float().numpy()
                    xyz = pca.transform([last_hidden])[0]
                    
                    # Apply Dynamic Temp
                    next_token_logits = next_token_logits / current_temp
                    
                    # Top-P (Fixed 0.92 - EXACTLY as original)
                    sorted_logits, sorted_indices = torch.sort(next_token_logits, descending=True)
                    cumulative_probs = torch.softmax(sorted_logits, dim=-1).cumsum(dim=-1)
                    sorted_indices_to_remove = cumulative_probs > 0.92
                    sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
                    sorted_indices_to_remove[..., 0] = 0
                    indices_to_remove = sorted_indices_to_remove.scatter(1, sorted_indices, sorted_indices_to_remove)
                    next_token_logits[indices_to_remove] = -float('inf')
                    
                    probs = torch.softmax(next_token_logits, dim=-1)
                    next_token = torch.multinomial(probs, num_samples=1)
                    final_prob = probs[0, next_token[0].item()].item()
                    
                    # Extract Top-5 candidates
                    top_probs, top_indices = torch.topk(probs, k=5, dim=-1)
                    candidates = []
                    for i in range(5):
                        token_text = tokenizer.decode([top_indices[0, i].item()], skip_special_tokens=True)
                        prob_value = top_probs[0, i].item()
                        candidates.append({"token": token_text, "prob": round(prob_value, 4)})
                    
                # 5. Decode
                new_text = tokenizer.decode(next_token[0], skip_special_tokens=True)
                
                # Yield with candidates
                current_count += 1
                yield json.dumps({
                    "text": new_text, 
                    "count": current_count,
                    "candidates": candidates,
                    "final_prob": round(final_prob, 6)
                }) + "\n"
                
                # Send OSC: /latent/point [text, x, y, z, index]
                osc_sender.send_message("/latent/point", [
                    new_text, 
                    float(xyz[0]), 
                    float(xyz[1]), 
                    float(xyz[2]), 
                    current_count
                ])
                
                # 6. Update Global State (Local variable here)
                input_ids = torch.cat([input_ids, next_token], dim=-1)
                
                # Speed control (uses global delay for real-time updates)
                time.sleep(max(0.01, min(2.0, current_delay)))

            except Exception as e:
                print(f"Gen Error: {e}")
                break

    return StreamingResponse(iter_generation(), media_type="application/x-ndjson")

# --- Set Delay Endpoint ---
class DelayRequest(BaseModel):
    delay: float = 0.05

@app.post("/set-delay")
async def set_delay(req: DelayRequest):
    global current_delay
    current_delay = max(0.01, min(2.0, req.delay))
    return {"status": "ok", "delay": current_delay}

# --- Reset Endpoint (OSC only) ---
class ResetRequest(BaseModel):
    value: int = 1

@app.post("/reset")
async def reset_endpoint(req: ResetRequest):
    osc_sender.send_message("/reset", int(req.value))
    return {"status": "ok", "value": int(req.value)}

# --- Simple Backend Dashboard ---
@app.get("/")
async def dashboard():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Backend Dashboard</title>
        <style>
            body { font-family: monospace; background: #000; color: #0f0; padding: 20px; }
        </style>
    </head>
    <body>
        <h1>THE SIDE PROJECT - BACKEND</h1>
        <div>Status: ONLINE (Original Logic)</div>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content, status_code=200)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
