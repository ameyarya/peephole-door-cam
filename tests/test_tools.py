"""Tests for the recorder and chime tools using simulated video and audio.

    uv run --with numpy --with pillow --with requests --with pytest pytest tests
"""
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import chime  # noqa: E402
import recorder  # noqa: E402

RATE = chime.SAMPLE_RATE


# --- Simulated video ---

def frame(box_x=None, brightness=90) -> bytes:
    """A hallway frame, optionally with a bright person-sized box."""
    image = Image.new("RGB", (320, 240), (brightness,) * 3)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 40, 60, 200), fill=(brightness // 2,) * 3)  # a door frame
    if box_x is not None:
        draw.rectangle((box_x, 60, box_x + 50, 220), fill=(25, 25, 35))  # dark clothes
    out = io.BytesIO()
    image.save(out, "JPEG", quality=70)
    return out.getvalue()


def test_iter_jpegs_handles_any_chunking():
    frames = [frame(), frame(100), frame(200)]
    stream = b"".join(b"\r\n--doorcamframe\r\nContent-Type: image/jpeg\r\n\r\n" + f for f in frames)
    for size in (1, 7, 4096, len(stream)):
        chunks = [stream[i : i + size] for i in range(0, len(stream), size)]
        assert list(recorder.iter_jpegs(chunks)) == frames


def test_detector_sees_motion_but_not_a_still_scene():
    d = recorder.MotionDetector()
    assert d.update(frame()) is False
    assert d.update(frame()) is False
    assert d.update(frame(150)) is True


def test_detector_ignores_lights_switching_on():
    d = recorder.MotionDetector()
    d.update(frame(brightness=60))
    assert d.update(frame(brightness=200)) is False
    assert d.update(frame(brightness=200)) is False


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_recorder_saves_one_clip_with_pre_and_post_roll(tmp_path):
    rec = recorder.Recorder(tmp_path, pre_s=2, post_s=2)
    t, fps = 1_000_000.0, 10
    def feed(jpeg, seconds):
        nonlocal t
        for _ in range(seconds * fps):
            rec.feed(jpeg, t)
            t += 1 / fps

    feed(frame(), 5)                      # still
    assert not rec.recording and not rec.clips
    for x in range(60, 240, 6):           # 3s of someone walking past
        rec.feed(frame(x), t)
        t += 1 / fps
    assert rec.recording
    feed(frame(), 20)                     # still again: background relearns, clip ends

    assert not rec.recording and len(rec.clips) == 1
    clip = rec.clips[0]
    assert clip.with_suffix(".jpg").exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name",
         "-of", "json", str(clip)], capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    assert info["streams"][0]["codec_name"] == "h264"
    assert 4 < float(info["format"]["duration"]) < 20
    event = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
    assert event["type"] == "motion" and event["clip"].endswith(".mp4")


def test_recorder_caps_clip_length(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("needs ffmpeg")
    rec = recorder.Recorder(tmp_path, pre_s=1, post_s=2, max_s=5)
    t = 2_000_000.0
    rec.feed(frame(), t)
    for i in range(100):
        t += 0.1
        rec.feed(frame(60 + (i % 2) * 150), t)
    assert len(rec.clips) >= 1


# --- Simulated audio ---

rng = np.random.default_rng(7)


def note(freq, seconds, decay=4.0):
    t = np.arange(int(seconds * RATE)) / RATE
    env = np.exp(-decay * t)
    return (np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 2.76 * t)) * env


def ding_dong(tones=(659, 523), volume=0.5, noise=0.01, lead=0.5, freq_jitter=0.0):
    f1, f2 = (f * (1 + rng.normal(0, freq_jitter)) for f in tones)
    audio = np.concatenate([np.zeros(int(lead * RATE)), note(f1, 0.7), note(f2, 1.2), np.zeros(int(0.5 * RATE))])
    return audio * volume + rng.normal(0, noise, len(audio))


def speech_like(seconds=4.0):
    """Noise shaped by moving formants and gated like syllables."""
    n = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.normal(0, 1, n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    shape = sum(np.exp(-((freqs - f) / w) ** 2) for f, w in [(500, 200), (1500, 300), (2500, 400)])
    audio = np.fft.irfft(spectrum * shape, n)
    gate = (np.sin(2 * np.pi * 4 * np.arange(n) / RATE) > -0.2).astype(float)
    return 0.3 * audio / np.abs(audio).max() * gate


def melody(seconds=4.0):
    """Music-like tones away from the chime's frequencies."""
    notes = [rng.choice([392, 440, 494, 587, 784, 880]) for _ in range(int(seconds * 3))]
    return 0.4 * np.concatenate([note(f, 1 / 3, decay=2) for f in notes])


def background_set():
    return [speech_like() for _ in range(3)] + [melody() for _ in range(3)] + [rng.normal(0, 0.05, 4 * RATE)]


@pytest.fixture(scope="module")
def trained():
    positives = [ding_dong(volume=rng.uniform(0.2, 0.7), freq_jitter=0.002) for _ in range(8)]
    negatives = background_set()
    return chime.fit(positives, negatives), positives, negatives


def test_finds_the_chime_tones(trained):
    model, _, _ = trained
    assert any(abs(t - 659) < 25 for t in model["tones_hz"])
    assert any(abs(t - 523) < 25 for t in model["tones_hz"])
    assert model["separable"]


def test_detects_new_chimes_including_quiet_ones(trained):
    model, _, _ = trained
    for volume in (0.7, 0.3, 0.1):
        assert chime.detect(ding_dong(volume=volume, noise=0.005), model), f"missed at volume {volume}"


def test_no_false_alarms_on_new_background(trained):
    model, _, _ = trained
    for clip in background_set():
        assert chime.detect(clip, model) == []


def test_rejects_a_single_beep_and_a_different_doorbell(trained):
    model, _, _ = trained
    beep = np.concatenate([note(659, 1.0), np.zeros(RATE)]) * 0.5
    assert chime.detect(beep, model) == []
    assert chime.detect(ding_dong(tones=(988, 784)), model) == []


def test_finds_the_time_of_a_chime_inside_a_long_recording(trained):
    model, _, _ = trained
    audio = np.concatenate([speech_like(5.0), ding_dong(lead=0), speech_like(10.0)])
    hits = chime.detect(audio, model)
    assert len(hits) == 1
    assert 5.0 <= hits[0] <= 8.0


def test_leave_one_out_on_simulated_chimes(trained):
    _, positives, negatives = trained
    detected, total = chime.leave_one_out(positives, negatives)
    assert detected == total


def test_wav_round_trip_and_resample(tmp_path):
    audio = 0.5 * np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE)
    path = tmp_path / "a.wav"
    chime.write_wav(path, audio)
    assert np.allclose(chime.read_wav(path), audio, atol=1e-3)


def test_board_mic_reassembles_pcm_across_chunks():
    pcm = (np.arange(-500, 500, dtype=np.int16) * 20).astype("<i2").tobytes()
    mic = chime.BoardMic("unused")
    mic.chunks = iter(pcm[i : i + 37] for i in range(0, len(pcm), 37))
    audio = np.concatenate([mic.read(300), mic.read(700)])
    assert np.allclose(audio * 32768, np.arange(-500, 500) * 20)
