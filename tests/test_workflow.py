import hashlib
import json
import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request, urlopen

import uvicorn

from app import converter
from app.main import app


def run(*args):
    result = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def make_fixture(target, work_dir, layout="5.1", default="default"):
    subtitle = work_dir / "sample.srt"
    subtitle.write_text("1\n00:00:00,100 --> 00:00:01,500\nA subtitle\n", encoding="utf-8")
    notes = work_dir / "notes.txt"
    notes.write_text("An original attachment\n", encoding="utf-8")
    cover = work_dir / "cover.png"
    run(
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:size=32x32",
        "-frames:v", "1", "-threads", "1", str(cover),
    )
    metadata = work_dir / "sample.ffmetadata"
    metadata.write_text(
        ";FFMETADATA1\ntitle=AC3Fixer fixture\n[CHAPTER]\nTIMEBASE=1/1000\n"
        "START=0\nEND=1000\ntitle=Opening\n",
        encoding="utf-8",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    run(
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=6",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl={layout}",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-i", str(subtitle),
        "-f", "ffmetadata", "-i", str(metadata),
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-map", "4:s",
        "-map_metadata", "5", "-map_chapters", "5",
        "-c:v", "mpeg4", "-c:a:0", "dca", "-c:a:1", "ac3", "-c:a:2", "dca",
        "-strict", "experimental", "-c:s", "srt", "-t", "2",
        "-metadata:s:a:0", "language=fra", "-metadata:s:a:0", "title=French main",
        "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English dub",
        "-metadata:s:a:2", "language=jpn", "-metadata:s:a:2", "title=Japanese stereo",
        "-disposition:a:0", default, "-disposition:a:1", "0", "-disposition:a:2", "0",
        "-disposition:s:0", "forced", "-default_mode", "passthrough",
        "-attach", str(notes), "-metadata:s:t:0", "mimetype=text/plain",
        "-metadata:s:t:0", "filename=notes.txt",
        "-attach", str(cover), "-metadata:s:t:1", "mimetype=image/png",
        "-metadata:s:t:1", "filename=cover.png",
        str(target),
    )


def probe(path):
    return json.loads(run(
        "ffprobe", "-v", "error", "-of", "json",
        "-show_format", "-show_streams", "-show_chapters", "-show_data_hash", "sha256", str(path),
    ))


def packet_hashes(path, stream):
    data = json.loads(run(
        "ffprobe", "-v", "error", "-of", "json", "-select_streams", stream,
        "-show_packets", "-show_entries", "packet=data_hash", "-show_data_hash", "sha256", str(path),
    ))
    return [packet["data_hash"] for packet in data["packets"]]


def snapshot(root):
    return {
        path.relative_to(root): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*") if path.is_file()
    }


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.work_dir = Path(self.enterContext(TemporaryDirectory()))
        self.source = self.work_dir / "source"
        self.output = self.work_dir / "output"
        self.source.mkdir()
        self.output.mkdir()
        self.enterContext(patch.dict(os.environ, {
            "MEDIA_PATH": str(self.source), "OUTPUT_PATH": str(self.output),
        }))

        listener = self.enterContext(socket.socket())
        listener.bind(("127.0.0.1", 0))
        self.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        self.addCleanup(self.stop_server, server, thread)
        for _ in range(100):
            try:
                self.request("/")
                break
            except URLError:
                time.sleep(0.05)
        else:
            self.fail("The local AC3Fixer server did not start.")

    def stop_server(self, server, thread):
        server.should_exit = True
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "The local server did not shut down.")

    def request(self, path, *, body=None):
        headers = {}
        if isinstance(body, list):
            body = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        with urlopen(Request(self.base_url + path, data=body, headers=headers), timeout=10) as response:
            return response.read().decode("utf-8")

    def wait_for_jobs(self, count):
        until = time.monotonic() + 20
        while time.monotonic() < until:
            jobs = json.loads(self.request("/jobs"))
            if len(jobs) == count and all(job["status"] not in ("queued", "running") for job in jobs):
                return jobs
            time.sleep(0.05)
        self.fail(f"Jobs did not finish: {jobs}")

    def assert_remux(self, source, result, *, channels, language, make_default):
        original = probe(source)
        output = probe(result)
        self.assertEqual(output["format"]["tags"]["title"], original["format"]["tags"]["title"])
        self.assertTrue(original["chapters"])
        self.assertEqual(output["chapters"], original["chapters"])

        def streams(data, kind):
            return [stream for stream in data["streams"] if stream["codec_type"] == kind]

        original_audio = streams(original, "audio")
        output_audio = streams(output, "audio")
        self.assertEqual(len(output["streams"]), len(original["streams"]) + 1)
        self.assertEqual(len(output_audio), len(original_audio) + 1)
        for before, after in zip(original_audio, output_audio[:-1]):
            for key in ("codec_name", "channels", "channel_layout", "extradata_hash"):
                self.assertEqual(before.get(key), after.get(key))
            for key in ("language", "title"):
                self.assertEqual(before["tags"][key], after["tags"][key])
            disposition = dict(before["disposition"])
            if make_default:
                disposition["default"] = 0
            self.assertEqual(after["disposition"], disposition)

        added = output_audio[-1]
        self.assertEqual(added["codec_name"], "ac3")
        self.assertEqual(added["channels"], channels)
        self.assertEqual(added["tags"]["language"], language)
        self.assertEqual(added["tags"]["title"], "AC-3 Compatibility")
        self.assertEqual(added["disposition"]["default"], int(make_default))
        self.assertEqual(streams(output, "subtitle")[0]["codec_name"], "subrip")
        self.assertEqual(streams(output, "subtitle")[0]["disposition"]["forced"], 1)
        self.assertEqual(
            streams(output, "attachment")[0]["extradata_hash"],
            streams(original, "attachment")[0]["extradata_hash"],
        )
        covers = [stream for stream in streams(output, "video") if stream["disposition"]["attached_pic"]]
        self.assertEqual([cover["tags"]["filename"] for cover in covers], ["cover.png"])
        for stream in ("v:0", "v:1"):
            original_packets = packet_hashes(source, stream)
            self.assertTrue(original_packets)
            self.assertEqual(packet_hashes(result, stream), original_packets)

    def test_batch_scan_preserve_and_continue(self):
        feature = self.source / "Films" / "Été à 東京.mkv"
        make_fixture(feature, self.work_dir)
        stereo = self.source / "Stereo default.mkv"
        existing = self.source / "Already made.MKV"
        compatible = self.source / "Already compatible.mkv"
        failing = self.source / "Write failure.mkv"
        for path in (stereo, existing, failing):
            path.write_bytes(feature.read_bytes())
        run(
            "ffmpeg", "-v", "error", "-i", str(feature),
            "-map", "0:v:0", "-map", "0:a:1", "-c", "copy", str(compatible),
        )
        (self.source / "Unreadable.mkv").write_bytes(b"broken MKV")
        existing_output = self.output / "Already made.ac3.mkv"
        existing_output.write_bytes(b"previous output")
        original_files = snapshot(self.source)

        page = self.request("/scan", body=b"")
        for value in ("Files to convert", "Films/Été à 東京.mkv", "French main", "English dub",
                      "Japanese stereo", "Scan errors", "Unreadable.mkv", "6 ch", "DTS", "AC-3"):
            self.assertIn(value, page)
        for name in ("Already compatible.mkv", "Already made.MKV", "Unreadable.mkv"):
            self.assertNotIn(f'data-source="{name}"', page)
        self.assertEqual(snapshot(self.source), original_files)
        self.assertEqual(list(self.output.iterdir()), [existing_output])
        dashboard = json.loads(self.request("/dashboard"))
        self.assertEqual(
            dashboard["stats"],
            {"found": 6, "needs_attention": 4, "completed": 1, "in_progress": 0},
        )
        self.assertCountEqual(dashboard["pending_sources"], [
            "Films/Été à 東京.mkv", "Stereo default.mkv", "Write failure.mkv",
        ])

        def select(path, index=1, make_default=False):
            return {
                "source": path.relative_to(self.source).as_posix(),
                "track_index": index,
                "make_default": make_default,
            }

        started, resume = Event(), Event()
        real_run = converter._run_conversion
        failing_input = failing.resolve()

        def block_failing_ffmpeg(command, duration, report_progress):
            if Path(command[command.index("-i") + 1]) == failing_input:
                # Leave partial output and trigger an FFmpeg error on every supported version.
                Path(command[-1]).write_bytes(b"partial output")
                started.set()
                if not resume.wait(timeout=10):
                    raise RuntimeError("The test did not release FFmpeg in time.")
                command = [command[0], "-ac3fixer-test-invalid-option", *command[1:]]
            return real_run(command, duration, report_progress)

        with patch.object(converter, "_run_conversion", block_failing_ffmpeg):
            try:
                queued = json.loads(self.request("/convert", body=[
                    select(failing), select(feature), select(stereo, 3, make_default=True),
                    select(existing), select(feature),
                ]))
                self.assertEqual(queued, {"queued": 4, "already_active": 1})
                self.assertTrue(started.wait(timeout=10), self.request("/jobs"))
                jobs = json.loads(self.request("/jobs"))
                self.assertEqual([job["status"] for job in jobs], ["running", "queued", "queued", "queued"])
                dashboard = json.loads(self.request("/dashboard"))
                self.assertEqual(
                    dashboard["stats"],
                    {"found": 6, "needs_attention": 1, "completed": 0, "in_progress": 4},
                )
                self.assertEqual(dashboard["pending_sources"], [])
                self.assertIn('data-source="Write failure.mkv" hidden', self.request("/"))
                duplicates = json.loads(self.request("/convert", body=[select(failing), select(feature)]))
                self.assertEqual(duplicates, {"queued": 0, "already_active": 2})
            finally:
                resume.set()
            jobs = self.wait_for_jobs(4)

        self.assertEqual([job["status"] for job in jobs], ["failed", "completed", "completed", "skipped"])
        self.assertIn("ffmpeg:", jobs[0]["message"])
        self.assertIn("Output already exists", jobs[3]["message"])
        dashboard = json.loads(self.request("/dashboard"))
        self.assertEqual(
            dashboard["stats"],
            {"found": 6, "needs_attention": 2, "completed": 3, "in_progress": 0},
        )
        self.assertEqual(dashboard["pending_sources"], ["Write failure.mkv"])
        self.assertEqual(existing_output.read_bytes(), b"previous output")
        self.assertFalse((self.output / "Write failure.ac3.mkv").exists())
        self.assertEqual(list(self.output.rglob(".ac3fixer-*")), [])
        self.assertEqual(snapshot(self.source), original_files)
        self.assert_remux(
            feature, self.output / "Films" / "Été à 東京.ac3.mkv",
            channels=6, language="fra", make_default=False,
        )
        self.assert_remux(
            stereo, self.output / "Stereo default.ac3.mkv",
            channels=2, language="jpn", make_default=True,
        )
        page = self.request("/scan", body=b"")
        self.assertIn('data-source="Write failure.mkv"', page)
        self.assertNotIn('data-source="Films/Été à 東京.mkv"', page)

    def test_running_job_reports_progress_before_publish(self):
        feature = self.source / "Progress.mkv"
        make_fixture(feature, self.work_dir)
        self.request("/scan", body=b"")
        reached, resume = Event(), Event()
        percentages = []
        real_run = converter._run_conversion

        def wait_for_observation(command, duration, report_progress):
            def report(percent):
                percentages.append(percent)
                report_progress(percent)
                if percent == 50:
                    reached.set()
                    if not resume.wait(timeout=10):
                        raise RuntimeError("The test did not release the conversion in time.")

            # Control the reports so the test does not depend on how fast FFmpeg runs.
            converter._report_ffmpeg_progress(
                ["out_time_us=N/A", "out_time_us=-1000", "out_time_us=1000000",
                 "out_time_us=500000", "out_time_us=2000000"],
                2_000_000, report,
            )
            real_run(command, duration, None)

        result = self.output / "Progress.ac3.mkv"
        with patch.object(converter, "_run_conversion", wait_for_observation):
            try:
                self.request("/convert", body=[{"source": feature.name, "track_index": 1}])
                self.assertTrue(reached.wait(timeout=10), self.request("/jobs"))
                dashboard = json.loads(self.request("/dashboard"))
                job = dashboard["jobs"][0]
                self.assertEqual(job["status"], "running")
                self.assertEqual(job["progress"], 50)
                self.assertEqual(dashboard["stats"]["in_progress"], 1)
                self.assertFalse(result.exists())
            finally:
                resume.set()
            job = self.wait_for_jobs(1)[0]

        self.assertEqual(job["status"], "completed", job["message"])
        self.assertEqual(job["progress"], 100)
        self.assertEqual(percentages, [0, 50, 99])
        result.unlink()
        self.request("/scan", body=b"")
        self.assertEqual(
            json.loads(self.request("/dashboard"))["stats"],
            {"found": 1, "needs_attention": 1, "completed": 0, "in_progress": 0},
        )

    def test_rescan_reuses_unchanged_audio_metadata(self):
        feature = self.source / "Feature.mkv"
        make_fixture(feature, self.work_dir)
        other = self.source / "Other.mkv"
        other.write_bytes(feature.read_bytes())
        probed = []
        original_probe = converter._probe

        def record_probe(path):
            probed.append(path)
            return original_probe(path)

        with patch.object(converter, "_probe", record_probe):
            self.request("/scan", body=b"")
            self.assertCountEqual(probed, [feature.resolve(), other.resolve()])

            (self.output / "Feature.ac3.mkv").write_bytes(b"existing output")
            page = self.request("/scan", body=b"")
            self.assertNotIn('data-source="Feature.mkv"', page)
            self.assertIn('data-source="Other.mkv"', page)
            self.assertEqual(len(probed), 2)

            info = other.stat()
            os.utime(other, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
            self.request("/scan", body=b"")
            self.assertEqual(probed[2:], [other.resolve()])

            other.unlink()
            page = self.request("/scan", body=b"")
            self.assertNotIn("Other.mkv", page)
            self.assertIn("No files waiting to be queued.", page)
            self.assertEqual(len(probed), 3)

    def test_mono_without_default_audio(self):
        feature = self.source / "Mono.mkv"
        make_fixture(feature, self.work_dir, layout="mono", default="0")
        self.request("/scan", body=b"")
        self.request("/convert", body=[{"source": "Mono.mkv", "track_index": 1}])
        job = self.wait_for_jobs(1)[0]
        self.assertEqual(job["status"], "completed", job["message"])
        self.assert_remux(
            feature, self.output / "Mono.ac3.mkv", channels=1, language="fra", make_default=False,
        )


if __name__ == "__main__":
    unittest.main()
