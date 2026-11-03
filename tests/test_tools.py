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


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_default_clip_keeps_10_seconds_each_side_and_nothing_else(tmp_path):
    rec = recorder.Recorder(tmp_path)
    t, fps = 3_000_000.0, 10
    still = frame()
    for _ in range(30 * fps):             # 30s of nothing saves nothing
        rec.feed(still, t)
        t += 1 / fps
    assert not rec.recording and not rec.clips and not list(tmp_path.glob("*/*.mp4"))
    for x in range(60, 240, 6):           # 3s of someone walking past
        rec.feed(frame(x), t)
        t += 1 / fps
    for _ in range(25 * fps):
        rec.feed(still, t)
        t += 1 / fps
    assert len(rec.clips) == 1 and not rec.recording
    event = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
    assert 22 <= event["seconds"] <= 26   # 10 before + 3 of motion + 10 after


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


# --- Training a single-note bell from one recording ---

import chime_sim  # noqa: E402

BELL_HZ = 766.0


def struck_bell(seconds=2.4, fade_db_s=19.0):
    t = np.arange(int(seconds * RATE)) / RATE
    env = 10 ** (-fade_db_s * t / 20)
    return 0.13 * env * (np.sin(2 * np.pi * BELL_HZ * t) + 0.02 * np.sin(2 * np.pi * 4078 * t) * np.exp(-30 * t))


@pytest.fixture(scope="module")
def sim_model():
    source = chime_sim.trim_to_strike(struck_bell())
    tone = chime.find_tones([source], max_tones=1)[0]
    return chime_sim.train(source, tone, [], chimes=60, backgrounds=8), source, tone


def test_sim_learns_the_bell_note_and_its_fade(sim_model):
    model, _, tone = sim_model
    assert abs(tone - BELL_HZ) < 16
    low, high = model["strike"]["fade_db_s"]
    assert low < -19 < high < 0


def test_sim_detects_new_simulated_bells(sim_model):
    model, source, tone = sim_model
    rng = np.random.default_rng(1234)
    clips = [chime_sim.chime_clip(source, rng, [], tone) for _ in range(30)]
    assert chime_sim.caught(model, clips) >= 0.8


@pytest.mark.parametrize("kind", ["beep at same pitch", "other doorbell", "speech", "knocking"])
def test_sim_rejects_other_sounds(sim_model, kind):
    model, source, tone = sim_model
    rng = np.random.default_rng(4321)
    clips = [chime_sim.background_clip(kind, source, rng, [], tone) for _ in range(20)]
    assert chime_sim.caught(model, clips) <= 0.1


def test_steady_tone_at_the_bell_pitch_has_no_strike(sim_model):
    model, _, _ = sim_model
    t = np.arange(4 * RATE) / RATE
    steady = 0.2 * np.sin(2 * np.pi * BELL_HZ * t)
    steady[: RATE] = 0
    assert chime.detect(steady, model) == []


def test_musical_note_at_the_bell_pitch_is_rejected_by_its_overtones(sim_model):
    model, _, _ = sim_model
    t = np.arange(3 * RATE) / RATE
    env = 10 ** (-23 * t / 20)
    note_ = sum(np.sin(2 * np.pi * BELL_HZ * k * t) / k for k in range(1, 6)) * env
    audio = np.concatenate([np.zeros(RATE), 0.2 * note_, np.zeros(RATE)]) + rng.normal(0, 0.001, 5 * RATE)
    assert chime.detect(audio, model) == []


# --- The board's detector should agree with the Python one ---

CHECK = """
#include <stdio.h>
#include <vector>
#include "chime_detector.h"
int main(int argc, char **argv) {
  FILE *f = fopen(argv[1], "rb");
  fseek(f, 44, SEEK_SET);
  static ChimeDetector d;
  std::vector<int16_t> pcm(256);
  size_t n;
  while ((n = fread(pcm.data(), 2, pcm.size(), f)) > 0) {
    float t;
    if (d.feed(pcm.data(), n, &t)) printf("%.2f\\n", t);
  }
}
"""


@pytest.mark.skipif(not shutil.which("clang++"), reason="needs clang++")
def test_board_detector_matches_python(tmp_path):
    model = json.loads(chime.MODEL_PATH.read_text()) if chime.MODEL_PATH.exists() else None
    if model is None or "strike" not in model:
        pytest.skip("needs a trained single-note model")
    header_dir = Path(__file__).parent.parent / "firmware" / "src"
    src = tmp_path / "check.cpp"
    src.write_text(CHECK)
    binary = tmp_path / "check"
    subprocess.run(["clang++", "-std=c++17", "-O1", f"-I{header_dir}", str(src), "-o", str(binary)], check=True)
    test_rng = np.random.default_rng(11)
    t = np.arange(int(2.4 * RATE)) / RATE
    bell = 10 ** (-23 * t / 20) * np.sin(2 * np.pi * model["tones_hz"][0] * t) * 0.2
    audio = np.concatenate([np.zeros(RATE), bell, np.zeros(4 * RATE), bell, speech_like(4.0), np.zeros(RATE)])
    audio = audio + test_rng.normal(0, 0.001, len(audio))
    wav = tmp_path / "a.wav"
    chime.write_wav(wav, audio)
    expected = chime.detect(chime.read_wav(wav), model)
    got = [float(x) for x in subprocess.run([str(binary), str(wav)], capture_output=True, text=True, check=True).stdout.split()]
    assert expected, "the Python detector should find the bell"
    assert len(got) == len(expected)
    assert np.allclose(got, expected, atol=0.1)


# --- Serving clips to the Smart Home page ---

def make_clip(root, day="2026-11-02", name="101500"):
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.mp4").write_bytes(bytes(range(256)) * 4)
    (folder / f"{name}.jpg").write_bytes(b"picture")
    with (root / "events.jsonl").open("a") as log:
        log.write(json.dumps({"type": "motion", "start": f"{day}T10:15:00", "seconds": 23.0,
                              "clip": f"{day}/{name}.mp4"}) + "\n")


@pytest.fixture
def served(tmp_path):
    import requests

    make_clip(tmp_path, name="101500")
    make_clip(tmp_path, name="111500")
    server = recorder.clip_server(tmp_path, 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield requests, base, recorder.clips_token(tmp_path), tmp_path
    server.shutdown()


def test_clips_list_is_newest_first_and_skips_deleted(served):
    requests, base, token, root = served
    got = requests.get(f"{base}/{token}/clips.json")
    assert got.headers["Access-Control-Allow-Origin"] == "*"
    assert [c["video"] for c in got.json()] == ["2026-11-02/111500.mp4", "2026-11-02/101500.mp4"]
    (root / "2026-11-02/111500.mp4").unlink()
    assert [c["video"] for c in requests.get(f"{base}/{token}/clips.json").json()] == ["2026-11-02/101500.mp4"]


def test_clips_need_the_token_and_stay_in_their_folder(served):
    requests, base, token, root = served
    (root / "secret.txt").write_text("private")
    assert requests.get(f"{base}/clips.json").status_code == 404
    assert requests.get(f"{base}/wrong/clips.json").status_code == 404
    assert requests.get(f"{base}/wrong/2026-11-02/101500.mp4").status_code == 404
    for path in ("secret.txt", "events.jsonl", ".clips_token", "../secret.txt", "2026-11-02/../../secret.txt"):
        session = requests.Session()
        prepared = requests.Request("GET", f"{base}/{token}/x").prepare()
        prepared.url = f"{base}/{token}/{path}"
        assert session.send(prepared).status_code == 404, path


def test_videos_support_the_range_requests_phones_use(served):
    requests, base, token, _ = served
    url = f"{base}/{token}/2026-11-02/101500.mp4"
    whole = requests.get(url)
    assert whole.status_code == 200 and len(whole.content) == 1024 and whole.headers["Accept-Ranges"] == "bytes"
    part = requests.get(url, headers={"Range": "bytes=0-1"})
    assert part.status_code == 206 and part.content == bytes([0, 1]) and part.headers["Content-Range"] == "bytes 0-1/1024"
    tail = requests.get(url, headers={"Range": "bytes=-2"})
    assert tail.status_code == 206 and len(tail.content) == 2
    assert requests.get(url, headers={"Range": "bytes=5000-"}).status_code == 416


def test_deleting_a_clip_removes_it_for_good(served):
    requests, base, token, root = served
    url = f"{base}/{token}/2026-11-02/101500.mp4"
    assert requests.options(url).headers["Access-Control-Allow-Methods"] == "GET, POST, DELETE"
    assert requests.delete(url).status_code == 204
    assert not (root / "2026-11-02/101500.mp4").exists() and not (root / "2026-11-02/101500.jpg").exists()
    assert "101500" not in (root / "events.jsonl").read_text()
    assert [c["video"] for c in requests.get(f"{base}/{token}/clips.json").json()] == ["2026-11-02/111500.mp4"]
    assert requests.delete(url).status_code == 404


def test_deleting_needs_the_token_and_only_touches_clips(served):
    requests, base, token, root = served
    (root / "secret.txt").write_text("private")
    assert requests.delete(f"{base}/wrong/2026-11-02/101500.mp4").status_code == 404
    assert (root / "2026-11-02/101500.mp4").exists()
    assert requests.delete(f"{base}/{token}/2026-11-02/101500.jpg").status_code == 404
    assert (root / "2026-11-02/101500.jpg").exists()
    for path in ("secret.txt", "events.jsonl", ".clips_token", "../secret.txt"):
        session = requests.Session()
        prepared = requests.Request("DELETE", f"{base}/{token}/x").prepare()
        prepared.url = f"{base}/{token}/{path}"
        assert session.send(prepared).status_code == 404, path
    assert (root / "secret.txt").exists() and (root / ".clips_token").exists()


def test_deleting_the_last_clip_of_a_day_removes_its_folder(served):
    requests, base, token, root = served
    make_clip(root, day="2026-11-03", name="090000")
    assert requests.delete(f"{base}/{token}/2026-11-03/090000.mp4").status_code == 204
    assert not (root / "2026-11-03").exists() and (root / "2026-11-02").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_status_follows_a_recording_from_motion_to_saved(tmp_path):
    import requests

    rec = recorder.Recorder(tmp_path, pre_s=1, post_s=1)
    server = recorder.clip_server(tmp_path, 0, rec.status)
    url = f"http://127.0.0.1:{server.server_address[1]}/{recorder.clips_token(tmp_path)}/status.json"
    try:
        first = requests.get(url).json()
        assert first == {"state": "idle", "seconds": 0, "recording_on": True, "newest": None}
        t = 4_000_000.0
        for _ in range(20):
            rec.feed(frame(), t)
            t += 0.1
        for x in range(60, 240, 18):
            rec.feed(frame(x), t)
            t += 0.1
        assert rec.recording
        during = rec.status(now=rec.motion_began + 3)
        assert during == {"state": "recording", "seconds": 3, "recording_on": True}

        seen = {}
        real_run = recorder.subprocess.run

        def spying_run(*args, **kwargs):
            seen["while_encoding"] = requests.get(url).json()["state"]
            return real_run(*args, **kwargs)

        recorder.subprocess.run = spying_run
        try:
            rec.finish()
        finally:
            recorder.subprocess.run = real_run
        assert seen["while_encoding"] == "saving"
        done = requests.get(url).json()
        assert done["state"] == "idle" and done["newest"].endswith(".mp4")
    finally:
        server.shutdown()


def test_recording_can_be_turned_off_from_the_page_and_stays_off(tmp_path):
    import requests

    rec = recorder.Recorder(tmp_path, pre_s=1, post_s=1)
    server = recorder.clip_server(tmp_path, 0, rec.status, rec.set_paused)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    url = f"{base}/{recorder.clips_token(tmp_path)}/recording"
    try:
        assert requests.post(f"{base}/wrong/recording", data="off").status_code == 404
        assert requests.post(url, data="maybe").status_code == 400
        assert not rec.paused

        off = requests.post(url, data="off")
        assert off.status_code == 200 and off.json()["state"] == "off" and not off.json()["recording_on"]
        t = 5_000_000.0
        for x in [None] * 10 + list(range(60, 240, 18)):
            rec.feed(frame() if x is None else frame(x), t)
            t += 0.1
        assert not rec.recording and not rec.pre_roll
        assert recorder.Recorder(tmp_path).paused   # survives a restart

        assert requests.post(url, data="on").json()["recording_on"]
        assert not rec.paused
    finally:
        server.shutdown()
