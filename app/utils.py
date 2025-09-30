import os
import re
import shutil
import unicodedata
from pathlib import Path


SAFE_DOT_RE = re.compile(r"\.+")
UNSAFE_RE = re.compile(r"[^a-zA-Z0-9\._-]")




def safe_stem(text: str) -> str:
    # Normalize unicode, collapse spaces to dots, allow letters, digits, dot, underscore, dash
    n = unicodedata.normalize("NFKD", text)
    n = n.replace(" ", ".")
    n = UNSAFE_RE.sub(".", n)
    n = SAFE_DOT_RE.sub(".", n)
    return n




def safe_rename(path: Path) -> Path:
    """Rename file to a safer name (in-place). Returns the new Path (could be unchanged)."""
    parent = path.parent
    new_name = safe_stem(path.name)
    new_path = parent / new_name
    if new_path != path:
        path.rename(new_path)
    return new_path




def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)




def move_to_dir(src: Path, dest_dir: Path) -> Path:
    ensure_dir(dest_dir)
    target = dest_dir / src.name
    return Path(shutil.move(str(src), str(target)))