import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


from .utils import safe_rename, ensure_dir, move_to_dir

@dataclass
class MediaJob:
    src: Path
    out: Path
    will_convert: bool
    reason: str




def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)




def has_ac3_audio(path: Path) -> bool:
    # Use ffprobe JSON to check audio codec names
    cp = _run([
        "ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)
    ])
    if cp.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {cp.stderr.strip()}")
    data = json.loads(cp.stdout or "{}")
    streams = data.get("streams", [])
    for s in streams:
        if s.get("codec_type") == "audio" and str(s.get("codec_name", "")).lower() == "ac3":
            return True
    return False




def plan_jobs(root: Path, ext: str, bitrate: str = "640k", channels: int = 6) -> List[MediaJob]:
    jobs: List[MediaJob] = []
    for p in sorted(root.rglob(f"*{ext}")):
        if not p.is_file():
            continue
        safe = safe_rename(p)
        try:
            ac3 = has_ac3_audio(safe)
        except Exception as e:
            jobs.append(MediaJob(src=safe, out=safe, will_convert=False, reason=f"probe error: {e}"))
            continue
        if ac3:
            jobs.append(MediaJob(src=safe, out=safe, will_convert=False, reason="has AC3 already"))
            continue
        converted = safe.with_suffix(f".ac3{ext}")
        jobs.append(MediaJob(src=safe, out=converted, will_convert=True, reason=f"add AC3 {bitrate} {channels}ch"))
    return jobs




def convert(job: MediaJob, bitrate: str = "640k", channels: int = 6, move_originals: bool = True) -> Optional[str]:
    if not job.will_convert:
        return None
    converted_dir = job.src.parent
    ensure_dir(converted_dir)


    cmd = [
        "ffmpeg", "-v", "warning", "-y", "-i", str(job.src),
        "-map", "0", "-c:v", "copy", "-c:s", "copy", "-c:a", "ac3",
        "-b:a", str(bitrate), "-ac", str(channels), str(job.out)
    ]
    cp = _run(cmd)
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {job.src}: {cp.stderr.strip()}")


    if move_originals:
        move_to_dir(job.src, job.src.parent / "convertedFilms")


    return job.out.name