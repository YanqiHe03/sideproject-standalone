"""
Centralized configuration for The Side Project.
All tunable constants in one place.
"""

import os

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# --- Model ---
MODEL_DIR = "Qwen/Qwen3-0.6B"
MAX_TOKENS_BEFORE_RESET = 4000
SEEDS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

# --- PCA Calibration ---
PCA_N_COMPONENTS = 3
PCA_CALIBRATION_SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "Artificial intelligence is a branch of computer science.",
    "I am a machine and I am thinking.",
    "Logic, emotion, data, vector, tensor, matrix.",
]

# --- OSC ---
OSC_TARGET_IP = os.environ.get("OSC_TARGET_IP", "100.89.121.111")
OSC_TARGET_PORT = int(os.environ.get("OSC_TARGET_PORT", "7000"))

# --- Servers ---
API_HOST = "0.0.0.0"
API_PORT = 7860
PRINT_HOST = "0.0.0.0"
PRINT_PORT = 5001

# --- Printer ---
PRINTER_MODEL = "QL-650TD"
PRINTER_IDENTIFIER = "usb://0x04f9:0x20c0"
LABEL_WIDTH = 696  # 62mm continuous label width in pixels
KEEPALIVE_INTERVAL = 180  # seconds

# --- Generation defaults ---
TOP_P = 0.92
DEFAULT_DELAY = 0.5
DELAY_RANGE = (0.01, 2.0)
