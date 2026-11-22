import errno
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from tempfile import TemporaryDirectory
from typing import Literal

from .converter import MediaLibrary, verify_converted_film


type FilmAction = Literal["move", "delete_original"]
type FileVersion = tuple[int, int, int, int]


@dataclass(frozen=True)
class ConvertedFilm:
    output: str
    source: str | None
    in_output: bool
    in_library: bool


def staged_without_originals(root: Path, known: set[Path], errors: list[str]) -> set[str]:
    """Find staged films that can still be moved after their original was deleted."""
    found = set()
    for parent, _, names in os.walk(root, onerror=lambda err: errors.append(str(err))):
        folder = Path(parent).relative_to(root)
        for name in names:
            relative = folder / name
            if name.lower().endswith(".ac3.mkv") and relative not in known:
                found.add(relative.as_posix())
    return found


def _managed_path(root: Path, name: str) -> Path:
    relative = Path(name)
    path = root / relative
    if (
        relative.anchor or ".." in relative.parts or relative.suffix.lower() != ".mkv"
        or path.resolve() != path or not path.is_relative_to(root)
    ):
        raise ValueError("File actions require a regular MKV inside its configured folder. Links cannot be managed.")
    return path


def _version(path: Path) -> FileVersion:
    info = path.lstat()
    if path.resolve(strict=True) != path or not S_ISREG(info.st_mode):
        raise ValueError(f"Expected a regular file: {path}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _check_version(path: Path, expected: FileVersion) -> None:
    if _version(path) != expected:
        raise ValueError(f"The file changed during verification. Scan again: {path}")


def _same_bytes(first: Path, second: Path) -> bool:
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as a, second.open("rb") as b:
        while True:
            chunk = a.read(1024 * 1024)
            if chunk != b.read(1024 * 1024):
                return False
            if not chunk:
                return True


def _publish_in_library(staged: Path, target: Path, staged_version: FileVersion) -> FileVersion:
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(target):
        existing = _version(target)
        if staged.parent.samefile(target.parent) and staged.name == target.name:
            raise ValueError("The output and library paths refer to the same directory entry.")
        if staged.samefile(target) or _same_bytes(staged, target):
            return existing  # A previous move may have stopped before removing the staged copy.
        raise FileExistsError(f"A different file already exists at {target}. Both files were kept.")
    try:
        os.link(staged, target)
        return staged_version
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP) and getattr(exc, "winerror", 0) != 17:
            raise
    # Separate Docker mounts can require a copy, even on the same NAS.
    with TemporaryDirectory(dir=target.parent, prefix=".ac3fixer-") as work:
        temp = Path(work) / "move.part"
        shutil.copyfile(staged, temp)
        if not _same_bytes(staged, temp):
            raise ValueError("The copied file failed verification. The staged output was kept.")
        copied = _version(temp)
        os.link(temp, target)
        return copied


def manage_film(library: MediaLibrary, film: ConvertedFilm, action: FilmAction) -> None:
    original = _managed_path(library.source, film.source) if film.source is not None else None
    before = _version(original) if original is not None else None
    staged = _managed_path(library.output, film.output)
    sibling = _managed_path(library.source, film.output)
    deleting = action == "delete_original"
    output = sibling if deleting and film.in_library else staged
    version = _version(output)
    verify_converted_film(output, original, library.source, deleting=deleting)
    _check_version(output, version)
    if original is not None:
        _check_version(original, before)
    if deleting:
        if original is None:
            raise ValueError("The original has already been removed.")
        original.unlink()
    else:
        published = _publish_in_library(staged, sibling, version)
        _check_version(staged, version)
        _check_version(sibling, published)
        staged.unlink()
