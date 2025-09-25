from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from .config import DOCS, MEDIA, PROJ
from .utils_fs import safe_ascii
from .utils_media import ext_group_of, ffprobe_duration_seconds, ocr_image, read_pdf_text

_HIDDEN_NAMES = {"_moved_today"}
_ROOT_MAP = {
    "Documents": DOCS,
    "Media": MEDIA,
    "Projects": PROJ,
}


def tool_list_dir(path: str) -> Dict[str, Any]:
    """Return basic metadata for each child entry in a directory."""
    root = Path(path)
    items: List[Dict[str, Any]] = []
    try:
        for entry in root.iterdir():
            name = entry.name
            if name.startswith(".") or name in _HIDDEN_NAMES or entry.is_symlink():
                continue
            stat = entry.stat()
            items.append(
                {
                    "path": str(entry),
                    "name": name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size,
                    "ext": entry.suffix.lower(),
                    "mtime": int(stat.st_mtime),
                }
            )
    except Exception as exc:
        return {"items": [], "error": f"list_dir:{exc}"}
    return {"items": items}


def tool_inspect_file(path: str) -> Dict[str, Any]:
    """Collect lightweight information about a single file."""
    file_path = Path(path)
    if not file_path.exists():
        return {"path": path, "error": "not_found"}

    ext = file_path.suffix.lower()
    data: Dict[str, Any] = {
        "path": str(file_path),
        "name": file_path.name,
        "ext": ext,
        "size": file_path.stat().st_size,
        "group": ext_group_of(file_path),
    }

    try:
        if ext == ".pdf":
            data["text"] = read_pdf_text(file_path, 1500)[:400]
        elif data["group"] == "image":
            data["ocr"] = ocr_image(file_path, 1500)[:400]
        if data["group"] == "video":
            data["duration_s"] = ffprobe_duration_seconds(file_path)
    except Exception as exc:
        data["error"] = f"inspect:{exc}"
    return data


def _destination_root(name: str) -> Path:
    try:
        return _ROOT_MAP[name]
    except KeyError as exc:
        raise ValueError(f"Unknown destination_root: {name}") from exc


def _sanitize_segment(segment: str) -> str:
    segment = segment.replace(os.sep, "_").replace("\x00", "").strip()
    if segment in {"", ".", ".."}:
        return "_"
    return segment


def tool_plan_move(src: str, destination_root: str, subpath: str, filename: str) -> Dict[str, Any]:
    """Move a file or directory to the requested root/subpath location."""
    try:
        src_path = Path(src)
        base = _destination_root(destination_root)

        parts = [part for part in subpath.split("/") if part]
        safe_parts = [_sanitize_segment(part) for part in parts]
        dest_dir = base.joinpath(*safe_parts) if safe_parts else base
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_name = safe_ascii(filename)
        dest_path = dest_dir / safe_name

        if src_path.is_dir() and dest_path.exists():
            shutil.rmtree(dest_path)
        shutil.move(str(src_path), str(dest_path))

        return {"moved_to": str(dest_path), "error": None}
    except Exception as exc:
        return {"moved_to": None, "error": str(exc)}
