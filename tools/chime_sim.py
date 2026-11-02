#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "requests"]
# ///
"""Train the chime detector from one recording, without ringing the bell again.

    uv run tools/chime_sim.py doorbell.wav

Simulates the recording in different rooms, at different volumes, through
different mics and over background noise, then tests the result on simulations
it never trained on. WAV files in tools/chime_data/room/ are used as real
background noise: room_train* for training and everything else for testing.

The scores measure how well it handles simulated conditions, not your real door.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import chime

RATE = chime.SAMPLE_RATE
CLIP_S = 5.0


def db(value: float) -> float:
    return 10 ** (value / 20)


def fit_length(audio: np.ndarray, n: int, rng) -> np.ndarray:
    if len(audio) >= n:
        start = rng.integers(0, len(audio) - n + 1)
        return audio[start : start + n]
    return np.resize(audio, n)


def trim_to_strike(source: np.ndarray) -> np.ndarray:
    """Cuts the lead-in, so simulated clips control where the strike lands."""
    levels = chime.frame_levels(chime.power_frames(source))
    first = int(np.argmax(levels > levels.max() * 0.01))
    return source[max(first * chime.HOP - 200, 0) :]


def change_speed(audio: np.ndarray, factor: float) -> np.ndarray:
    n = int(len(audio) / factor)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)


def filtered(audio: np.ndarray, curve) -> np.ndarray:
    spectrum = np.fft.rfft(audio)
    return np.fft.irfft(spectrum * curve(np.fft.rfftfreq(len(audio), 1 / RATE)), len(audio))


def add_room(audio: np.ndarray, rng) -> np.ndarray:
    """Reverb: an echo tail of decaying noise."""
    rt60 = rng.uniform(0.15, 0.8)
    t = np.arange(int(rt60 * RATE)) / RATE
    tail = rng.normal(0, 1, len(t)) * np.exp(-6.9 * t / rt60)
    tail *= rng.uniform(0.05, 0.5) / np.sqrt((tail**2).sum())
    tail[0] = 1.0
    size = len(audio) + len(tail)
    return np.fft.irfft(np.fft.rfft(audio, size) * np.fft.rfft(tail, size), size)[: len(audio)]


def change_mic(audio: np.ndarray, rng) -> np.ndarray:
    """A different mic: a low cut, a tilt, and random bumps in its response."""
    low_cut = rng.uniform(80, 300)
    tilt = rng.uniform(-3, 3)
    points = np.geomspace(50, RATE / 2, 9)
    bumps = rng.uniform(-4, 4, len(points))

    def curve(f):
        f = np.maximum(f, 1.0)
        gain_db = tilt * np.log2(f / 1000) + np.interp(np.log(f), np.log(points), bumps)
        return db(gain_db) * (f / np.sqrt(f**2 + low_cut**2))

    return filtered(audio, curve)


# --- Sounds that aren't the doorbell ---

def harmonic_note(freq, seconds, rng, decay=3.0):
    t = np.arange(int(seconds * RATE)) / RATE
    tone = sum(rng.uniform(0.2, 1) / k * np.sin(2 * np.pi * freq * k * t + rng.uniform(0, 6)) for k in range(1, 7))
    return tone * np.exp(-decay * t) * np.minimum(t / 0.005, 1)


def speech(n, rng):
    formants = [(rng.uniform(300, 800), 180), (rng.uniform(1000, 1800), 280), (rng.uniform(2200, 3000), 380)]
    audio = filtered(rng.normal(0, 1, n), lambda f: sum(np.exp(-(((f - c) / w) ** 2)) for c, w in formants))
    syllables = np.sin(2 * np.pi * rng.uniform(3, 6) * np.arange(n) / RATE + rng.uniform(0, 6)) > -0.2
    return audio * syllables


def music(n, rng):
    """Piano-like notes, including ones close to the bell's pitch."""
    audio = np.zeros(n)
    step = int(RATE * rng.uniform(0.2, 0.6))
    for start in range(0, n - step, step):
        midi = rng.integers(55, 88)
        note = harmonic_note(440 * 2 ** ((midi - 69) / 12), step * 2 / RATE, rng)
        end = min(start + len(note), n)
        audio[start:end] += note[: end - start]
    return audio


def bark(n, rng):
    audio = np.zeros(n)
    for _ in range(rng.integers(1, 5)):
        burst = harmonic_note(rng.uniform(250, 800), 0.2, rng, decay=12) + 0.5 * rng.normal(0, 1, int(0.2 * RATE))
        start = rng.integers(0, n - len(burst))
        audio[start : start + len(burst)] += burst
    return audio


def knock(n, rng):
    audio = np.zeros(n)
    burst = filtered(rng.normal(0, 1, 800), lambda f: 1 / (1 + (f / 400) ** 2)) * np.exp(-np.arange(800) / 120)
    for _ in range(rng.integers(1, 5)):
        start = rng.integers(0, n - 800)
        audio[start : start + 800] += burst
    return audio


def appliance_beep(n, rng, tone_hz):
    """Steady beeps right at the bell's pitch, like a microwave. No fade."""
    audio = np.zeros(n)
    length = int(rng.uniform(0.15, 1.5) * RATE)
    for start in range(int(0.5 * RATE), n - length, length * 2):
        t = np.arange(length) / RATE
        audio[start : start + length] += np.sin(2 * np.pi * tone_hz * t)
    return audio


def other_bell(n, rng, source, tone_hz):
    """A bell with the same shape but another pitch, such as a different doorbell."""
    away = rng.choice([-1, 1]) * rng.uniform(0.15, 0.6)
    bell = change_speed(source, 1 + away)
    audio = np.zeros(n)
    start = rng.integers(RATE // 2, max(n - len(bell), RATE // 2 + 1))
    end = min(start + len(bell), n)
    audio[start:end] = bell[: end - start]
    return audio


def interference(kind: str, n: int, rng, source, tone_hz) -> np.ndarray:
    if kind == "speech":
        return speech(n, rng)
    if kind == "music":
        return music(n, rng)
    if kind == "tv":
        return speech(n, rng) / 2 + music(n, rng) / 3
    if kind == "dog barking":
        return bark(n, rng)
    if kind == "knocking":
        return knock(n, rng)
    if kind == "beep at same pitch":
        return appliance_beep(n, rng, tone_hz)
    if kind == "other doorbell":
        return other_bell(n, rng, source, tone_hz)
    raise ValueError(kind)


NOISY_KINDS = ["speech", "music", "tv", "dog barking", "knocking"]
FALSE_ALARM_KINDS = NOISY_KINDS + ["beep at same pitch", "other doorbell"]


def normalized(audio: np.ndarray, peak_db: float) -> np.ndarray:
    return audio / max(np.abs(audio).max(), 1e-9) * db(peak_db)


def noise_bed(n, rng, room_noise) -> np.ndarray:
    if room_noise:
        return fit_length(room_noise[rng.integers(0, len(room_noise))], n, rng)
    return rng.normal(0, db(-60), n)


def chime_clip(source, rng, room_noise, tone_hz, kind=None, peak_db=None, snr_db=None) -> np.ndarray:
    n = int(CLIP_S * RATE)
    bell = change_speed(source, 1 + rng.uniform(-0.005, 0.005))
    bell = add_room(change_mic(bell, rng), rng)
    peak_db = rng.uniform(-45, -12) if peak_db is None else peak_db
    bell = normalized(bell, peak_db)
    clip = noise_bed(n, rng, room_noise).copy()
    start = rng.integers(RATE // 2, n - len(bell) - RATE // 4)
    clip[start : start + len(bell)] += bell
    if kind:
        snr_db = rng.uniform(5, 25) if snr_db is None else snr_db
        clip += normalized(interference(kind, n, rng, source, tone_hz), peak_db - snr_db)
    return np.clip(clip, -1, 1)


def background_clip(kind, source, rng, room_noise, tone_hz, peak_db=None) -> np.ndarray:
    n = int(CLIP_S * RATE)
    sound = change_mic(interference(kind, n, rng, source, tone_hz), rng)
    sound = normalized(add_room(sound, rng), rng.uniform(-40, -8) if peak_db is None else peak_db)
    return np.clip(noise_bed(n, rng, room_noise) + sound, -1, 1)


def train(source, tone_hz, room_noise, seed=1, chimes=200, backgrounds=20) -> dict:
    rng = np.random.default_rng(seed)
    positives = []
    for _ in range(chimes):
        kind = rng.choice(NOISY_KINDS) if rng.random() < 0.5 else None
        positives.append(chime_clip(source, rng, room_noise, tone_hz, kind))
    negatives = [
        background_clip(kind, source, rng, room_noise, tone_hz)
        for kind in FALSE_ALARM_KINDS
        for _ in range(backgrounds)
    ]
    negatives += [noise_bed(int(CLIP_S * RATE), rng, room_noise) for _ in range(20)]
    return chime.fit_strike(positives, negatives, tone_hz)


def caught(model, clips) -> float:
    return float(np.mean([bool(chime.detect(c, model)) for c in clips]))


def evaluate(model, source, tone_hz, room_noise, seed=2026, count=60) -> dict:
    rng = np.random.default_rng(seed)
    results: dict = {"chime_by_volume": {}, "chime_by_noise": {}, "false_alarms": {}}
    for peak in (-12, -25, -35, -45, -55):
        results["chime_by_volume"][f"{peak} dBFS"] = caught(
            model, [chime_clip(source, rng, room_noise, tone_hz, peak_db=peak) for _ in range(count)])
    for kind in NOISY_KINDS:
        for snr in (20, 10, 0):
            results["chime_by_noise"][f"{kind}, noise {snr} dB below the bell"] = caught(
                model, [chime_clip(source, rng, room_noise, tone_hz, kind, peak_db=-25, snr_db=snr) for _ in range(count // 2)])
    for kind in FALSE_ALARM_KINDS:
        results["false_alarms"][kind] = caught(
            model, [background_clip(kind, source, rng, room_noise, tone_hz) for _ in range(count)])
    results["false_alarms_per_hour"] = false_alarms_per_hour(model, source, tone_hz, room_noise, rng)
    return results


def false_alarms_per_hour(model, source, tone_hz, room_noise, rng, minutes=60) -> float:
    """Long-run rate on simulated TV, music and speech. Short tests can hide this."""
    hits = 0
    clips = int(minutes * 60 / CLIP_S)
    for _ in range(clips):
        kind = rng.choice(["tv", "music", "speech"])
        hits += len(chime.detect(background_clip(kind, source, rng, room_noise, tone_hz), model))
    return hits * 60 / minutes


def load_room_noise() -> tuple[list[np.ndarray], list[np.ndarray]]:
    folder = chime.DATA_DIR / "room"
    train_noise, test_noise = [], []
    for path in sorted(folder.glob("*.wav")) if folder.exists() else []:
        (train_noise if path.name.startswith("room_train") else test_noise).append(chime.read_wav(path))
    return train_noise, test_noise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recording", type=Path, help="one clean recording of the doorbell (16-bit WAV)")
    args = parser.parse_args()

    source = trim_to_strike(chime.read_wav(args.recording))
    tones = chime.find_tones([source], max_tones=1)
    if not tones:
        raise SystemExit("No clear tone found in that recording")
    tone_hz = tones[0]
    room_train, room_test = load_room_noise()
    print(f"Bell note: {tone_hz:.0f} Hz. Real room noise clips: {len(room_train)} train, {len(room_test)} test.")

    model = train(source, tone_hz, room_train)
    chime.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    chime.MODEL_PATH.write_text(json.dumps(model, indent=2) + "\n")
    print(f"Saved {chime.MODEL_PATH}")
    print(json.dumps({k: model[k] for k in ("strike", "threshold", "lowest_chime_score", "highest_background_score", "separable")}, indent=2))

    results = evaluate(model, source, tone_hz, room_test or room_train)
    per_hour = results.pop("false_alarms_per_hour")
    for section, rows in results.items():
        print(f"\n{section.replace('_', ' ')}:")
        for name, rate in rows.items():
            print(f"  {name:48s} {rate:6.0%}")

    print(f"\nFalse alarms on an hour of simulated TV, music and speech: {per_hour:.0f}")

    if room_test:
        hits = sum(len(chime.detect(clip, model)) for clip in room_test)
        minutes = sum(len(clip) for clip in room_test) / RATE / 60
        print(f"\nReal room audio it never trained on: {hits} false alarms in {minutes:.1f} minutes")


if __name__ == "__main__":
    main()
