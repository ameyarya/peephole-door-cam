# Testing the software on a bench

You can test everything before building the hardware. Two firmware builds:

| Build | Board | Use |
|---|---|---|
| `xiao_sense` | XIAO ESP32S3 Sense | The door unit: mic always live, camera on whenever someone watches, doorbell detection on the board, updates over WiFi |
| `esp32cam` | AI-Thinker ESP32-CAM | Video only, it has no mic. Train on your computer's mic instead |

Before the first XIAO flash, create the token that protects the mic and updates:

```bash
cp src/secrets.h.example src/secrets.h
```

Then put a long random string in it. `secrets.h` is git-ignored. Without a token the
board still works, but refuses mic listeners and updates.

**The mic is always on.** Recording conversations without consent is illegal in many
places, including hallways and shared spaces. Check your local rules, and tell the
people you live with. Nothing is saved on the board: audio only leaves it when someone
with the token listens.

## 1. Flash the board
**XIAO:** plug it in over USB-C. From this folder:

```bash
pio run -e xiao_sense -t upload
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
| `/status` | Signal strength, memory, uptime, chip temperature (`chip_c`) and whether the camera is asleep, as JSON |
| `/control?framesize=vga&quality=12&vflip=1&hmirror=0` | Change settings until the next reboot (`qvga`, `vga`, `svga`, `xga`, `hd`) |
| `:81/stream` | MJPEG stream, up to 4 viewers at once |
| `:82/audio?token=…` | Live 16 kHz mono PCM from the mic, up to 2 listeners. Needs the token |
| `POST /ota` | Firmware update, needs the token. Use `./ota.sh` |

The stream has no password, so keep it on your home network and never
port-forward it.

**Heat.** The board runs warm, and the housing is PLA, which softens at about 55 °C. To
keep it cool, the camera goes to standby 10 seconds after the last viewer leaves and
wakes in under half a second for the next one. The camera runs at half its usual clock
and the stream is capped at 10 frames a second. The radio transmits at a quarter of full
power, and the processor runs at 160 MHz instead of 240. The radio itself stays fully
awake: its power save would drop the board's draw so low that many power banks switch off.

Measured on the chip (`chip_c`): about 42 °C and falling
with the camera asleep, and about 64 °C streaming without a break. While motion recording
is on, the recorder counts as a viewer, so the camera never sleeps. Turn recording off
when you don't need it.

## 4. Record motion clips
From the repo root:

```bash
uv run tools/recorder.py
```

It watches all the time but only saves clips when something moves, with 10 seconds
from before and 10 seconds after (`--pre` and `--post`). It only runs while this
computer is awake. Clips go to `recordings/YYYY-MM-DD/`, which git ignores. Walk past
the camera to test it.

It also serves the clips to your network for the Smart Home page, through a private
link it prints when it starts (`--serve-port 0` turns that off). Paste the link into
the page's Settings with the Mac's real address. Open the door camera and tap
**Recordings** to play, save or delete clips. Deleting is permanent. If it triggers too easily, raise `--sensitivity`, for example to `0.03`.

**Motion recording** in the page's Settings turns recording off and on. While it's off, the
recorder lets go of the camera and saves nothing, and it stays off after a restart. When you
open the page, it shows one notice if there's new motion since your last visit, for example
"New motion at Front door 2 mins ago". Tap it to see the recordings.

## 5. Train on your doorbell
Train with the mic that will do the listening. Put the XIAO where it will live (a USB power bank works), then from the repo
root:

```bash
uv run tools/chime.py record chime --count 10 --source 'http://door-cam.local:82/audio?token=YOUR_TOKEN'
```

```bash
uv run tools/chime.py record background --seconds 30 --count 5 --source 'http://door-cam.local:82/audio?token=YOUR_TOKEN'
```

For the background clips, include everyday noise: TV, talking, music, a knock.
Keep the chime out of them.

```bash
uv run tools/chime.py train
```

```bash
uv run tools/chime.py listen --verbose --source 'http://door-cam.local:82/audio?token=YOUR_TOKEN'
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

**Status: works through the XIAO's mic on phone playback.** Rings near the board
trigger it, but it isn't proven at the door's real distance. Earlier plays from a
monitor and earbuds didn't trigger it, and the reason wasn't established.

Limits to expect:
- The scores only cover simulated conditions.
- Simulated bell levels may be too loud. The XIAO's mic reads low, so a real bell
  may land below the range it does well in.
- A neighbor's identical bell, heard loudly enough, will also trigger it.
- A very short beep at the bell's pitch can look like a fast-dying bell. The
  simulator's report shows how often.
- A loud TV can hide the bell: detection falls off sharply when the noise is as
  loud as the bell.

## 6. Put the model on the board and ring your TV
Write the trained model into the firmware, then flash the `xiao_sense` build:

```bash
uv run tools/chime.py header
```

```bash
pio run -e xiao_sense -t upload
```

On a ring the board POSTs to a URL you set once. It's kept on the board, because it
may hold a secret. For the [Smart Home app](https://github.com/ameyarya/fire-tv-home-hub)
it's `http://<TV>:8765/api/<secret>/doorbell?id=<camera id>`:

```bash
curl -X POST --data "<your URL>" http://door-cam.local/doorbell-url
```

To test the link without a bell:

```bash
curl -X POST http://door-cam.local/ring
```

If a ring doesn't trigger it, `/status` shows the numbers for the last bell-like
sound under `last_strike` (numbers only, no audio). Compare them with the limits in
`firmware/src/chime_model.h`. After an alert, the board ignores the bell for 5 seconds.

## 7. Update over WiFi
After the first USB flash, the Mac only needs to be on the same network:

```bash
./ota.sh
```

A new firmware is on trial until the camera and WiFi come up. If it restarts or crashes
first, the board goes back to the previous firmware by itself. If a new firmware hangs
without restarting, or the board can't reach WiFi at all, you'll need USB. `running` in
`/status` shows which of the two firmware slots is active.

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
