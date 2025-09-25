from __future__ import annotations
import json, requests, time, re
from typing import Tuple, List, Dict, Any
from .config import LLM_URL, REQUEST_TIMEOUT, FIRST_CALL_NPRED
from .config import allowed_destinations

def _json_coerce(s: str) -> dict:
    """Robustly extract the first JSON object containing an "actions" key."""
    if not isinstance(s, str):
        return {"actions": [], "error": "non_string_input"}
    txt = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s.strip())

    # 1) Tentative directe
    try:
        obj = json.loads(txt)
        return obj if isinstance(obj, dict) else {"actions": [], "error": "not_dict_root"}
    except Exception:
        pass

    # 2) Scan for the first balanced JSON block that references "actions"
    def _first_balanced_with_actions(t: str) -> str | None:
        i = 0
        n = len(t)
        in_str = False
        esc = False
        depth = 0
        start = -1
        while i < n:
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == '}':
                    if depth > 0:
                        depth -= 1
                        if depth == 0 and start != -1:
                            frag = t[start:i+1]
                            if '"actions"' in frag:
                                return frag
            i += 1
        return None

    frag = _first_balanced_with_actions(txt)
    if frag:
        try:
            obj = json.loads(frag)
            return obj if isinstance(obj, dict) else {"actions": [], "error": "not_dict_root"}
        except Exception:
            pass

    # 3) Fallbacks simples
    m = re.search(r'\{.*?\}', txt, flags=re.S)
    if m:
        frag = m.group(0)
        try:
            obj = json.loads(frag)
            return obj if isinstance(obj, dict) else {"actions": [], "error": "not_dict_root"}
        except Exception:
            return {"actions": [], "error": "parse_coerce_fail"}
    return {"actions": [], "error": "no_braces"}

def llm_json(prompt: str, n_predict: int = FIRST_CALL_NPRED, timeout: int = REQUEST_TIMEOUT) -> Tuple[dict, str]:
    """Call the model deterministically and return (parsed_actions, raw_text)."""
    base_payload = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0,
        "top_p": 0,
        "stream": False,
    }
    raw_text = ""

    def post(payload):
        nonlocal raw_text
        r = requests.post(LLM_URL, json=payload, timeout=timeout, headers={"Content-Type": "application/json"})
        if r.status_code >= 400:
            raw_text = r.text if isinstance(r.text, str) else ""
            return None, raw_text
        try:
            body = r.json()
            txt = body.get("content")
            if txt is None and "choices" in body and body["choices"]:
                txt = body["choices"][0].get("text", "")
            if not isinstance(txt, str):
                txt = str(txt)
            raw_text = txt.strip()
            parsed = _json_coerce(raw_text)
            return parsed, None
        except Exception as e:
            raw_text = r.text if isinstance(r.text, str) else ""
            return {"actions": [], "error": f"parse_error:{e}"}, None

    for attempt in range(3):
        payload = dict(base_payload)
        if attempt == 0:
            # Stop tokens pour limiter le bruit si le backend les supporte
            payload["stop"] = ["</s>", "\n\n", "\nOBSERVATION:", "\nRECENT_TOOL_OBS:"]
        elif attempt == 1:
            payload.pop("stop", None)
        else:
            # Dernier essai avec troncature de prompt
            payload["prompt"] = prompt[:12000]

        try:
            resp, errtxt = post(payload)
            if resp is not None:
                return resp, raw_text
            time.sleep(1)
        except requests.exceptions.ReadTimeout:
            timeout += 120
            time.sleep(2)
        except Exception as e:
            return {"actions": [], "error": f"llm_error:{e}"}, raw_text

    return {"actions": [], "error": "llm_400_or_timeout"}, raw_text

def _roots_from_patterns(pats: List[str]) -> List[str]:
    """
    Convertit les patterns de allowed_destinations() en racines canoniques que le runner attend :
      'Documents/*' -> 'Documents'
      'Media/*'     -> 'Media'
      'Projects'    -> 'Projects'
    """
    roots: List[str] = []
    for p in pats or []:
        head = str(p).split("/", 1)[0].strip()
        if head and head not in roots:
            roots.append(head)
    canon = {"documents": "Documents", "media": "Media", "projects": "Projects"}
    return [canon.get(r.lower(), r) for r in roots]

def force_decision_once(obs_current: Dict[str, Any], mem: List[dict]) -> Tuple[dict, str]:
    """Send a stripped-down DECIDE prompt that enforces valid destinations."""
    allowed_roots = _roots_from_patterns(allowed_destinations())

    hard_system = (
        'You MUST return a single minified JSON object with exactly one action inside {"actions":[ ... ]} and nothing else. '
        'When DESTINATION_TREES are present, return EXACTLY ONE {"tool":"plan_move", ...}. '
        f'destination_root MUST be EXACTLY one of: {", ".join(allowed_roots)}. '
        'Put nested folders ONLY into "subpath" (never into destination_root). '
        'Never write to the root directly; always choose/reuse/create a subfolder via "subpath". '
        'Do NOT rename files or directories; keep the original basename (ASCII sanitize only). '
        'If the target is a media file inside a folder with multiple related media files, move the parent folder instead of the single file. '
    )

    prompt = (
        hard_system
        + "\nRECENT_TOOL_OBS:\n" + json.dumps(mem[-8:], ensure_ascii=False)
        + "\nOBSERVATION:\n" + json.dumps(obs_current, ensure_ascii=False)
    )
    return llm_json(prompt, n_predict=64, timeout=REQUEST_TIMEOUT)
