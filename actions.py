from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Tuple

from .config import DOCS, INBOX, MEDIA, PROJ, allowed_destinations
from .utils_fs import fs_norm_path, safe_ascii


def _norm_key(value: str) -> str:
    return str(value or "").strip().strip("/").casefold()


def allowed_root_names() -> List[str]:
    """Return the canonical root labels the agent is allowed to target."""
    patterns = allowed_destinations()
    roots: List[str] = []
    for pattern in patterns or []:
        head = str(pattern).split("/", 1)[0].strip()
        if head:
            roots.append(head)

    roots.extend(
        [
            pathlib.Path(DOCS).name,
            pathlib.Path(MEDIA).name,
            pathlib.Path(PROJ).name,
        ]
    )

    canonical = {"documents": "Documents", "media": "Media", "projects": "Projects"}
    unique: Dict[str, str] = {}
    for root in roots:
        key = _norm_key(root)
        label = canonical.get(key, root.strip().strip("/"))
        unique[label] = label
    return sorted(unique.keys())


def root_alias_map() -> Dict[str, str]:
    """Return a mapping of normalized labels to their canonical root name."""
    labels = allowed_root_names()
    aliases: Dict[str, str] = {}
    for label in labels:
        aliases[_norm_key(label)] = label

    # Always support the default English labels even if the config overrides them.
    aliases[_norm_key("Documents")] = "Documents"
    aliases[_norm_key("Media")] = "Media"
    aliases[_norm_key("Projects")] = "Projects"
    return aliases


def _auto_split_root(raw_root: str, alias_map: Dict[str, str]) -> Tuple[str, str, bool]:
    parts = raw_root.split("/", 1)
    if len(parts) == 2:
        base = parts[0].strip()
        extra = parts[1].strip().strip("/")
        norm_base = _norm_key(base)
        if norm_base in alias_map:
            return alias_map[norm_base], extra, True
    return raw_root, "", False


def normalize_plan_move(
    action: Dict[str, Any],
    current_path: str,
    allowed_labels: List[str],
) -> Tuple[Dict[str, Any], List[str]]:
    """Normalize a plan_move action and collect any normalization notes."""
    notes: List[str] = []
    src = (action.get("src") or current_path).strip()
    raw_root = (action.get("destination_root") or "").strip()
    subpath = (action.get("subpath") or "").strip().strip("/")
    filename = (action.get("filename") or pathlib.Path(src).name).strip()

    alias_map = root_alias_map()
    root_key = _norm_key(raw_root)
    root = alias_map.get(root_key, raw_root.strip().strip("/"))

    root, extra, changed = _auto_split_root(root, alias_map)
    if changed:
        notes.append("auto_split_root_subpath")
        subpath = "/".join([part for part in (extra, subpath) if part])

    allowed_set = {_norm_key(label) for label in allowed_labels}
    if _norm_key(root) not in allowed_set:
        return {}, notes + ["invalid_root"]

    if not subpath:
        try:
            rel = pathlib.Path(src).relative_to(INBOX)
            parent = rel.parent
            subpath = str(parent).strip("/") or "Unsorted"
        except Exception:
            subpath = "Unsorted"

    if not filename:
        filename = pathlib.Path(src).name or "unnamed"
    filename = safe_ascii(filename)

    normalized = {
        "tool": "plan_move",
        "src": fs_norm_path(src),
        "destination_root": root,
        "subpath": subpath,
        "filename": filename,
    }
    return normalized, notes


def sanitize_actions(
    actions: List[Dict[str, Any]],
    current_path: str,
    allowed_labels: List[str],
    log_fn,
) -> List[Dict[str, Any]]:
    """Validate and normalize tool calls returned by the model."""
    sane: List[Dict[str, Any]] = []
    current_path = fs_norm_path(current_path)
    for raw_action in actions or []:
        if not isinstance(raw_action, dict):
            log_fn({"event": "drop_bad_action", "reason": "not_dict"})
            continue

        tool = (raw_action.get("tool") or "").strip()
        if tool not in ("list_dir", "inspect_file", "plan_move"):
            log_fn({"event": "drop_bad_action", "reason": "bad_tool", "action": raw_action})
            continue

        if tool in ("list_dir", "inspect_file"):
            path = raw_action.get("path") or current_path
            sane.append({"tool": tool, "path": path})
            continue

        normalized, notes = normalize_plan_move(raw_action, current_path, allowed_labels)
        if normalized.get("src") and normalized.get("destination_root"):
            if not normalized.get("subpath"):
                log_fn({"event": "drop_plan_move", "reason": "empty_subpath", "raw": raw_action})
                continue
            if notes:
                log_fn({"event": "normalize_notes", "notes": notes, "action": normalized})
            sane.append(normalized)
        else:
            log_fn({"event": "invalid_plan_move", "action": raw_action, "notes": notes})
    return sane
