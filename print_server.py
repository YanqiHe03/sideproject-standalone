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

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from main.html

# --- Printer Configuration ---
PRINTER_MODEL = 'QL-650TD'
# Run `brother_ql -b pyusb discover` to find your printer's USB ID
PRINTER_IDENTIFIER = 'usb://0x04f9:0x20c0'  # Update this for your system
LABEL_WIDTH = 696  # 62mm continuous label width in pixels

def get_monospace_font(font_size):
    """Get a monospace font that works across platforms"""
    system = platform.system()
    
    # Try platform-specific fonts first
    font_paths = []
    if system == 'Darwin':  # macOS
        font_paths = [
            '/System/Library/Fonts/Monaco.dfont',
            '/System/Library/Fonts/Menlo.ttc',
            '/Library/Fonts/Courier New.ttf',
        ]
    elif system == 'Windows':
        font_paths = [
            'C:/Windows/Fonts/consola.ttf',
            'C:/Windows/Fonts/cour.ttf',
        ]
    else:  # Linux
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
            '/usr/share/fonts/TTF/DejaVuSansMono.ttf',
        ]
    
    for path in font_paths:
        try:
            return ImageFont.truetype(path, font_size)
        except:
            continue
    
    # Fallback to default
    return ImageFont.load_default()

def create_label_image(text, font_size=20, margin=20):
    """Generate a label image with monospace font for Brother QL printer"""
    width = LABEL_WIDTH
    
    # Load monospace font (cross-platform)
    font = get_monospace_font(font_size)
    
    # Calculate characters per line (approximate for monospace)
    chars_per_line = int((width - 2 * margin) / (font_size * 0.6))
    wrapped = textwrap.fill(text, width=chars_per_line)
    lines = wrapped.split('\n')
    
    # Calculate height
    line_height = int(font_size * 1.3)
    height = len(lines) * line_height + 2 * margin
    height = max(height, 100)  # Minimum height
    
    # Create image (grayscale, white background)
    img = Image.new('L', (width, height), 255)
    draw = ImageDraw.Draw(img)
    
    # Draw text
    y = margin
    for line in lines:
        draw.text((margin, y), line, font=font, fill=0)
        y += line_height
    
    return img

@app.route('/print', methods=['POST'])
def print_text():
    """Print text to Brother QL-600 label printer"""
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

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'printer': PRINTER_MODEL})

if __name__ == '__main__':
    print(f"Print Server starting...")
    print(f"Printer: {PRINTER_MODEL} at {PRINTER_IDENTIFIER}")
    print(f"Listening on http://localhost:5001")
    app.run(host='127.0.0.1', port=5001, debug=False)
