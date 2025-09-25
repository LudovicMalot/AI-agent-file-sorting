import pathlib
from typing import Optional
from .config import PEOPLE_CFG, normalize_owner_label

def detect_owner_from_text(text: str) -> Optional[str]:
    if not text: return None
    t = text.lower()
    for person in PEOPLE_CFG.get("people", []):
        label = person.get("label")
        for pat in person.get("patterns", []):
            if pat and pat.lower() in t:
                return label
    return None

def detect_owner_for_path(p: pathlib.Path, recent_inspect: Optional[dict]) -> Optional[str]:
    owner = detect_owner_from_text(p.name)
    if not owner and recent_inspect:
        for k in ("text", "ocr"):
            owner = detect_owner_from_text(recent_inspect.get(k) or "")
            if owner: break
    # owner valide uniquement s’il existe dans people.json
    return normalize_owner_label(owner)