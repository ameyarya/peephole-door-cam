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

Models are parametric OpenSCAD. Change values in the Customizer and re-export.

## Status
- [x] Sleeve and enclosure designed (door: 34mm thick, ~13mm hole)
- [ ] Test print and fit
- [ ] Check camera module and XIAO dimensions against the models
- [ ] Firmware: camera stream + chime detection
- [ ] Home Assistant: TV popup + notifications
- [ ] Frigate: recording + package detection

The door is fire-rated (20-minute viewer). The printed sleeve is for
prototyping. See `hardware/README.md`.

## License
MIT. See `LICENSE`. Keep WiFi credentials, keys and photos of your own door in `secrets.yaml`, `.env` or `private/`; they are git-ignored.
