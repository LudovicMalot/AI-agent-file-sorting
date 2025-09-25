import pathlib
import re

from .config import MIN_SAME_EXT, MIN_SUBTREE_FILES, YEAR_DIR_REGEX

def _is_specific_enough(path: pathlib.Path) -> bool:
    # 1) Check for year-based subfolders
    year_rx = re.compile(YEAR_DIR_REGEX)
    try:
        year_dirs = [c for c in path.iterdir() if c.is_dir() and year_rx.match(c.name)]
        if len(year_dirs) >= 1:
            return True
    except Exception:
        pass
    # 2) Require a minimum number of files with a dominant extension
    try:
        exts = {}
        n_files = 0
        for it in path.rglob("*"):
            if it.is_file():
                n_files += 1
                exts[it.suffix.lower()] = exts.get(it.suffix.lower(), 0) + 1
        if n_files >= MIN_SUBTREE_FILES and (max(exts.values() or [0]) >= MIN_SAME_EXT):
            return True
    except Exception:
        pass
    return False

def remove_empty_dirs(base: pathlib.Path):
    if not base.exists() or not base.is_dir():
        return
    for child in list(base.iterdir()):
        if child.name == "_moved_today":   # skip special drop folder
            continue
        if child.is_symlink():
            continue
        if child.is_dir():
            remove_empty_dirs(child)
            try:
                child.rmdir()
            except OSError:
                pass
