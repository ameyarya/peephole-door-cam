#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "pillow", "requests"]
# ///
"""Record motion clips from the door camera's MJPEG stream.

    uv run tools/recorder.py --url http://door-cam.local:81/stream

Clips go to recordings/YYYY-MM-DD/HHMMSS.mp4 with a matching .jpg snapshot,
and each one is logged to recordings/events.jsonl. Requires ffmpeg.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
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
    def __init__(self, out_dir: Path, pre_s=3.0, post_s=5.0, max_s=120.0, detector=None):
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
        self.clips: list[Path] = []

    @property
    def recording(self) -> bool:
        return self.frames_file is not None

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
    parser.add_argument("--pre", type=float, default=3.0, help="seconds kept before motion")
    parser.add_argument("--post", type=float, default=5.0, help="seconds kept after motion")
    parser.add_argument("--max", type=float, default=120.0, help="longest clip in seconds")
    parser.add_argument("--sensitivity", type=float, default=0.01,
                        help="fraction of the frame that must change")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found. Install it with: brew install ffmpeg")
    recorder = Recorder(args.out, args.pre, args.post, args.max, MotionDetector(args.sensitivity))
    try:
        run(args.url, recorder)
    except KeyboardInterrupt:
        recorder.finish()


if __name__ == "__main__":
    main()
