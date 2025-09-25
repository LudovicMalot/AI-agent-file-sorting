import json as _json
from typing import Any, Dict, List

from .actions import allowed_root_names
from .config import MEM_LIMIT

def _system_prompt() -> str:
    allowed = ", ".join(allowed_root_names())
    return f"""You are a file-sorting agent.

Respond only with ONE minified JSON: {{"actions":[ ... ]}} and nothing else.

Action schema (absolute paths only):
{{"tool":"list_dir","path":"<abs dir>"}} |
{{"tool":"inspect_file","path":"<abs file>"}} |
{{"tool":"plan_move","src":"<abs file or dir>","destination_root":"<one of: {allowed}>","subpath":"<short or empty>","filename":"<ascii with ext>"}}

Guidelines:
- Prefer reusing EXISTING folders from DESTINATION_TREES when they fit. Create a new subfolder only if clearly beneficial.
- Consider semantics: personal records / IDs (even as images/PDF scans) go under appropriate Documents categories.
- For video series: if multiple related media files sit together, prefer moving the parent folder (season/show).
- Keep original basenames (ASCII sanitize only). Do not rename internals.

DECIDE MODE REQUIREMENTS (DESTINATION_TREES are present):
- You MUST return exactly one action and it MUST be {{"tool":"plan_move", ...}}.
- Do NOT return inspect_file or list_dir in DECIDE mode.
- Do NOT place into the root of Documents, Media, or Projects; always choose or create a meaningful subfolder.
"""

def build_prompt(mem: List[dict], obs: Dict[str, Any], tight: bool = False) -> str:
    base = _system_prompt()
    if tight:
        mem_cut = [m for m in mem[-4:] if m.get("tool") in ("list_dir", "inspect_file")]
        obs_min = {"CURRENT_TARGET": obs["CURRENT_TARGET"], "DESTINATION_TREES": {}}
        return base + "\nRECENT_TOOL_OBS:\n" + json_dumps(mem_cut) + "\nOBSERVATION:\n" + json_dumps(obs_min)
    return base + "\nRECENT_TOOL_OBS:\n" + json_dumps(mem[-MEM_LIMIT:]) + "\nOBSERVATION:\n" + json_dumps(obs)

def json_dumps(obj) -> str:
    return _json.dumps(obj, ensure_ascii=False)
