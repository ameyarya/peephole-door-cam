# Peephole door cam

A renter-friendly door camera that replaces the peephole viewer. A XIAO
ESP32S3 Sense inside the apartment streams video, listens for the doorbell
chime, and triggers a live view on the TV. Recording and package tracking run
on a home server.

```
[Camera node at door]  --WiFi-->  [Home server]  ------->  [TV / phone]
 XIAO ESP32S3 Sense                Home Assistant           PiPup overlay / cast
 - listens for chime               go2rtc (restream)        push notification
 - streams MJPEG                   Frigate (record, detect)
```

## Layout
| Path | What |
|---|---|
| `hardware/peephole-sleeve/` | Clamshell sleeve that holds the camera in the door hole, plus the inside clip |
| `hardware/enclosure/` | Box for the XIAO that sticks to the inside of the door over the sleeve |
| `hardware/*/stl/` | Rendered STLs, ready to print |
| `hardware/README.md` | Measurements, assembly, print settings |
| `firmware/` | Firmware for the XIAO and ESP32-CAM, and the [bench test guide](firmware/README.md) |
| `tools/recorder.py` | Records motion clips from the stream |
| `tools/chime.py` | Trains and tests a detector on your own doorbell |

Models are parametric OpenSCAD. Change values in the Customizer and re-export.

## Status
- [x] Sleeve and enclosure designed (door: 34mm thick, ~13mm hole)
- [ ] Test print and fit
- [ ] Check camera module and XIAO dimensions against the models
- [x] XIAO firmware: 640x480 live stream, up to 4 viewers, mic audio for training (tested on a board)
- [x] Motion recorder (tested on a live stream)
- [x] Chime trainer (tested on simulated chimes only)
- [ ] ESP32-CAM build tested on a real board (compiles only)
- [ ] Train on a real doorbell with the XIAO's mic
- [ ] Chime detection running on the board itself
- [ ] Home Assistant: TV popup + notifications
- [ ] Frigate: recording + package detection

The door is fire-rated (20-minute viewer). The printed sleeve is for
prototyping. See `hardware/README.md`.

## License
MIT. See `LICENSE`. Keep WiFi credentials, keys and photos of your own door in `secrets.yaml`, `.env` or `private/`; they are git-ignored.
