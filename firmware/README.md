# Testing the software on a bench

You can test everything before building the hardware. Three firmware builds:

| Build | Board | Use |
|---|---|---|
| `xiao_sense_training` | XIAO ESP32S3 Sense | Video plus a mic audio stream, for doorbell training. **Don't leave this running at the door**: anyone on your network could listen to the room |
| `xiao_sense` | XIAO ESP32S3 Sense | Video only |
| `esp32cam` | AI-Thinker ESP32-CAM | Video only, it has no mic. Train on your computer's mic instead |

## 1. Flash the board
**XIAO:** plug it in over USB-C. From this folder:

```bash
pio run -e xiao_sense_training -t upload
```

If it can't connect, hold BOOT while plugging it in.

**AI-Thinker ESP32-CAM:** it needs a USB base or serial adapter.
- **ESP32-CAM-MB USB base:** if flashing fails, hold `IO0` on the base, tap `RST`,
  then release `IO0`.
- **USB-serial adapter (FTDI or CP2102):** connect `5V`→`5V`, `GND`→`GND`,
  `U0R`←`TX` and `U0T`→`RX`. Jumper `IO0` to `GND`, then tap `RST`. Remove the
  jumper and tap `RST` again after flashing.

```bash
pio run -e esp32cam -t upload
```

Watch the boot log with:

```bash
pio device monitor
```

If `pio` isn't on your path, it's at `~/.platformio/penv/bin/pio`.

**Reusing a board?** The XIAO build keeps WiFi settings in the standard storage area at
`0x9000`, so saved WiFi can carry over from other ESP-IDF firmware with the same
layout. Back up first if you want the old firmware
back; flashing replaces it.

## 2. Connect it to WiFi
If the board has no saved WiFi, it opens a hotspot called **door-cam-setup**. Join it from
your phone, pick your WiFi network and enter the password. The password is
stored only on the board. ESP32 boards only support 2.4GHz networks.

To clear the saved WiFi, run `pio run -t erase`, then flash again.

## 3. Check the stream
Open `http://door-cam.local/`, or the IP address from the boot log.

| URL | What it does |
|---|---|
| `/` | Test page with the live view |
| `/capture` | One JPEG |
| `/status` | Signal strength, memory, uptime as JSON |
| `/control?framesize=vga&quality=12&vflip=1&hmirror=0` | Change settings until the next reboot (`qvga`, `vga`, `svga`, `xga`, `hd`) |
| `:81/stream` | MJPEG stream, up to 4 viewers at once |
| `:82/audio` | 16 kHz mono PCM from the mic, `xiao_sense_training` only |

The stream has no password, so keep it on your home network and never
port-forward it.

## 4. Record motion clips
From the repo root:

```bash
uv run tools/recorder.py
```

Clips go to `recordings/YYYY-MM-DD/`, which git ignores. Walk past the camera to
test it. If it triggers too easily, raise `--sensitivity`, for example to `0.03`.

## 5. Train on your doorbell
Train with the mic that will do the listening. With the XIAO on the training
build, put it where it will live (a USB power bank works), then from the repo
root:

```bash
uv run tools/chime.py record chime --count 10 --source http://door-cam.local:82/audio
```

```bash
uv run tools/chime.py record background --seconds 30 --count 5 --source http://door-cam.local:82/audio
```

For the background clips, include everyday noise: TV, talking, music, a knock.
Keep the chime out of them.

```bash
uv run tools/chime.py train
```

```bash
uv run tools/chime.py listen --verbose --source http://door-cam.local:82/audio
```

On a board with no mic, leave out `--source` to use your computer's mic.

`train` prints the tones it found and how many chimes it caught when each one
was held out of training. Recordings and the model stay in `tools/chime_data/`,
which git ignores.

### Can't ring the bell repeatedly?
One clean recording is enough to start. Convert it, then train on simulated
versions of it in different rooms, at different volumes, through different mics
and over background noise:

```bash
mkdir -p tools/chime_data/source
```

```bash
ffmpeg -i my_doorbell.m4a -ac 1 -ar 16000 -c:a pcm_s16le tools/chime_data/source/doorbell.wav
```

```bash
uv run tools/chime_sim.py tools/chime_data/source/doorbell.wav
```

WAV files of ordinary room noise in `tools/chime_data/room/` make it more
realistic: `room_train*` files for training, any others for testing.

Single-note bells are matched on pitch, sudden strike, steady fade and lack of
overtones.

**Status: unproven on a real mic.** In simulation it does well, but it detected
none of 28 speaker and earbud playbacks through the XIAO's mic (some possibly
silent or masked by a TV), and the cause isn't known yet. Check the mic responds
to speech up close, then test with a real ring, before relying on it.

Limits to expect:
- The scores only cover simulated conditions.
- Simulated bell levels may be too loud. The XIAO's mic reads low, so a real bell
  may land below the range it does well in.
- A neighbor's identical bell, heard loudly enough, will also trigger it.
- A loud TV can hide the bell: detection falls off sharply when the noise is as
  loud as the bell.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| Boot loops or `Brownout detector was triggered` | Weak power. Use a 5V supply that can deliver at least 1A, and a short cable |
| `Camera init failed` | Reseat the camera ribbon and its latch |
| `Failed to connect to ESP32` | The board isn't in flash mode. See step 1 |
| `door-cam.local` doesn't open | Use the IP address from the boot log |
| A viewer gets `503` | All 4 viewer slots are taken. A closed viewer's slot takes up to about 5 seconds to free |
| Choppy video | Weak WiFi. Check `rssi` in `/status` (better than -70 is good) or try `framesize=qvga` |

## Tests
The tools have tests that use simulated video and audio, so they need no
hardware. From the repo root:

```bash
uv run --no-project --with numpy --with pillow --with requests --with pytest pytest tests
```
