"""Settings for the model and its TouchDesigner output.

The browser chooses each display round's temperature, context and delay in
display-session.mjs. Restart the model backend after changing this file.
"""

MODEL_DIR = "Qwen/Qwen3-0.6B-Base"
SEEDS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_TOKENS_BEFORE_RESET = 4000
TOP_P = 0.92
TOP_CANDIDATES = 5

OSC_TARGET_IP = "100.89.121.111"
OSC_TARGET_PORT = 7000

CALIBRATION_SENTENCES = (
    "The quick brown fox jumps over the lazy dog.",
    "Artificial intelligence is a branch of computer science.",
    "I am a machine and I am thinking.",
    "Logic, emotion, data, vector, tensor, matrix.",
)
