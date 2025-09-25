import os, re, shutil, socket, sys, time, pathlib, unicodedata
from typing import Optional, Deque
from collections import deque
from unidecode import unidecode
from .config import ROOT, DRY_RUN


# Keep filesystem paths normalized (handles macOS NFD vs NFC differences).
MAC_NORM = "NFD" if sys.platform == "darwin" else "NFC"


def fs_norm_path(path: str) -> str:
    """Return a normalized filesystem path with consistent Unicode normalization."""
    return os.path.normpath(unicodedata.normalize(MAC_NORM, path))

def safe_ascii(s:str)->str:
    s = unidecode(s)
    s = re.sub(r"[^\w.\-() ]+","_", s).strip()
    s = re.sub(r"\s+"," ", s).strip()
    return s or "unnamed"

def safe_move(src: pathlib.Path, dst_dir: pathlib.Path, new_name:Optional[str]=None) -> str:
    dst_dir.mkdir(parents=True, exist_ok=True)
    name = safe_ascii(new_name or src.name)
    target = dst_dir / name
    i = 1
    while target.exists():
        target = dst_dir / (f"{target.stem} ({i}){target.suffix}")
        i += 1
    if not DRY_RUN:
        shutil.move(str(src), str(target))
    return str(target)

def ensure(dst_root:str, subpath:Optional[str]):
    base = ROOT
    for part in dst_root.split("/"):
        if not part: continue
        base = base/part
    if subpath:
        base = base/safe_ascii(subpath)
    base.mkdir(parents=True, exist_ok=True)
    return base

def wait_port(host="127.0.0.1", port=8080, timeout=120) -> bool:
    t0=time.time()
    while time.time()-t0<timeout:
        try:
            with socket.create_connection((host,port), timeout=1):
                return True
        except OSError:
            time.sleep(1)
    return False

def path_exists(p: str) -> bool:
    try:
        return pathlib.Path(p).exists()
    except Exception:
        return False

def purge_queue_under(queue: Deque[str], moved_path: pathlib.Path):
    try:
        moved_str = str(moved_path.resolve())
    except Exception:
        moved_str = str(moved_path)
    keep = deque()
    while queue:
        q_str = queue.popleft()
        try:
            q_res = str(pathlib.Path(q_str).resolve())
        except Exception:
            q_res = q_str
        if q_res == moved_str or q_res.startswith(moved_str + os.sep):
            continue
        keep.append(q_str)
    queue.extend(keep)

def _cap_txt(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit]
