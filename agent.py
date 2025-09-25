from __future__ import annotations

import os, json, time, pathlib, collections, math
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from collections import defaultdict, Counter

from .actions import allowed_root_names, sanitize_actions
from .config import INBOX, LOGS, DOCS, MEDIA, PROJ, MAX_STEPS, INSPECT_CAP_PER_FILE
from .llm_io import llm_json
from .tools import tool_list_dir, tool_inspect_file, tool_plan_move
from .utils_fs import fs_norm_path, path_exists, purge_queue_under, safe_ascii
from .utils_media import ext_group_of, is_graphic_asset_png
from .owner import detect_owner_for_path
from .snapshot import tree_snapshot, content_summary_for_dir

# ————————————————————————————————————————————————————————————————————————————
# Cohesion (consensus-based parent escalation)
# ————————————————————————————————————————————————————————————————————————————
class CohesionTracker:
    """Track repeated moves to decide when to escalate an entire parent folder."""

    def __init__(self, k_threshold: int = 3, purity_min: float = 0.8, max_children_cap: int = 500):
        self.k = k_threshold         # minimum number of votes required before escalating
        self.purity = purity_min     # dominant destination must cover at least this share of votes
        self.cap = max_children_cap  # refuse to escalate very large directories (safety)
        self.stats = defaultdict(lambda: {
            "votes": Counter(),      # (dest_root, subpath) -> count
            "exts": Counter(),       # extension histogram for entropy check
            "seen": set(),           # paths already counted for this parent
            "total": 0
        })
        self.already_escalated = set()   # parents escalated once already

    def note(self, parent: pathlib.Path, file_path: pathlib.Path, dest_root: str, subpath: str):
        key = str(parent)
        s = self.stats[key]
        fp = str(file_path)
        if fp in s["seen"]:
            return
        s["seen"].add(fp)
        s["votes"][(dest_root, subpath)] += 1
        s["exts"][file_path.suffix.lower()] += 1
        s["total"] += 1

    def consensus(self, parent: pathlib.Path) -> Optional[tuple]:
        key = str(parent)
        if key in self.already_escalated:
            return None
        s = self.stats.get(key)
        if not s or s["total"] < self.k:
            return None
        (dest, cnt) = s["votes"].most_common(1)[0]
        purity = cnt / s["total"]
        if purity < self.purity:
            return None
        # Low entropy means the directory mostly contains the same file types.
        total = sum(s["exts"].values())
        ent = -sum((c/total)*math.log2(c/total) for c in s["exts"].values() if c)
        if ent > 1.0:
            return None
        # Skip escalation if the directory is too large.
        try:
            children = [p for p in parent.iterdir() if not p.name.startswith(".")]
            if len(children) > self.cap:
                return None
        except Exception:
            pass
        return dest  # (destination_root, subpath)

# —— constants ——
ST_LIGHT, ST_DECIDE = 0, 1
SNAP_TTL_STEPS = 10
DOC_TREE_DEPTH, MEDIA_TREE_DEPTH, PROJ_TREE_DEPTH = 3, 2, 1
DIR_CAP = 40

# Dev diagnostics
DEV_LOG_RAW_LLM = True

# ————————————————————————————————————————————————————————————————————————————
# Dependency/vendor directories guard
# ————————————————————————————————————————————————————————————————————————————
DEP_DIR_NAMES = {
    "node_modules", "bower_components", "vendor",
    ".venv", "venv", ".pip", ".mypy_cache",
    ".git", ".svn", ".hg", "build", "dist", "target", ".next", ".cache"
}

def _is_in_dep_dir(p: pathlib.Path) -> bool:
    return any(part in DEP_DIR_NAMES for part in p.parts)

# ————————————————————————————————————————————————————————————————————————————
# Prompt construction (tightened)
# ————————————————————————————————————————————————————————————————————————————
def _system_prompt() -> str:
    allowed_str = ", ".join(allowed_root_names())
    return (
        "You are a file-sorting agent.\n\n"
        "Respond only with ONE minified JSON: {\"actions\":[ ... ]} and nothing else.\n\n"
        "Action schema (absolute paths only):\n"
        "{\"tool\":\"list_dir\",\"path\":\"<abs dir>\"} |\n"
        "{\"tool\":\"inspect_file\",\"path\":\"<abs file>\"} |\n"
        "{\"tool\":\"plan_move\",\"src\":\"<abs file or dir>\","
        "\"destination_root\":\"<one of: " + allowed_str + ">\","
        "\"subpath\":\"<short or empty>\",\"filename\":\"<ascii with ext>\"}\n\n"
        "IMPORTANT (DECIDE MODE when DESTINATION_TREES present):\n"
        "- Return EXACTLY ONE action and it MUST be plan_move.\n"
        "- destination_root MUST be EXACTLY one of: " + allowed_str + "\n"
        "- Put nested folders only into subpath, never into destination_root.\n"
        "- Never write into root directly; always choose/reuse/create a subfolder via subpath.\n"
        "- Prefer existing subfolders in DESTINATION_TREES when semantically close (synonyms/translations).\n\n"
        "VALID example (root vs subpath):\n"
        "{\"actions\":[{\"tool\":\"plan_move\",\n"
        "  \"src\":\"/Users/jervis/_Vault/INBOX/Cours/2019-2021/Contrat etudiant/EeContrat_4934_20191125 - copie.pdf\",\n"
        "  \"destination_root\":\"Documents\",\n"
        "  \"subpath\":\"Education/Cours/2019-2021/Contrat etudiant\",\n"
        "  \"filename\":\"EeContrat_4934_20191125 - copie.pdf\"}]}\n"
    )

def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)

def build_prompt(mem: List[dict], obs: Dict[str, Any], *, tight: bool) -> str:
    base = _system_prompt()
    # Keep only most relevant recent tool outputs
    mem_cut: List[dict] = []
    for m in reversed(mem):
        if m.get("tool") in ("list_dir", "inspect_file", "owner_hint", "policy_hint"):
            mem_cut.append(m)
        if len(mem_cut) >= 12:
            break
    mem_cut.reverse()
    dest_trees = obs["DESTINATION_TREES"] if obs.get("DESTINATION_TREES") else {}
    obs_obj = {"CURRENT_TARGET": obs["CURRENT_TARGET"], "DESTINATION_TREES": dest_trees}
    return base + "\nRECENT_TOOL_OBS:\n" + _json_dumps(mem_cut) + "\nOBSERVATION:\n" + _json_dumps(obs_obj)

# ————————————————————————————————————————————————————————————————————————————
# Main runner
# ————————————————————————————————————————————————————————————————————————————
def run():
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    stream_logf = LOGS / f"{ts}_agent.jsonl"
    logf = open(stream_logf, "w", buffering=1, encoding="utf-8")

    def _log(ev: Dict[str, Any]):
        try:
            logf.write(json.dumps(ev, ensure_ascii=False) + "\n")
            logf.flush(); os.fsync(logf.fileno())
        except Exception:
            pass

    # queue init (non-hidden, non-symlink, excluding special folder)
    items = [str(p) for p in INBOX.iterdir() if not p.name.startswith(".") and p.name != "_moved_today" and not p.is_symlink()]
    items.sort(key=lambda s: os.path.basename(s).lower())
    queue = collections.deque(items)
    _log({"event": "start", "queue_size": len(queue), "inbox": str(INBOX), "log": str(stream_logf)})

    stage: Dict[str, int] = {}
    inspected_count: Dict[str, int] = {}
    decide_fail_counts: Dict[str, int] = collections.Counter()

    mem: List[dict] = []
    cohesion = CohesionTracker(k_threshold=3, purity_min=0.8, max_children_cap=500)
    allowed_labels = allowed_root_names()

    snap_cache = {"docs": None, "media": None, "proj": None, "exp_step": 0}
    step = 0

    while queue and step < MAX_STEPS:
        step += 1
        target = pathlib.Path(fs_norm_path(queue[0])); key = str(target)

        # Skip targets that live inside dependency/vendor directories right away.
        if _is_in_dep_dir(target):
            _log({"event": "skip_dependency_dir", "path": str(target)})
            queue.popleft()
            continue

        st = stage.get(key, ST_LIGHT)
        _log({"event": "step", "step": step, "target": key, "stage": ("LIGHT" if st == ST_LIGHT else "DECIDE")})

        # Expand directories deterministically (no LLM)
        if target.is_dir() and not any(m.get("tool") == "list_dir" and m.get("path") == key for m in mem[-64:]):
            res = tool_list_dir(key)
            items_res = res.get("items", [])

            def _keep(pstr: str) -> bool:
                p = pathlib.Path(fs_norm_path(pstr))
                if p.name.startswith("."):
                    return False
                return not _is_in_dep_dir(p)

            kids = sorted([it["path"] for it in items_res if _keep(it["path"])])
            mem.append({"tool": "list_dir", "path": key, "result_count": len(items_res)})
            _log({"event": "list_dir", "step": step, "path": key, "result_count": len(items_res), "kept": len(kids)})

            queue.popleft()
            for c in reversed(kids):
                queue.appendleft(fs_norm_path(c))
            continue

        # Current observation
        cur = {
            "path": key,
            "is_dir": target.is_dir(),
            "name": target.name,
            "ext": target.suffix.lower(),
            "size": (target.stat().st_size if target.exists() else 0),
            "group_hint": (ext_group_of(target) if target.exists() else "other"),
            "png_asset_hint": (is_graphic_asset_png(target) if target.exists() and target.is_file() else False),
        }
        if target.is_dir():
            cur["dir_content_summary"] = content_summary_for_dir(target)
        obs = {"CURRENT_TARGET": cur, "DESTINATION_TREES": {}}

        # STAGE 1: LIGHT (probe; inspect or list only)
        if st == ST_LIGHT:
            prompt = build_prompt(mem, obs, tight=True)
            _log({"event": "prompt_light", "step": step, "prompt_len": len(prompt)})
            plan, raw = llm_json(prompt)
            if DEV_LOG_RAW_LLM:
                _log({"event": "llm_raw_light", "len": len(raw or ""), "head": (raw or "")[:256]})
            acts = sanitize_actions(plan.get("actions") or [], key, allowed_labels, _log)
            acts = [a for a in acts if a.get("tool") in ("inspect_file", "list_dir")]  # no move here

            if not acts:
                if target.is_file() and inspected_count.get(key, 0) == 0:
                    acts = [{"tool": "inspect_file", "path": key}]
                else:
                    _log({"event": "no_progress_rotate", "step": step, "target": key})
                    queue.rotate(-1)
                    continue

            a = acts[0]
            # Guard LIGHT action against dep-dirs
            if _is_in_dep_dir(pathlib.Path(fs_norm_path(a.get("path", key)))):  # type: ignore[arg-type]
                _log({"event": "skip_dependency_dir", "path": a.get("path", key)})
                queue.rotate(-1)
                continue

            if a["tool"] == "inspect_file":
                if inspected_count.get(a["path"], 0) >= INSPECT_CAP_PER_FILE:
                    stage[key] = ST_DECIDE
                    continue
                res = tool_inspect_file(fs_norm_path(a["path"]))  # type: ignore[arg-type]
                slim = {k: v for k, v in res.items() if k in ("group", "ext", "size", "text", "ocr", "duration_s")}
                mem.append({"tool": "inspect_file", "path": fs_norm_path(a["path"]), "result": slim})
                inspected_count[a["path"]] = inspected_count.get(a["path"], 0) + 1
                _log({"event": "inspect_file", "step": step, "path": fs_norm_path(a["path"]), "group": slim.get("group"), "size": slim.get("size")})
                stage[key] = ST_DECIDE
                continue
            else:
                res = tool_list_dir(fs_norm_path(a["path"]))  # type: ignore[arg-type]
                items_res = res.get("items", [])
                def _keep2(pstr: str) -> bool:
                    p = pathlib.Path(fs_norm_path(pstr))
                    if p.name.startswith("."):
                        return False
                    return not _is_in_dep_dir(p)
                kids = sorted([it["path"] for it in items_res if _keep2(it["path"])])
                mem.append({"tool": "list_dir", "path": fs_norm_path(a["path"]), "result_count": len(items_res)})
                _log({"event": "list_dir", "step": step, "path": fs_norm_path(a["path"]), "result_count": len(items_res), "kept": len(kids)})
                queue.popleft()
                for c in reversed(kids):
                    queue.appendleft(fs_norm_path(c))
                stage[key] = ST_DECIDE
                continue

        # STAGE 2: DECIDE (LLM must output plan_move; prompt enforces rule)
        if step >= snap_cache["exp_step"]:
            t0 = time.time()
            snap_cache["docs"]  = tree_snapshot(DOCS,  depth=DOC_TREE_DEPTH,  dir_cap=DIR_CAP)
            snap_cache["media"] = tree_snapshot(MEDIA, depth=MEDIA_TREE_DEPTH,  dir_cap=DIR_CAP)
            snap_cache["proj"]  = tree_snapshot(PROJ,  depth=PROJ_TREE_DEPTH,  dir_cap=DIR_CAP)
            snap_cache["exp_step"] = step + SNAP_TTL_STEPS
            _log({"event": "snap_refresh", "step": step, "ms": int((time.time() - t0) * 1000)})

        obs["DESTINATION_TREES"] = {
            "Documents": snap_cache["docs"],
            "Media": snap_cache["media"],
            "Projects": snap_cache["proj"],
        }

        def _ask_decide(mem_note: str = "") -> List[Dict[str, Any]]:
            if mem_note:
                mem.append({"tool": "policy_hint", "note": mem_note})
            prompt = build_prompt(mem, obs, tight=True)
            _log({"event": "prompt_full", "step": step, "prompt_len": len(prompt)})

            # DECIDE responses can be longer due to DESTINATION_TREES
            plan, raw = llm_json(prompt, n_predict=256)
            if DEV_LOG_RAW_LLM:
                _log({"event": "llm_raw_decide", "len": len(raw or ""), "head": (raw or "")[:256]})
            acts_raw = plan.get("actions")
            _log({"event": "plan_parsed", "actions_len": (len(acts_raw) if isinstance(acts_raw, list) else None), "error": plan.get("error")})

            actions = sanitize_actions(acts_raw or [], key, allowed_labels, _log)
            _log({"event": "plan_sanitized", "count": len(actions)})
            return [a for a in actions if a.get("tool") == "plan_move"]

        moves = _ask_decide()
        if not moves:
            moves = _ask_decide(
                "In DECIDE mode with DESTINATION_TREES, you MUST return exactly one plan_move. "
                "Do not return inspect_file or list_dir. Never dump into root; always pick/reuse/create a subfolder."
            )

        # If still nothing: do not move; rotate & continue (no heuristics).
        if not moves:
            _log({"event": "decide_noncompliance", "step": step, "target": key})
            decide_fail_counts[key] += 1
            queue.rotate(-1)
            continue

        # Execute exactly one plan_move (validated)
        a = moves[0]
        src = fs_norm_path(a.get("src") or "")
        dest_root = a.get("destination_root")
        sub = (a.get("subpath") or "").strip()
        if not src or not dest_root or not path_exists(src):
            _log({"event": "invalid_plan_move", "step": step, "action": a})
            queue.rotate(-1)
            continue

        src_path = pathlib.Path(src)

        # Hard guard: never act inside dependency/vendor dirs
        if _is_in_dep_dir(src_path):
            _log({"event": "skip_dependency_dir", "path": str(src_path)})
            queue.rotate(-1)
            continue

        parent = src_path.parent

        # 1) Record LLM vote for cohesion (skip dep dirs)
        if not _is_in_dep_dir(src_path):
            cohesion.note(parent, src_path, dest_root, sub or "")

        # 2) If there is consensus, escalate and move the parent as a unit (one level; never above INBOX)
        cons = cohesion.consensus(parent)
        if cons and src_path.is_file():
            try:
                if parent.resolve() != INBOX.resolve():
                    dest_root, sub = cons
                    src = fs_norm_path(str(parent))
                    src_path = pathlib.Path(src)
                    a["src"] = src
                    a["destination_root"] = dest_root
                    a["subpath"] = sub
                    a["filename"] = safe_ascii(parent.name)
                    cohesion.already_escalated.add(str(parent))
            except Exception:
                if str(parent) != str(INBOX):
                    dest_root, sub = cons
                    src = fs_norm_path(str(parent))
                    src_path = pathlib.Path(src)
                    a["src"] = src
                    a["destination_root"] = dest_root
                    a["subpath"] = sub
                    a["filename"] = safe_ascii(parent.name)
                    cohesion.already_escalated.add(str(parent))

        # Re-check existence after possible escalation
        if not path_exists(src):
            _log({"event": "invalid_plan_move", "step": step, "action": a, "reason": "src_not_exists_after_escalation"})
            queue.rotate(-1)
            continue

        # optional owner hint
        recent_inspect = next(
            (m.get("result") for m in reversed(mem[-8:])
             if m.get("tool") == "inspect_file" and m.get("path") == str(src_path)),
            None,
        )
        owner = detect_owner_for_path(src_path, recent_inspect) if recent_inspect is not None else None
        if owner:
            mem.append({"tool": "owner_hint", "path": str(src_path), "owner": owner})

        final_name = safe_ascii(src_path.name) if src_path.name else (a.get("filename") or "unnamed")
        _log({
            "event": "plan_move_exec",
            "step": step,
            "src": str(src_path),
            "dest_root": dest_root,
            "subpath": sub,
            "filename": final_name,
            "group_hint": ext_group_of(src_path),
            "owner_hint": owner,
        })

        res = tool_plan_move(src, dest_root, sub, final_name)
        _log({"event": "plan_move_done", "moved_to": res.get("moved_to"), "error": res.get("error")})

        try:
            purge_queue_under(queue, pathlib.Path(src))
        except Exception:
            pass
        if queue and queue[0] == src:
            queue.popleft()
        decide_fail_counts.pop(key, None)

    try:
        logf.close()
    except Exception:
        pass
