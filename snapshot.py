import pathlib, unicodedata, re
from typing import Any, Dict, List, Tuple

IGN = {"_moved_today"}

# ——— content summary ———

def content_summary_for_dir(p: pathlib.Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"path": str(p), "files": 0, "dirs": 0, "ext_hist": []}
    hist: Dict[str, int] = {}
    try:
        for it in p.iterdir():
            if it.name.startswith("."):
                continue
            if it.is_dir():
                if it.name in IGN: continue
                out["dirs"] += 1
            else:
                out["files"] += 1
                hist[it.suffix.lower()] = hist.get(it.suffix.lower(), 0) + 1
    except Exception:
        pass
    out["ext_hist"] = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)
    return out

# ——— tree snapshot (dirs only) ———

def _summarize_dir(dirpath: pathlib.Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"path": str(dirpath), "name": dirpath.name, "dirs": 0}
    try:
        for it in dirpath.iterdir():
            if it.is_dir() and not it.name.startswith(".") and it.name not in IGN:
                out["dirs"] += 1
    except Exception:
        pass
    return out


def tree_snapshot(base: pathlib.Path, depth: int = 1, dir_cap: int = 40) -> Dict[str, Any]:
    def walk(p: pathlib.Path, d: int) -> Dict[str, Any]:
        node = {"name": p.name, "path": str(p), "summary": _summarize_dir(p), "children": []}
        if d == 0:
            return node
        try:
            kids = [it for it in p.iterdir() if it.is_dir() and not it.name.startswith(".") and it.name not in IGN]
            kids.sort(key=lambda x: x.name.lower())
            for i, k in enumerate(kids):
                if i >= dir_cap:
                    break
                node["children"].append(walk(k, d - 1))
        except Exception:
            pass
        return node

    return walk(base, depth)