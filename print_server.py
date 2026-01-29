"""
Print Server for Brother QL-600
Works on Mac, Linux, and Windows (with Zadig driver).
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import send
from PIL import Image, ImageDraw, ImageFont
import textwrap
import platform
import os
import threading
import time

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# --- Keep-Alive Thread ---
KEEPALIVE_INTERVAL = 180  # seconds (3 minutes)

def keepalive_worker():
    """Background thread that pings the printer periodically to prevent auto-shutdown"""
    while True:
        time.sleep(KEEPALIVE_INTERVAL)
        try:
            # Just open and close connection to keep printer awake
            import usb.core
            # Brother QL-600 USB IDs
            dev = usb.core.find(idVendor=0x04f9, idProduct=0x20c0)
            if dev:
                # Reading device info is enough to keep it awake
                _ = dev.bDeviceClass
                print(f"[KEEPALIVE] Pinged printer at {time.strftime('%H:%M:%S')}")
            else:
                print("[KEEPALIVE] Printer not found")
        except Exception as e:
            print(f"[KEEPALIVE] Error: {e}")

# Start keepalive thread
keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
keepalive_thread.start()
print(f"[KEEPALIVE] Started (interval: {KEEPALIVE_INTERVAL}s)")
CORS(app)  # Allow cross-origin requests from main.html

# --- Printer Configuration ---
PRINTER_MODEL = 'QL-650TD'
# Run `brother_ql -b pyusb discover` to find your printer's USB ID
PRINTER_IDENTIFIER = 'usb://0x04f9:0x20c0'  # Update this for your system
LABEL_WIDTH = 696  # 62mm continuous label width in pixels

def get_font(font_size):
    """Get a monospace font that supports multi-language (Unicode) across platforms"""
    system = platform.system()
    
    # Priority: Fonts with widest Unicode coverage
    font_paths = []
    
    # Best multi-language monospace fonts (need to be installed)
    universal_fonts = [
        # Project's own font (in public folder) - highest priority
        os.path.join(SCRIPT_DIR, 'public', 'unifont.otf'),
        
        # GNU Unifont - system installed locations
        '/Users/grmdhe/Library/Fonts/unifont.otf',
        '/Library/Fonts/unifont.otf',
        'C:/Windows/Fonts/unifont.ttf',
        '/usr/share/fonts/truetype/unifont/unifont.ttf',
        
        # Noto Sans Mono - Google's universal font
        '/Library/Fonts/NotoSansMono-Regular.ttf',
        'C:/Windows/Fonts/NotoSansMono-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf',
        
        # Sarasa Gothic (更纱黑体) - CJK + Latin
        '/Library/Fonts/Sarasa-Mono-SC-Regular.ttf',
        '/Library/Fonts/SarasaMonoSC-Regular.ttf',
        'C:/Windows/Fonts/SarasaMonoSC-Regular.ttf',
        
        # DejaVu Sans Mono - good Latin + some symbols
        '/Library/Fonts/DejaVuSansMono.ttf',
        'C:/Windows/Fonts/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    ]
    font_paths.extend(universal_fonts)
    
    # Platform-specific fallbacks (less coverage but always available)
    if system == 'Darwin':  # macOS
        font_paths.extend([
            '/Library/Fonts/Arial Unicode.ttf',             # Good Unicode coverage
            '/System/Library/Fonts/Apple Color Emoji.ttc',  # For emoji
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/Monaco.dfont',
        ])
    elif system == 'Windows':
        font_paths.extend([
            'C:/Windows/Fonts/seguisym.ttf',  # Segoe UI Symbol
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/consola.ttf',
        ])
    else:  # Linux
        font_paths.extend([
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/freefont/FreeMono.ttf',
        ])
    
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, font_size)
            print(f"[FONT] Using: {path}")
            return font
        except:
            continue
    
    print("[FONT] Warning: Using default font (limited Unicode support)")
    return ImageFont.load_default()

def create_label_image(text, margin=20):
    """Generate a SQUARE label image matching main.html canvas layout"""
    # Square dimensions (62mm x 62mm)
    size = LABEL_WIDTH  # 696px = 62mm
    
    # Start with a base font size and adjust if needed to fit
    font_size = 25
    min_font_size = 12
    
    while font_size >= min_font_size:
        font = get_font(font_size)
        line_height = int(font_size * 1.4)
        
        # Calculate text wrapping using actual font measurements
        max_width = size - 2 * margin
        max_height = size - 2 * margin
        lines = []
        
        for paragraph in text.split('\n'):
            if not paragraph:
                lines.append('')
                continue
            current_line = ''
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
        
        # Check if text fits in the square
        total_height = len(lines) * line_height
        if total_height <= max_height:
            break  # Font size is good
        
        # Try smaller font
        font_size -= 1
    
    # Create square image (grayscale, white background)
    img = Image.new('L', (size, size), 255)
    draw = ImageDraw.Draw(img)
    
    # Calculate vertical centering (optional - can remove if you want top-aligned)
    total_text_height = len(lines) * line_height
    start_y = margin  # Top-aligned like main.html
    
    # Draw text
    y = start_y
    for line in lines:
        if y + line_height > size - margin:
            break  # Stop if we'd overflow
        draw.text((margin, y), line, font=font, fill=0)
        y += line_height
    
    return img

@app.route('/print', methods=['POST'])
def print_text():
    """Print text to Brother QL-600 label printer (legacy endpoint)"""
    data = request.json
    text = data.get('text', '')
    
    if not text.strip():
        return jsonify({'status': 'empty', 'message': 'No text to print'}), 400
    
    try:
        # Generate label image
        img = create_label_image(text)
        
        # Convert to printer instructions
        qlr = BrotherQLRaster(PRINTER_MODEL)
        instructions = convert(qlr, [img], '62')
        
        # Send to printer (pyusb backend for Windows)
        send(instructions, PRINTER_IDENTIFIER, 'pyusb')
        
        print(f"[PRINT] Sent {len(text)} chars to printer")
        return jsonify({'status': 'ok', 'chars': len(text)})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[PRINT ERROR] {type(e).__name__}: {e}")
        return jsonify({'status': 'error', 'message': f"{type(e).__name__}: {e}"}), 500

@app.route('/print-image', methods=['POST'])
def print_image():
    """Print a screenshot image directly - exact match to what's on screen"""
    import base64
    from io import BytesIO
    
    data = request.json
    image_data = data.get('image', '')
    
    if not image_data:
        return jsonify({'status': 'empty', 'message': 'No image data'}), 400
    
    try:
        # Decode base64 image
        # Format: "data:image/png;base64,xxxxx"
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        image_bytes = base64.b64decode(image_data)
        img = Image.open(BytesIO(image_bytes))
        
        # Convert to grayscale
        img = img.convert('L')
        
        # Resize to fit 62mm width (696px) while maintaining aspect ratio
        target_width = LABEL_WIDTH
        aspect_ratio = img.height / img.width
        target_height = int(target_width * aspect_ratio)
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # Convert to printer instructions
        qlr = BrotherQLRaster(PRINTER_MODEL)
        instructions = convert(qlr, [img], '62')
        
        # Send to printer
        send(instructions, PRINTER_IDENTIFIER, 'pyusb')
        
        print(f"[PRINT-IMAGE] Sent {img.width}x{img.height} image to printer")
        return jsonify({'status': 'ok', 'width': img.width, 'height': img.height})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[PRINT-IMAGE ERROR] {type(e).__name__}: {e}")
        return jsonify({'status': 'error', 'message': f"{type(e).__name__}: {e}"}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'printer': PRINTER_MODEL})

if __name__ == '__main__':
    print(f"Print Server starting...")
    print(f"Printer: {PRINTER_MODEL} at {PRINTER_IDENTIFIER}")
    print(f"Listening on http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=False)
