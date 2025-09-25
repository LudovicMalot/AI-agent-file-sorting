#!/usr/bin/env python3
import os, json, pathlib
from typing import Dict, Any, List, Optional
from unidecode import unidecode

# ====== Package directories ======
BASE_DIR = pathlib.Path(__file__).resolve().parent
CFG_DIR  = BASE_DIR / "config"
LOGS     = BASE_DIR / "logs"
CFG_DIR.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

# ====== Data roots ======
HOME  = pathlib.Path.home()
ROOT  = HOME / "_Vault"
INBOX = ROOT / "INBOX"
DOCS  = ROOT / "Documents"
PROJ  = ROOT / "Projects"
MEDIA = ROOT / "Media"
for d in [INBOX, DOCS, PROJ, MEDIA]:
    d.mkdir(parents=True, exist_ok=True)

# ====== Environment / runtime ======
LLM_URL               = os.environ.get("LLM_URL", "http://127.0.0.1:8080/completion")
DRY_RUN               = bool(int(os.environ.get("DRY_RUN", "0")))
MAX_STEPS             = int(os.environ.get("MAX_STEPS", "500"))
REQUEST_TIMEOUT       = int(os.environ.get("REQUEST_TIMEOUT", "180"))
FIRST_CALL_NPRED      = int(os.environ.get("FIRST_CALL_NPRED", "64"))
MEM_LIMIT             = int(os.environ.get("MEM_LIMIT", "8"))
INSPECT_CAP_PER_FILE  = int(os.environ.get("INSPECT_CAP_PER_FILE", "2"))
DIR_LIST_CAP_PER_DIR  = int(os.environ.get("DIR_LIST_CAP_PER_DIR", "1"))
MAX_RETRY_PER_TARGET  = int(os.environ.get("MAX_RETRY_PER_TARGET", "3"))
COOLDOWN_SKIP_SET_SIZE = int(os.environ.get("COOLDOWN_SKIP_SET_SIZE", "2000"))

# Heuristics (default thresholds)
YEAR_DIR_REGEX        = os.environ.get("YEAR_DIR_REGEX", r"^(19|20)\d{2}$")
MIN_SAME_EXT          = int(os.environ.get("MIN_SAME_EXT", "4"))
MIN_SUBTREE_FILES     = int(os.environ.get("MIN_SUBTREE_FILES", "6"))

def _load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _load_config(name: str, default: Any) -> Any:
    """Load user config from *.local.json, falling back to the provided default."""
    local_path = CFG_DIR / f"{name}.local.json"
    data = _load_json(local_path, None)
    if data is not None:
        return data
    return default

# User-provided overrides (config/*.local.json)
PEOPLE_CFG: Dict[str, Any] = _load_config("people", {"people": [], "fallback": ""})
TAXONOMY:   Dict[str, Any] = _load_config("taxonomy", {
    "Documents": ["Identity","Legal","Finance","Housing","Health","Education","Employment","Travel","Family"],
    "Projects": [],
    "Media": ["Movies","Series","Music","Images"]
})

def allowed_destinations() -> List[str]:
    """Return the destination patterns exposed to the agent."""
    # Keep taxonomy.json for UI purposes but do not enforce it at runtime.
    return ["Documents/*", "Media/*", "Projects"]

def normalize_owner_label(label: Optional[str]) -> Optional[str]:
    """Return a canonical owner label if it matches the configured people list."""
    if not label:
        return None
    lbl = unidecode(label).strip().casefold()
    for person in PEOPLE_CFG.get("people", []):
        stored = unidecode(str(person.get("label", ""))).strip().casefold()
        if stored == lbl:
            return person.get("label")
    return None
