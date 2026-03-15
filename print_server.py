"""
Print Server for Brother QL-600.
Works on Mac, Linux, and Windows (with Zadig driver).
"""

import base64
import platform
import threading
import time
import traceback
from io import BytesIO

from flask import Flask, request, jsonify
from flask_cors import CORS
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import send
from PIL import Image, ImageDraw, ImageFont

from config import (
    PUBLIC_DIR, PRINTER_MODEL, PRINTER_IDENTIFIER,
    LABEL_WIDTH, KEEPALIVE_INTERVAL, PRINT_HOST, PRINT_PORT,
)

import os

app = Flask(__name__)
CORS(app)


# --- Keep-Alive Thread ---
def keepalive_worker():
    """Background thread that pings the printer periodically to prevent auto-shutdown."""
    while True:
        time.sleep(KEEPALIVE_INTERVAL)
        try:
            import usb.core
            dev = usb.core.find(idVendor=0x04F9, idProduct=0x20C0)
            if dev:
                _ = dev.bDeviceClass
                print(f"[KEEPALIVE] Pinged printer at {time.strftime('%H:%M:%S')}")
            else:
                print("[KEEPALIVE] Printer not found")
        except Exception as e:
            print(f"[KEEPALIVE] Error: {e}")


keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
keepalive_thread.start()
print(f"[KEEPALIVE] Started (interval: {KEEPALIVE_INTERVAL}s)")


# --- Font resolution ---
def _build_font_paths():
    """Build ordered list of font paths to try, platform-aware."""
    paths = [
        # Project bundled font — highest priority
        os.path.join(PUBLIC_DIR, "unifont.otf"),
    ]

    system = platform.system()

    # Cross-platform common locations
    common = [
        "/usr/share/fonts/truetype/unifont/unifont.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]

    if system == "Darwin":
        paths += [
            "/Library/Fonts/unifont.otf",
            os.path.expanduser("~/Library/Fonts/unifont.otf"),
            "/Library/Fonts/NotoSansMono-Regular.ttf",
            "/Library/Fonts/Sarasa-Mono-SC-Regular.ttf",
            "/Library/Fonts/SarasaMonoSC-Regular.ttf",
            "/Library/Fonts/DejaVuSansMono.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Monaco.dfont",
        ]
    elif system == "Windows":
        paths += [
            "C:/Windows/Fonts/unifont.ttf",
            "C:/Windows/Fonts/NotoSansMono-Regular.ttf",
            "C:/Windows/Fonts/SarasaMonoSC-Regular.ttf",
            "C:/Windows/Fonts/DejaVuSansMono.ttf",
            "C:/Windows/Fonts/seguisym.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/consola.ttf",
        ]
    else:  # Linux
        paths += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]

    paths += common
    return paths


FONT_PATHS = _build_font_paths()


def get_font(font_size):
    """Get a monospace font that supports multi-language (Unicode) across platforms."""
    for path in FONT_PATHS:
        try:
            font = ImageFont.truetype(path, font_size)
            print(f"[FONT] Using: {path}")
            return font
        except Exception:
            continue

    print("[FONT] Warning: Using default font (limited Unicode support)")
    return ImageFont.load_default()


def create_label_image(text, margin=20):
    """Generate a square label image matching main.html canvas layout."""
    size = LABEL_WIDTH

    font_size = 25
    min_font_size = 12

    while font_size >= min_font_size:
        font = get_font(font_size)
        line_height = int(font_size * 1.4)

        max_width = size - 2 * margin
        max_height = size - 2 * margin
        lines = []

        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current_line = ""
            for char in paragraph:
                test_line = current_line + char
                bbox = font.getbbox(test_line)
                text_width = bbox[2] - bbox[0] if bbox else 0
                if text_width <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = char
            if current_line:
                lines.append(current_line)

        total_height = len(lines) * line_height
        if total_height <= max_height:
            break
        font_size -= 1

    img = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(img)

    y = margin
    for line in lines:
        if y + line_height > size - margin:
            break
        draw.text((margin, y), line, font=font, fill=0)
        y += line_height

    return img


# --- Routes ---
@app.route("/print", methods=["POST"])
def print_text():
    """Print text to Brother QL label printer."""
    data = request.json
    text = data.get("text", "")

    if not text.strip():
        return jsonify({"status": "empty", "message": "No text to print"}), 400

    try:
        img = create_label_image(text)
        qlr = BrotherQLRaster(PRINTER_MODEL)
        instructions = convert(qlr, [img], "62")
        send(instructions, PRINTER_IDENTIFIER, "pyusb")

        print(f"[PRINT] Sent {len(text)} chars to printer")
        return jsonify({"status": "ok", "chars": len(text)})
    except Exception as e:
        traceback.print_exc()
        print(f"[PRINT ERROR] {type(e).__name__}: {e}")
        return jsonify({"status": "error", "message": f"{type(e).__name__}: {e}"}), 500


@app.route("/print-image", methods=["POST"])
def print_image():
    """Print a screenshot image directly."""
    data = request.json
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({"status": "empty", "message": "No image data"}), 400

    try:
        if "," in image_data:
            image_data = image_data.split(",")[1]

        image_bytes = base64.b64decode(image_data)
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("L")

        target_width = LABEL_WIDTH
        aspect_ratio = img.height / img.width
        target_height = int(target_width * aspect_ratio)
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        qlr = BrotherQLRaster(PRINTER_MODEL)
        instructions = convert(qlr, [img], "62")
        send(instructions, PRINTER_IDENTIFIER, "pyusb")

        print(f"[PRINT-IMAGE] Sent {img.width}x{img.height} image to printer")
        return jsonify({"status": "ok", "width": img.width, "height": img.height})
    except Exception as e:
        traceback.print_exc()
        print(f"[PRINT-IMAGE ERROR] {type(e).__name__}: {e}")
        return jsonify({"status": "error", "message": f"{type(e).__name__}: {e}"}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "printer": PRINTER_MODEL})


if __name__ == "__main__":
    print(f"Print Server starting...")
    print(f"Printer: {PRINTER_MODEL} at {PRINTER_IDENTIFIER}")
    print(f"Listening on http://localhost:{PRINT_PORT}")
    app.run(host=PRINT_HOST, port=PRINT_PORT, debug=False)
