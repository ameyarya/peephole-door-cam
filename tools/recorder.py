#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "pillow", "requests"]
# ///
"""Watch the door camera all the time, and save clips only when something moves.

Each clip keeps 10 seconds from before the motion and 10 seconds after it stops,
like a car's sentry mode. Until then, frames are held in memory and thrown away.

    uv run tools/recorder.py --url http://door-cam.local:81/stream

Clips go to recordings/YYYY-MM-DD/HHMMSS.mp4 with a matching .jpg snapshot,
and each one is logged to recordings/events.jsonl. Requires ffmpeg.

Clips are also served on your network, for the Smart Home page's Motion panel, to
anyone with the private link it prints. Use --serve-port 0 to turn that off.
"""
from __future__ import annotations

import argparse
import collections
import io
import hmac
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
from PIL import Image

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_BUFFER = 4 * 1024 * 1024


def iter_jpegs(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Split a multipart MJPEG byte stream into JPEG frames."""
    buf = bytearray()
    for chunk in chunks:
        buf += chunk
        while True:
            start = buf.find(SOI)
            if start < 0:
                del buf[:-1]  # keep a byte in case a marker spans two chunks
                break
            end = buf.find(EOI, start + 2)
            if end < 0:
                del buf[:start]
                if len(buf) > MAX_BUFFER:
                    buf.clear()
                break
            yield bytes(buf[start : end + 2])
            del buf[: end + 2]


class MotionDetector:
    """Compares each frame with a slowly updated background.

    A change across most of the frame is treated as a lighting change, such as
    the hallway lights switching on, and doesn't count as motion.
    """

    def __init__(self, min_area=0.01, max_area=0.70, pixel_delta=25, learn_rate=0.05):
        self.min_area = min_area
        self.max_area = max_area
        self.pixel_delta = pixel_delta
        self.learn_rate = learn_rate
        self.background: np.ndarray | None = None

    def update(self, jpeg: bytes) -> bool:
        image = Image.open(io.BytesIO(jpeg))
        image.draft("L", (160, 120))
        gray = np.asarray(image.convert("L").resize((80, 60)), dtype=np.float32)
        if self.background is None:
            self.background = gray
            return False
        changed = float((np.abs(gray - self.background) > self.pixel_delta).mean())
        if changed > self.max_area:
            self.background = gray
            return False
        self.background += self.learn_rate * (gray - self.background)
        return changed >= self.min_area


class Recorder:
    def __init__(self, out_dir: Path, pre_s=10.0, post_s=10.0, max_s=120.0, detector=None):
        self.out_dir = Path(out_dir)
        self.pre_s = pre_s
        self.post_s = post_s
        self.max_s = max_s
        self.detector = detector or MotionDetector()
        self.pre_roll: collections.deque[tuple[float, bytes]] = collections.deque()
        self.frames_file = None
        self.frame_count = 0
        self.started = 0.0
        self.last_motion = 0.0
        self.last_frame = 0.0
        self.snapshot: bytes | None = None
        self.saving = False
        self.motion_began = 0.0
        self.clips: list[Path] = []

    @property
    def recording(self) -> bool:
        return self.frames_file is not None

    def status(self, now: float | None = None) -> dict:
        """What's happening right now: idle, recording, or saving a finished clip."""
        now = time.time() if now is None else now
        if self.saving:
            return {"state": "saving", "seconds": 0}
        if self.recording:
            return {"state": "recording", "seconds": round(now - self.motion_began)}
        return {"state": "idle", "seconds": 0}

    def feed(self, jpeg: bytes, now: float | None = None) -> None:
        now = time.time() if now is None else now
        motion = self.detector.update(jpeg)
        if motion:
            self.last_motion = now

        if not self.recording:
            self.pre_roll.append((now, jpeg))
            while self.pre_roll and now - self.pre_roll[0][0] > self.pre_s:
                self.pre_roll.popleft()
            if motion:
                self._start(now)
            return

        self._write(jpeg, now)
        if now - self.last_motion > self.post_s or now - self.started > self.max_s:
            self.finish()

    def _start(self, now: float) -> None:
        self.motion_began = now
        self.frames_file = tempfile.NamedTemporaryFile(suffix=".mjpeg", delete=False)
        self.frame_count = 0
        self.snapshot = self.pre_roll[-1][1]
        self.started = self.pre_roll[0][0]
        for t, frame in self.pre_roll:
            self._write(frame, t)
        self.pre_roll.clear()

    def _write(self, jpeg: bytes, now: float) -> None:
        self.frames_file.write(jpeg)
        self.frame_count += 1
        self.last_frame = now

    def finish(self) -> Path | None:
        """Close the current clip, if any, and encode it."""
        if not self.recording:
            return None
        self.saving = True
        try:
            return self._encode()
        finally:
            self.saving = False

    def _encode(self) -> Path | None:
        tmp = Path(self.frames_file.name)
        self.frames_file.close()
        self.frames_file = None

        duration = max(self.last_frame - self.started, 0.1)
        fps = max(self.frame_count / duration, 1.0)
        stamp = datetime.fromtimestamp(self.started)
        day_dir = self.out_dir / stamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        clip = day_dir / f"{stamp.strftime('%H%M%S')}.mp4"
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "mjpeg", "-framerate", f"{fps:.3f}",
             "-i", str(tmp), "-c:v", "libx264", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)],
            capture_output=True, text=True,
        )
        tmp.unlink(missing_ok=True)
        if result.returncode != 0:
            print(f"Could not encode {clip}: {result.stderr.strip()}", flush=True)
            return None

        clip.with_suffix(".jpg").write_bytes(self.snapshot)
        with (self.out_dir / "events.jsonl").open("a") as log:
            log.write(json.dumps({
                "type": "motion", "start": stamp.isoformat(timespec="seconds"),
                "seconds": round(duration, 1), "frames": self.frame_count,
                "clip": str(clip.relative_to(self.out_dir)),
            }) + "\n")
        self.clips.append(clip)
        print(f"Saved {clip} ({duration:.1f}s, {self.frame_count} frames)", flush=True)
        return clip


CLIP_FILE = re.compile(r"^\d{4}-\d\d-\d\d/\d{6}\.(mp4|jpg)$")
MAX_LISTED = 200


def clips_token(out_dir: Path) -> str:
    """The private part of the clips link. Kept with the recordings, so it survives restarts."""
    path = Path(out_dir) / ".clips_token"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(24))
        path.chmod(0o600)
    return path.read_text().strip()


def list_clips(out_dir: Path) -> list[dict]:
    """Saved clips, newest first. Clips deleted by hand simply drop off the list."""
    log = Path(out_dir) / "events.jsonl"
    if not log.exists():
        return []
    found = []
    for line in log.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        clip = event.get("clip", "")
        if CLIP_FILE.match(clip) and (Path(out_dir) / clip).exists():
            found.append({"start": event.get("start"), "seconds": event.get("seconds"),
                          "video": clip, "picture": clip[:-4] + ".jpg"})
    return found[::-1][:MAX_LISTED]


def delete_clip(out_dir: Path, clip: str) -> bool:
    """Deletes a clip for good: its video, picture and log line."""
    out_dir = Path(out_dir)
    if not CLIP_FILE.match(clip) or not clip.endswith(".mp4") or not (out_dir / clip).is_file():
        return False
    (out_dir / clip).unlink()
    (out_dir / clip[:-4]).with_suffix(".jpg").unlink(missing_ok=True)
    log = out_dir / "events.jsonl"
    if log.exists():
        kept = [line for line in log.read_text().splitlines() if f'"clip": "{clip}"' not in line]
        log.write_text("".join(line + "\n" for line in kept))
    folder = (out_dir / clip).parent
    if not any(folder.iterdir()):
        folder.rmdir()
    return True


def clip_server(out_dir: Path, port: int, status=None) -> ThreadingHTTPServer:
    out_dir = Path(out_dir)
    status = status or (lambda: {"state": "idle", "seconds": 0})
    token = clips_token(out_dir)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # the path holds the token

        def answer(self, code, body=b"", kind="text/plain", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_OPTIONS(self):   # the browser asks before a cross-site DELETE
            self.answer(204, extra=[("Access-Control-Allow-Methods", "GET, DELETE"), ("Access-Control-Max-Age", "600")])

        def do_DELETE(self):
            path = self.path.split("?")[0].lstrip("/")
            given, _, rest = path.partition("/")
            if not hmac.compare_digest(given.encode(), token.encode()) or not delete_clip(out_dir, rest):
                return self.answer(404)
            print(f"Deleted {rest}", flush=True)
            self.answer(204)

        def do_GET(self):
            path = self.path.split("?")[0].lstrip("/")
            given, _, rest = path.partition("/")
            if not hmac.compare_digest(given.encode(), token.encode()):
                return self.answer(404)
            if rest == "status.json":
                clips = list_clips(out_dir)
                body = dict(status(), newest=clips[0]["video"] if clips else None)
                return self.answer(200, json.dumps(body).encode(), "application/json")
            if rest == "clips.json":
                return self.answer(200, json.dumps(list_clips(out_dir)).encode(), "application/json")
            if not CLIP_FILE.match(rest) or not (out_dir / rest).is_file():
                return self.answer(404)
            self.send_file(out_dir / rest)

        def send_file(self, file: Path):
            data = file.read_bytes()
            kind = "video/mp4" if file.suffix == ".mp4" else "image/jpeg"
            accept = [("Accept-Ranges", "bytes")]
            # Phones ask for videos in ranges and won't play them otherwise.
            wanted = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if not wanted or wanted.groups() == ("", ""):
                return self.answer(200, data, kind, accept)
            first, last = wanted.groups()
            if first:
                start, end = int(first), min(int(last) if last else len(data) - 1, len(data) - 1)
            else:
                start, end = max(len(data) - int(last), 0), len(data) - 1
            if start > end or start >= len(data):
                return self.answer(416, b"", kind, [("Content-Range", f"bytes */{len(data)}")])
            self.answer(206, data[start : end + 1], kind, accept + [("Content-Range", f"bytes {start}-{end}/{len(data)}")])

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(url: str, recorder: Recorder) -> None:
    import requests

    delay = 1
    while True:
        try:
            with requests.get(url, stream=True, timeout=(5, 15)) as response:
                response.raise_for_status()
                print(f"Connected to {url}", flush=True)
                delay = 1
                for jpeg in iter_jpegs(response.iter_content(chunk_size=8192)):
                    recorder.feed(jpeg)
            print("Stream ended", flush=True)
        except requests.RequestException as err:
            print(f"Stream error: {err}. Retrying in {delay}s", flush=True)
        recorder.finish()
        time.sleep(delay)
        delay = min(delay * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://door-cam.local:81/stream")
    parser.add_argument("--out", type=Path, default=Path("recordings"))
    parser.add_argument("--pre", type=float, default=10.0, help="seconds kept before motion")
    parser.add_argument("--post", type=float, default=10.0, help="seconds kept after motion")
    parser.add_argument("--max", type=float, default=120.0, help="longest clip in seconds")
    parser.add_argument("--sensitivity", type=float, default=0.01,
                        help="fraction of the frame that must change")
    parser.add_argument("--serve-port", type=int, default=8766,
                        help="port for the Smart Home page's Motion panel (0 = off)")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found. Install it with: brew install ffmpeg")
    recorder = Recorder(args.out, args.pre, args.post, args.max, MotionDetector(args.sensitivity))
    if args.serve_port:
        clip_server(args.out, args.serve_port, recorder.status)
        print(f"Clips link for Smart Home's Settings: http://<this Mac's address>:{args.serve_port}/{clips_token(args.out)}", flush=True)
    try:
        run(args.url, recorder)
    except KeyboardInterrupt:
        recorder.finish()


if __name__ == "__main__":
    main()
