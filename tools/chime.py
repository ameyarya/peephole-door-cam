#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "sounddevice", "requests"]
# ///
"""Train and test a doorbell chime detector on your own doorbell.

    uv run tools/chime.py record chime --count 10      # ring the bell each time
    uv run tools/chime.py record background --seconds 60 --count 3
    uv run tools/chime.py train
    uv run tools/chime.py listen                       # live test with the mic
    uv run tools/chime.py scan some_recording.wav

Add --source http://door-cam.local:82/audio to record and listen to use the
board's own mic (needs the xiao_sense_training firmware) instead of this
computer's.

A chime is mostly a few steady tones, so the model is just those frequencies
and a threshold. That's small enough to run on an ESP32 with Goertzel filters.
A bell with a single note also has to match the shape of a strike: a sudden
start and a steady fade. See tools/chime_sim.py to train from one recording.
Train with the microphone that will do the listening: a laptop's model tells
you if the approach works, but the door unit needs samples from its own mic.
"""
from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
FRAME = 1024
HOP = 512
BAND_LOW = 300.0
BAND_HIGH = 6000.0
TONE_WIDTH = 40.0     # Hz either side of each tone
MAX_TONES = 3
MIN_TONE_GAP = 60.0   # Hz between tones
WINDOW_S = 1.5        # all tones must appear within this long
SILENCE_GATE = 0.15   # frames quieter than this share of the chime's peak are ignored

DATA_DIR = Path(__file__).parent / "chime_data"
MODEL_PATH = DATA_DIR / "chime_model.json"


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit audio")
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
        audio = audio.reshape(-1, w.getnchannels()).mean(axis=1)
        rate = w.getframerate()
    if rate != SAMPLE_RATE:
        n = int(len(audio) * SAMPLE_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    return audio


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def power_frames(audio: np.ndarray) -> np.ndarray:
    """Power spectrum per frame, shape (frames, bins)."""
    if len(audio) < FRAME:
        audio = np.pad(audio, (0, FRAME - len(audio)))
    starts = np.arange(0, len(audio) - FRAME + 1, HOP)
    frames = np.stack([audio[s : s + FRAME] for s in starts])
    return np.abs(np.fft.rfft(frames * np.hanning(FRAME), axis=1)) ** 2


FREQS = np.fft.rfftfreq(FRAME, 1 / SAMPLE_RATE)
IN_BAND = (FREQS >= BAND_LOW) & (FREQS <= BAND_HIGH)


def frame_levels(power: np.ndarray) -> np.ndarray:
    return power[:, IN_BAND].sum(axis=1)


def find_tones(clips: list[np.ndarray], max_tones: int = MAX_TONES) -> list[float]:
    """Frequencies that are consistently strong across all chime clips."""
    spectra = []
    for clip in clips:
        power = power_frames(clip)
        levels = frame_levels(power)
        loud = levels >= levels.max() * SILENCE_GATE
        spectrum = power[loud].mean(axis=0)
        spectra.append(spectrum / spectrum[IN_BAND].sum())
    # The median ignores one-off noises that were present in a single take.
    average = np.median(spectra, axis=0) * IN_BAND

    tones: list[float] = []
    peak_power = average.max()
    for i in np.argsort(average)[::-1]:
        if average[i] < peak_power * 0.1 or len(tones) == max_tones:
            break
        if average[i] < average[max(i - 1, 0)] or average[i] < average[min(i + 1, len(average) - 1)]:
            continue  # not a local peak
        if all(abs(FREQS[i] - t) >= MIN_TONE_GAP for t in tones):
            tones.append(float(FREQS[i]))
    return sorted(tones)


def tone_ratios(power: np.ndarray, tones: list[float]) -> np.ndarray:
    """Share of each frame's energy in each tone, shape (frames, tones)."""
    total = np.maximum(frame_levels(power), 1e-12)
    return np.stack(
        [power[:, np.abs(FREQS - t) <= TONE_WIDTH].sum(axis=1) / total for t in tones], axis=1
    )


def scores_over_time(audio: np.ndarray, tones: list[float], min_level: float) -> np.ndarray:
    """Score per frame: how strongly every tone appeared in the trailing window.

    Each tone must show up in the window, in any order, so a two-note ding-dong
    scores high while a single beep at one of its frequencies doesn't.
    """
    power = power_frames(audio)
    ratios = tone_ratios(power, tones)
    ratios[frame_levels(power) < min_level] = 0.0
    window = max(int(WINDOW_S * SAMPLE_RATE / HOP), 1)
    scores = np.zeros(len(ratios))
    for i in range(len(ratios)):
        scores[i] = ratios[max(0, i - window + 1) : i + 1].max(axis=0).min()
    return scores


STRIKE_WINDOW_S = 1.0   # how much of the fade to look at
STRIKE_PRE = 6          # frames before the strike used as the "before" level
STRIKE_RISE = 3         # frames the strike may take to reach its peak
MIN_FADE_FRAMES = 8     # fewer frames above the noise can't show a fade
FADE_MARGIN_DB = 6.0
MAX_OVERTONE_DB = -12.0 # bells are nearly pure; musical notes have strong overtones


def strike_candidates(audio: np.ndarray, tone_hz: float, min_level: float = 0.0):
    """Yields possible strikes: (end_frame, purity, attack_db, fade_db_s, wobble_db, overtone_db)."""
    power = power_frames(audio)
    tone = power[:, np.abs(FREQS - tone_hz) <= TONE_WIDTH].sum(axis=1)
    # The bands scale with k so they also catch overtones of notes near the bell's pitch.
    overtones = sum(power[:, np.abs(FREQS - tone_hz * k) <= TONE_WIDTH * k].sum(axis=1) for k in (2, 3))
    purity = tone / np.maximum(frame_levels(power), 1e-12)
    db = 10 * np.log10(tone + 1e-12)
    window = int(STRIKE_WINDOW_S * SAMPLE_RATE / HOP)
    half = window // 2
    seconds = np.arange(window) * HOP / SAMPLE_RATE
    for s in range(STRIKE_PRE, len(db) - window + 1):
        if tone[s : s + STRIKE_RISE].max() < min_level:
            continue
        before = float(np.median(db[s - STRIKE_PRE : s]))
        attack = float(db[s : s + STRIKE_RISE].max() - before)
        if attack <= 0 or int(np.argmax(db[s : s + window])) >= STRIKE_RISE:
            continue
        # Only fit the part of the fade that's still above the noise.
        keep = np.arange(STRIKE_RISE - 1, window)
        keep = keep[db[s + keep] > before + FADE_MARGIN_DB]
        if len(keep) < MIN_FADE_FRAMES:
            continue
        slope, intercept = np.polyfit(seconds[keep], db[s + keep], 1)
        wobble = float(np.std(db[s + keep] - (slope * seconds[keep] + intercept)))
        overtone = 10 * np.log10((overtones[s : s + half].sum() + 1e-12) / (tone[s : s + half].sum() + 1e-12))
        yield s + window - 1, float(purity[s : s + half].mean()), attack, float(slope), wobble, float(overtone)


def strike_scores(audio: np.ndarray, model: dict) -> np.ndarray:
    """Score per frame: the tone's purity, if a strike that fits the model ended there."""
    scores = np.zeros(max(len(power_frames(audio)), 1))
    strike = model["strike"]
    low, high = strike["fade_db_s"]
    for end, purity, attack, fade, wobble, overtone in strike_candidates(audio, model["tones_hz"][0], model["min_level"]):
        if (attack >= strike["min_attack_db"] and low <= fade <= high and wobble <= strike["max_wobble_db"]
                and overtone <= strike["max_overtone_db"]):
            scores[end] = purity
    return scores


def model_scores(audio: np.ndarray, model: dict) -> np.ndarray:
    if "strike" in model:
        return strike_scores(audio, model)
    return scores_over_time(audio, model["tones_hz"], model["min_level"])


def score_clip(audio: np.ndarray, tones: list[float], min_level: float) -> float:
    return float(scores_over_time(audio, tones, min_level).max())


def min_level_for(clips: list[np.ndarray]) -> float:
    """A level gate well below the quietest chime, so distant chimes still count."""
    return float(min(frame_levels(power_frames(c)).max() for c in clips) * 0.02)


def fit_strike(positives: list[np.ndarray], negatives: list[np.ndarray], tone_hz: float) -> dict:
    """A single-note bell: learn the strike's shape from the chime clips."""
    min_level = min_level_for(positives)
    best = []
    for clip in positives:
        found = list(strike_candidates(clip, tone_hz, min_level))
        if found:
            best.append(max(found, key=lambda c: c[1] * c[2]))
    if len(best) < len(positives) * 0.5:
        raise ValueError("Most chime clips don't look like a single struck note")
    _, _, attacks, fades, wobbles, overtones = np.array(best).T
    low, high = np.percentile(fades, [1, 99])
    model = {
        "tones_hz": [round(tone_hz, 1)],
        "min_level": min_level,
        "sample_rate": SAMPLE_RATE,
        "frame": FRAME,
        "hop": HOP,
        "tone_width_hz": TONE_WIDTH,
        "strike": {
            "min_attack_db": round(float(np.percentile(attacks, 1)) * 0.8, 2),
            "fade_db_s": [round(float(low) * 1.2, 2), round(float(high) * 0.8, 2)],
            "max_wobble_db": round(float(np.percentile(wobbles, 99)) * 1.2, 2),
            "max_overtone_db": round(min(float(np.percentile(overtones, 90)) + 3, MAX_OVERTONE_DB), 2),
        },
    }
    pos = np.array([strike_scores(c, model).max() for c in positives])
    neg = np.array([strike_scores(c, model).max() for c in negatives]) if negatives else np.zeros(1)
    # Most chimes must pass, even in noise, so a stray clip can't set the threshold.
    low_pos, high_neg = float(np.percentile(pos, 5)), float(neg.max())
    threshold = (low_pos + high_neg) / 2 if low_pos > high_neg else high_neg * 1.05
    model.update(
        threshold=round(threshold, 4),
        lowest_chime_score=round(low_pos, 4),
        highest_background_score=round(high_neg, 4),
        separable=low_pos > high_neg,
    )
    return model


def fit(positives: list[np.ndarray], negatives: list[np.ndarray]) -> dict:
    tones = find_tones(positives)
    if not tones:
        raise ValueError("No clear tones found in the chime recordings")
    if len(tones) == 1:
        return fit_strike(positives, negatives, tones[0])
    min_level = min_level_for(positives)
    pos = [score_clip(c, tones, min_level) for c in positives]
    neg = [score_clip(c, tones, min_level) for c in negatives]
    low, high = min(pos), max(neg, default=0.0)
    # With no overlap, sit between the classes; otherwise prefer missing a ring
    # over constant false alarms.
    threshold = (low + high) / 2 if low > high else high * 1.05
    return {
        "tones_hz": [round(t, 1) for t in tones],
        "threshold": round(threshold, 4),
        "min_level": min_level,
        "sample_rate": SAMPLE_RATE,
        "frame": FRAME,
        "hop": HOP,
        "tone_width_hz": TONE_WIDTH,
        "window_s": WINDOW_S,
        "lowest_chime_score": round(low, 4),
        "highest_background_score": round(high, 4),
        "separable": low > high,
    }


def leave_one_out(positives: list[np.ndarray], negatives: list[np.ndarray]) -> tuple[int, int]:
    """Train without each chime, then test on it. Returns (detected, total)."""
    detected = 0
    for i, clip in enumerate(positives):
        model = fit(positives[:i] + positives[i + 1 :], negatives)
        detected += model_scores(clip, model).max() > model["threshold"]
    return detected, len(positives)


def detect(audio: np.ndarray, model: dict, cooldown_s: float = 5.0) -> list[float]:
    """Times in seconds when the chime was detected."""
    scores = model_scores(audio, model)
    hits, last = [], -cooldown_s
    for i, score in enumerate(scores):
        t = (i * HOP + FRAME) / SAMPLE_RATE
        if score > model["threshold"] and t - last >= cooldown_s:
            hits.append(round(t, 2))
            last = t
    return hits


def load_clips(folder: Path) -> list[np.ndarray]:
    return [read_wav(p) for p in sorted(folder.glob("*.wav"))]


class ComputerMic:
    def __enter__(self):
        import sounddevice as sd

        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        self.stream.start()
        return self

    def __exit__(self, *_):
        self.stream.close()

    def read(self, samples: int) -> np.ndarray:
        block, _ = self.stream.read(samples)
        return block[:, 0]


class BoardMic:
    """Reads 16-bit PCM from the board's HTTP audio stream."""

    def __init__(self, url: str):
        self.url = url
        self.pending = bytearray()

    def __enter__(self):
        import requests

        self.response = requests.get(self.url, stream=True, timeout=(5, 10))
        self.response.raise_for_status()
        self.chunks = self.response.iter_content(chunk_size=2048)
        return self

    def __exit__(self, *_):
        self.response.close()

    def read(self, samples: int) -> np.ndarray:
        needed = samples * 2
        while len(self.pending) < needed:
            self.pending += next(self.chunks)
        data = bytes(self.pending[:needed])
        del self.pending[:needed]
        return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def open_mic(source: str | None):
    return BoardMic(source) if source else ComputerMic()


def cmd_record(args) -> None:
    folder = DATA_DIR / args.label
    start = len(list(folder.glob("*.wav"))) if folder.exists() else 0
    for i in range(args.count):
        input(f"[{i + 1}/{args.count}] Press Enter, then "
              f"{'ring the doorbell' if args.label == 'chime' else 'make everyday noise (TV, talking)'}...")
        print(f"Recording {args.seconds}s...")
        with open_mic(args.source) as mic:
            audio = mic.read(int(args.seconds * SAMPLE_RATE))
        path = folder / f"{start + i:03d}.wav"
        write_wav(path, audio)
        print(f"Saved {path} (peak {np.abs(audio).max():.2f})")


def cmd_train(args) -> None:
    positives = load_clips(DATA_DIR / "chime")
    negatives = load_clips(DATA_DIR / "background")
    if len(positives) < 3:
        raise SystemExit(f"Need at least 3 chime recordings, found {len(positives)}. "
                         "Run: uv run tools/chime.py record chime --count 10")
    if not negatives:
        print("Warning: no background recordings, so false alarms can't be measured.")
    model = fit(positives, negatives)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(model, indent=2) + "\n")
    detected, total = leave_one_out(positives, negatives)

    print(f"Tones: {model['tones_hz']} Hz")
    if "strike" in model:
        print(f"Single struck note: {model['strike']}")
    print(f"Threshold: {model['threshold']} (lowest chime {model['lowest_chime_score']}, "
          f"highest background {model['highest_background_score']})")
    print(f"Chimes detected when held out of training: {detected}/{total}")
    if not model["separable"]:
        print("Warning: background scores as high as the chime. Record closer to the "
              "bell, or check that your background clips don't contain the chime.")
    print(f"Saved {MODEL_PATH}")


def load_model() -> dict:
    if not MODEL_PATH.exists():
        raise SystemExit("No model yet. Run: uv run tools/chime.py train")
    return json.loads(MODEL_PATH.read_text())


def cmd_scan(args) -> None:
    hits = detect(read_wav(args.file), load_model())
    print(f"Chime at: {', '.join(f'{t}s' for t in hits)}" if hits else "No chime found")


def cmd_listen(args) -> None:
    model = load_model()
    keep = int((WINDOW_S + 0.2) * SAMPLE_RATE)
    buffer = np.zeros(keep, dtype=np.float32)
    last = 0.0
    print(f"Listening for {model['tones_hz']} Hz. Ring the bell. Ctrl+C to stop.")
    with open_mic(args.source) as mic:
        while True:
            block = mic.read(HOP * 4)
            buffer = np.concatenate((buffer[len(block):], block))
            score = float(model_scores(buffer, model).max())
            if args.verbose:
                print(f"score {score:.3f}", end="\r", flush=True)
            if score > model["threshold"] and time.time() - last > args.cooldown:
                last = time.time()
                print(f"{time.strftime('%H:%M:%S')} DOORBELL (score {score:.3f})", flush=True)
                if args.webhook:
                    import requests

                    try:
                        requests.post(args.webhook, json={"event": "doorbell"}, timeout=3)
                    except requests.RequestException as err:
                        print(f"Webhook failed: {err}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="record labelled samples from the mic")
    record.add_argument("label", choices=["chime", "background"])
    record.add_argument("--count", type=int, default=5)
    record.add_argument("--seconds", type=float, default=4.0)
    record.add_argument("--source", help="board audio URL (default: this computer's mic)")
    record.set_defaults(func=cmd_record)

    train = sub.add_parser("train", help="build the model from the recordings")
    train.set_defaults(func=cmd_train)

    scan = sub.add_parser("scan", help="look for the chime in a WAV file")
    scan.add_argument("file", type=Path)
    scan.set_defaults(func=cmd_scan)

    listen = sub.add_parser("listen", help="live detection from the mic")
    listen.add_argument("--source", help="board audio URL (default: this computer's mic)")
    listen.add_argument("--webhook", help="URL to POST to when the bell rings")
    listen.add_argument("--cooldown", type=float, default=5.0)
    listen.add_argument("--verbose", action="store_true")
    listen.set_defaults(func=cmd_listen)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
