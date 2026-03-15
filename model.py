"""
Model loading, device selection, and PCA calibration.
"""

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForCausalLM
from sklearn.decomposition import PCA

from config import MODEL_DIR, PCA_N_COMPONENTS, PCA_CALIBRATION_SENTENCES


def select_device():
    """Auto-detect best available device: MPS > CUDA > CPU."""
    if torch.backends.mps.is_available():
        print("Using MPS (Apple Silicon GPU)")
        return torch.device("mps")
    elif torch.cuda.is_available():
        print("Using CUDA (NVIDIA GPU)")
        return torch.device("cuda")
    else:
        print("Using CPU")
        return torch.device("cpu")


def load_model(device):
    """Load tokenizer and model, move to device."""
    print(f"Loading Model: {MODEL_DIR}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        trust_remote_code=True,
        torch_dtype=torch.float32,
    ).to(device)
    model.eval()
    print("Model loaded.")
    return tokenizer, model


def calibrate_pca(model, tokenizer, device):
    """Run calibration sentences through the model to fit PCA."""
    print("Calibrating Latent Space (PCA)...")
    cal_vectors = []
    with torch.no_grad():
        for sent in PCA_CALIBRATION_SENTENCES:
            inputs = tokenizer(sent, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            outputs = model(**inputs, output_hidden_states=True)
            hidden = outputs.hidden_states[-1].squeeze(0).cpu().float().numpy()
            cal_vectors.append(hidden)

    all_cal_data = np.concatenate(cal_vectors, axis=0)
    pca = PCA(n_components=PCA_N_COMPONENTS)
    pca.fit(all_cal_data)
    print("PCA Calibrated.")
    return pca
