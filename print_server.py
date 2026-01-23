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

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
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

def create_label_image(text, font_size=25, margin=20):
    """Generate a label image for Brother QL printer with Chinese support"""
    width = LABEL_WIDTH
    
    # Load font with Chinese support (cross-platform)
    font = get_font(font_size)
    
    # Calculate text wrapping using actual font measurements
    max_width = width - 2 * margin
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append('')
            continue
        current_line = ''
        for char in paragraph:
            test_line = current_line + char
            # Get actual text width
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
    
    # Calculate height
    line_height = int(font_size * 1.4)  # Slightly more spacing for readability
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
