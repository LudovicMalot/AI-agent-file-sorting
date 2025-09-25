import subprocess, pathlib, mimetypes
from typing import Optional
from PIL import Image

# Generic media grouping by MIME type
def ext_group_of(path: pathlib.Path) -> str:
    # Return one of: "audio" | "video" | "image" | "document" | "other"
    ext = path.suffix.lower()
    if ext in {".pdf",".doc",".docx",".pages",".txt",".rtf",".md",".numbers",".xlsx",".xls",".csv"}:
        return "document"
    if ext in {".png",".jpg",".jpeg",".heic",".webp",".gif",".tiff"}:
        return "image"
    if ext in {".mp3",".flac",".wav",".aac",".m4a",".ogg"}:
        return "audio"
    if ext in {".mp4",".mkv",".mov",".avi",".webm",".m4v"}:
        return "video"
    # fallback via mimetypes
    mt, _ = mimetypes.guess_type(str(path))
    if not mt: return "other"
    if mt.startswith("audio/"): return "audio"
    if mt.startswith("video/"): return "video"
    if mt.startswith("image/"): return "image"
    if mt in ("application/pdf","text/plain","application/msword","application/vnd.openxmlformats-officedocument"):
        return "document"
    return "other"

def ffprobe_duration_seconds(path: pathlib.Path) -> Optional[float]:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=nokey=1:noprint_wrappers=1", str(path)],
            text=True, timeout=20
        ).strip()
        return float(out) if out else None
    except Exception:
        return None

def read_pdf_text(path: pathlib.Path, limit=2000)->str:
    try:
        from pdfminer.high_level import extract_text
        t = extract_text(str(path)) or ""
        return t[:limit]
    except Exception:
        return ""

def ocr_image(path: pathlib.Path, limit=2000)->str:
    try:
        import pytesseract
        from PIL import Image
        t = pytesseract.image_to_string(Image.open(path)) or ""
        return t[:limit]
    except Exception:
        return ""

def is_media_file(p: pathlib.Path) -> bool:
    return ext_group_of(p) in {"audio","video"} or p.suffix.lower()==".srt"

def looks_like_series_folder(folder: pathlib.Path) -> bool:
    try:
        if not folder.is_dir():
            return False
        n_media = 0
        for it in folder.iterdir():
            if it.is_file() and is_media_file(it):
                n_media += 1
                if n_media >= 2:
                    return True
        return False
    except Exception:
        return False
    
def _png_has_alpha(img: Image.Image) -> bool:
    return ("A" in img.getbands()) or (img.mode in ("LA", "RGBA", "PA"))

def _image_complexity_score(img: Image.Image, sample_step: int = 4) -> float:
    """Return a simple 0..1 score based on colour diversity per sampled pixel."""
    w, h = img.size
    pixels = 0
    colors = set()
    px = img.convert("RGBA").load()
    for y in range(0, h, sample_step):
        for x in range(0, w, sample_step):
            colors.add(px[x, y])
            pixels += 1
    # The more diverse the colours, the more "photo-like" the asset is.
    return min(1.0, len(colors) / max(1, pixels))

def _transparent_ratio(img: Image.Image, sample_step: int = 2) -> float:
    if not _png_has_alpha(img):
        return 0.0
    w, h = img.size
    px = img.convert("RGBA").load()
    tot = 0
    trans = 0
    for y in range(0, h, sample_step):
        for x in range(0, w, sample_step):
            tot += 1
            if px[x, y][3] < 10:
                trans += 1
    return trans / max(1, tot)

def is_graphic_asset_png(path: pathlib.Path) -> bool:
    """Heuristic to detect UI assets (logos/icons) versus photographic images."""
    if path.suffix.lower() != ".png":
        return False
    try:
        with Image.open(path) as img:
            w, h = img.size
            area = w * h
            alpha = _png_has_alpha(img)
            trans = _transparent_ratio(img)          # 0..1
            cx = _image_complexity_score(img)        # 0..1

            # Conservative thresholds tuned to avoid false positives.
            smallish = (max(w, h) <= 1024) or (area <= 512 * 512)
            very_small = (max(w, h) <= 256) or (area <= 128 * 128)
            alpha_heavy = alpha and (trans >= 0.15 or very_small)
            low_complex = cx <= 0.25 or very_small

            # Logos/icons/effects are typically small, transparent, and simple.
            return (smallish and alpha_heavy and low_complex) or very_small
    except Exception:
        return False
