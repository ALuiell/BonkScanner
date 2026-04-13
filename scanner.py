import ctypes
import mss
import pytesseract
from PIL import Image, ImageEnhance, ImageOps

from config import TESSERACT_PATH, REGIONS

# Configure Tesseract path
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def get_screen_resolution():
    """Get the primary monitor resolution using ctypes."""
    user32 = ctypes.windll.user32
    # This prevents Windows from scaling the resolution if display scaling > 100%
    user32.SetProcessDPIAware()
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return width, height


def get_region_for_resolution(width, height):
    """Return the hardcoded region for the detected resolution."""
    if width == 2560 and height == 1440:
        return REGIONS["2K"], "2K"
    elif width == 1920 and height == 1080:
        return REGIONS["FHD"], "FHD"
    else:
        # We don't print here to keep logic separated from UI, but we fallback
        return REGIONS["2K"], "2K (Fallback)"


def preprocess_image(img: Image.Image) -> Image.Image:
    """Advanced preprocessing pipeline for better OCR on small, white text over dark UI."""
    # 1. Upscale: Tesseract needs fonts to be larger (e.g., 30+ pixels high)
    upscaled = img.resize((img.width * 3, img.height * 3), Image.Resampling.LANCZOS)

    # 2. Grayscale: Remove color channels
    gray = ImageOps.grayscale(upscaled)

    # 3. Contrast Boost: Make the white pop and the background darker
    enhancer = ImageEnhance.Contrast(gray)
    high_contrast = enhancer.enhance(3.0)

    # 4. Invert: Tesseract prefers black text on white background
    inverted = ImageOps.invert(high_contrast)

    # 5. Binarization (Threshold): Pure black/white. Adjust threshold if needed.
    threshold = 120
    binary = inverted.point(lambda p: 255 if p > threshold else 0)

    return binary


def capture_and_read(region: dict, sct: mss.mss) -> str:
    """
    Captures the screen at the given region, preprocesses it, 
    and extracts text using Tesseract.
    """
    # Capture Region
    screenshot = sct.grab(region)
    img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    # Preprocess Image
    processed_img = preprocess_image(img)

    # OCR Text Extraction
    text = pytesseract.image_to_string(processed_img, config='--oem 3 --psm 6')
    return text
