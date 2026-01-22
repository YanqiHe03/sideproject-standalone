import torch
import random
import time
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from transformers import AutoTokenizer, AutoModelForCausalLM
from pydantic import BaseModel
import json

# --- Configuration ---
MODEL_DIR = "Qwen/Qwen3-0.6B" 
SEEDS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
MAX_TOKENS_BEFORE_RESET = 4000 

# --- Model Loading ---
print(f"Loading Model: {MODEL_DIR}...")
try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        trust_remote_code=True,
        torch_dtype=torch.float32,
        device_map="cpu",
    )
    model.eval()
except Exception as e:
    print(f"Error loading model: {e}")

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
    reset: bool = True 

@app.post("/generate")
async def generate_endpoint(req: GenerateRequest):
    
    def iter_generation():
        # --- Exact Logic from live_base_server.py text_generator() ---
        
        # 1. Initial Seed (Equivalent to state["reset_trigger"] logic)
        seed_text = random.choice(SEEDS)
        inputs = tokenizer(text=seed_text, return_tensors="pt")
        input_ids = inputs.input_ids 
        
        current_count = 0
        
        # Send initial seed
        yield json.dumps({"text": seed_text, "count": 0}) + "\n"
        
        while True:
            try:
                # Check Reset Limit
                if current_count >= MAX_TOKENS_BEFORE_RESET:
                    seed_text = random.choice(SEEDS)
                    inputs = tokenizer(text=seed_text, return_tensors="pt")
                    input_ids = inputs.input_ids
                    current_count = 0
                    
                    reset_msg = f"\n\n[AUTO-RESET: MEMORY FLUSH]\n{seed_text}"
                    yield json.dumps({"text": reset_msg, "count": 0}) + "\n"
                    continue

                # 2. Get Current State (from params)
                current_temp = req.temp
                max_ctx = max(1, req.context)
                
                # 3. Sliding Window
                if input_ids.shape[1] > max_ctx:
                    input_ids = input_ids[:, -max_ctx:]
                    
                # 4. Manual Inference (Exactly as live_base_server.py)
                with torch.no_grad(): 
                    outputs = model(input_ids=input_ids)
                    next_token_logits = outputs.logits[:, -1, :]
                    
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
                    
                # 5. Decode
                new_text = tokenizer.decode(next_token[0], skip_special_tokens=True)
                
                # Yield
                current_count += 1
                yield json.dumps({"text": new_text, "count": current_count}) + "\n"
                
                # 6. Update Global State (Local variable here)
                input_ids = torch.cat([input_ids, next_token], dim=-1)
                
                # Speed control
                time.sleep(0.05)

            except Exception as e:
                print(f"Gen Error: {e}")
                break

    return StreamingResponse(iter_generation(), media_type="application/x-ndjson")

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
