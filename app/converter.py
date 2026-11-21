import json
import os
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from tempfile import TemporaryDirectory


AC3_TITLE = "AC-3 Compatibility"
DEFAULT_SCAN_WORKERS = 2

type SourceFingerprint = tuple[Path, int, int, int, int, int]


@dataclass(frozen=True)
class AudioTrack:
    index: int
    codec: str
    profile: str | None
    language: str | None
    title: str | None
    channels: int | None
    default: bool | None

    @property
    def is_dts(self) -> bool:
        # FFprobe reports DTS-HD as the DTS codec with a different profile.
        return self.codec == "dts"


@dataclass(frozen=True)
class MediaFile:
    source: str
    output: str
    tracks: tuple[AudioTrack, ...] = ()
    output_exists: bool = False
    error: str | None = None


def _run(command: list[str], *, timeout: int | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{command[0]} timed out after {timeout} seconds.") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start {command[0]}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"{command[0]}: {detail}")
    return result.stdout


def _probe(path: Path) -> dict:
    data = json.loads(_run([
        "ffprobe", "-v", "error", "-of", "json", "-show_streams", "-show_chapters",
        "-protocol_whitelist", "file", "-f", "matroska", "-i", str(path),
    ], timeout=30))
    if not data.get("streams"):
        raise RuntimeError("ffprobe found no streams in the MKV.")
    return data


def _audio_tracks(probe: dict) -> tuple[AudioTrack, ...]:
    tracks = []
    for stream in probe["streams"]:
        if stream["codec_type"] != "audio":
            continue
        tags = {key.lower(): value for key, value in stream.get("tags", {}).items()}
        default = stream.get("disposition", {}).get("default")
        tracks.append(AudioTrack(
            index=stream["index"],
            codec=stream.get("codec_name", "unknown"),
            profile=stream.get("profile"),
            language=tags.get("language"),
            title=tags.get("title"),
            channels=stream.get("channels"),
            default=None if default is None else bool(default),
        ))
    return tuple(tracks)


def _verify_output(
    original: dict, result: dict, selected: AudioTrack, make_default: bool
) -> None:
    original_audio = _audio_tracks(original)
    result_audio = _audio_tracks(result)
    if len(result_audio) != len(original_audio) + 1:
        raise RuntimeError("Output verification failed: expected one additional audio track.")

    added = result_audio[-1]
    expected_channels = min(selected.channels, 6) if selected.channels else None
    if (
        added.codec != "ac3"
        or (expected_channels is not None and added.channels != expected_channels)
        or (added.language or "und") != (selected.language or "und")
        or added.title != AC3_TITLE
        or bool(added.default) != make_default
    ):
        raise RuntimeError("Output verification failed: the new AC-3 track did not match the selection.")

    original_streams = Counter(
        (stream["codec_type"], stream.get("codec_name")) for stream in original["streams"]
    )
    copied_streams = Counter(
        (stream["codec_type"], stream.get("codec_name"))
        for stream in result["streams"]
        if stream["index"] != added.index
    )
    if original_streams != copied_streams:
        raise RuntimeError("Output verification failed: an original stream is missing or changed codec.")
    for before, after in zip(original_audio, result_audio[:-1]):
        if bool(after.default) != (bool(before.default) and not make_default):
            raise RuntimeError("Output verification failed: an original audio default flag changed unexpectedly.")
    original_chapters = original.get("chapters", [])
    result_chapters = result.get("chapters", [])
    if len(original_chapters) != len(result_chapters):
        raise RuntimeError("Output verification failed: the chapter count changed.")
    for before, after in zip(original_chapters, result_chapters):
        if (before["start_time"], before["end_time"]) != (after["start_time"], after["end_time"]):
            raise RuntimeError("Output verification failed: chapter timing changed.")


class MediaLibrary:
    def __init__(self, source: Path, output: Path, *, scan_workers: int = DEFAULT_SCAN_WORKERS):
        if scan_workers < 1:
            raise ValueError("SCAN_WORKERS must be a positive integer.")
        self.source = source.resolve()
        self.output = output.resolve()
        self.scan_workers = scan_workers
        self._audio_cache: dict[SourceFingerprint, tuple[AudioTrack, ...]] = {}
        if (
            self.output.is_relative_to(self.source)
            or self.source.is_relative_to(self.output)
            or (self.source.is_dir() and self.output.is_dir() and self.source.samefile(self.output))
        ):
            raise ValueError("MEDIA_PATH and OUTPUT_PATH must be separate directories.")

    def _source_file(self, relative: Path) -> tuple[Path, os.stat_result]:
        path = (self.source / relative).resolve(strict=True)
        if not path.is_relative_to(self.source):
            raise ValueError("Source path must stay inside the media directory.")
        info = path.stat()
        if not S_ISREG(info.st_mode):
            raise ValueError("Source must be a regular file.")
        return path, info

    def _destination(self, relative: Path) -> Path:
        parent = (self.output / relative.parent).resolve()
        if not parent.is_relative_to(self.output):
            raise ValueError("Output path must stay inside the output directory.")
        return parent / relative.name

    def _scan_file(self, relative: Path) -> tuple[MediaFile, SourceFingerprint | None]:
        output = relative.with_suffix(".ac3.mkv")
        tracks: tuple[AudioTrack, ...] = ()
        fingerprint = None
        output_exists = False
        error = None
        try:
            path, info = self._source_file(relative)
            key = (path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            cached = self._audio_cache.get(key)
            tracks = cached if cached is not None else _audio_tracks(_probe(path))
            fingerprint = key
            output_exists = os.path.lexists(self._destination(output))
        except (OSError, RuntimeError, ValueError) as exc:
            error = str(exc)
        return MediaFile(relative.as_posix(), output.as_posix(), tracks, output_exists, error), fingerprint

    def scan(self) -> tuple[dict[str, MediaFile], list[str]]:
        candidates = []
        errors = []

        for folder, _, names in os.walk(self.source, onerror=lambda error: errors.append(str(error))):
            relative_folder = Path(folder).relative_to(self.source)
            candidates.extend(relative_folder / name for name in names if Path(name).suffix.lower() == ".mkv")

        files = []
        audio_cache = {}
        with ThreadPoolExecutor(max_workers=self.scan_workers, thread_name_prefix="scan") as pool:
            for file, fingerprint in pool.map(self._scan_file, candidates):
                files.append(file)
                if fingerprint is not None:
                    audio_cache[fingerprint] = file.tracks
        self._audio_cache = audio_cache

        files.sort(key=lambda file: (file.source.casefold(), file.source))
        return {file.source: file for file in files}, errors

    def convert(self, media: MediaFile, selected: AudioTrack, make_default: bool) -> bool:
        """Publish a verified result, or return False if the destination exists."""
        destination = self._destination(Path(media.output))
        if os.path.lexists(destination):
            return False

        source, _ = self._source_file(Path(media.source))
        original = _probe(source)
        audio = _audio_tracks(original)
        if selected not in audio:
            raise RuntimeError("The selected DTS track changed. Scan media and select it again.")
        new_audio = f"a:{len(audio)}"
        bitrate = "192k" if selected.channels in (1, 2) else "640k"
        stream_maps = []
        attachment_maps = []
        cover_art = []
        for stream in original["streams"]:
            # FFmpeg exposes image attachments as video with an attached picture.
            if stream.get("disposition", {}).get("attached_pic"):
                cover_art.append(stream)
            elif stream["codec_type"] == "attachment":
                attachment_maps.extend(["-map", f"0:{stream['index']}"])
            else:
                stream_maps.extend(["-map", f"0:{stream['index']}"])
        ffmpeg_input = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror", "-n", "-copyts",
            "-protocol_whitelist", "file", "-f", "matroska", "-i", str(source),
        ]
        command = [
            *ffmpeg_input,
            *stream_maps, "-map", f"0:{selected.index}", *attachment_maps,
            "-map_metadata", "0", "-map_chapters", "0",
            "-c", "copy", f"-c:{new_audio}", "ac3", f"-b:{new_audio}", bitrate,
            f"-metadata:s:{new_audio}", f"title={AC3_TITLE}",
            f"-metadata:s:{new_audio}", f"language={selected.language or 'und'}",
            f"-disposition:{new_audio}", "default" if make_default else "0",
            "-default_mode", "passthrough", "-avoid_negative_ts", "disabled",
        ]
        if selected.channels and selected.channels > 6:
            command.extend([f"-ac:{new_audio}", "6"])
        if make_default:
            for index, track in enumerate(audio):
                if track.default:
                    command.extend([f"-disposition:a:{index}", "-default"])

        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=destination.parent, prefix=".ac3fixer-") as work_dir:
            # Reattach cover images from their original packets to keep them as Matroska attachments.
            attachment_count = len(attachment_maps) // 2
            for number, cover in enumerate(cover_art, start=attachment_count):
                image = Path(work_dir) / f"cover-{cover['index']}"
                _run([
                    *ffmpeg_input, "-map", f"0:{cover['index']}", "-c", "copy",
                    "-frames:v", "1", "-f", "image2pipe", str(image),
                ])
                command.extend(["-attach", str(image)])
                for name, value in cover.get("tags", {}).items():
                    command.extend([f"-metadata:s:t:{number}", f"{name}={value}"])

            temporary = Path(work_dir) / "output.part"
            _run([*command, "-f", "matroska", str(temporary)])
            _verify_output(original, _probe(temporary), selected, make_default)

            # A hard link publishes the complete file atomically and cannot replace an existing one.
            try:
                os.link(temporary, destination)
            except FileExistsError:
                return False
        return True
