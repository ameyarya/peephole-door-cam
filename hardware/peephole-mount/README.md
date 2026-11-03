# Door unit

A housing for the whole XIAO ESP32S3 Sense, with a tube that slides into the door
viewer's inner bore. It films through the existing viewer, so the door isn't changed
and its fire rating isn't affected. The unit hangs from the tube on its own, with
nothing stuck to the door.

![Housing with the board inside](preview.png)

- **Back:** the board goes in from the back and snaps past two small lips. A lid snaps
  over the outside of the back, and two bars on it hold the board down.
- **Bottom:** USB-C plug, plus room for a microSD card.
- **Top:** a slot for the WiFi antenna's cable.
- **Front:** the tube is in the middle of the housing's face. The camera comes off its
  place on the board on its flex cable, about 7 mm toward the antenna end and 2.4 mm
  forward, into a square 8.2 mm socket at the base of the tube, which holds it square and centred. The socket's
  corners stop it, and the lens goes on into the tube.

Housing 24.8 × 20.9 × 15 mm, lid 24.8 × 24.4 × 4.2 mm, about 4 g of plastic in all. The tube is 10.1 mm across, with four
thin ribs that reach 10.6 mm. They crush slightly as it goes into the 10.5 mm bore, so it
grips without a fit test. It reaches 16 mm into the viewer, stopping 2 mm short of the glass.

The board's dimensions come from Seeed's 3D model of the XIAO ESP32S3 Sense. The model
was checked against it, with the camera moved forward into its socket: only the camera
touches the plastic, at the socket's stop, and the lid clears the board by 0.15 mm.

## Versions
| File | What changed |
|---|---|
| `stl/housing_v1.stl` | First print. The tube's ribs, board pocket, USB and antenna slots fit. The round opening didn't hold the camera, and the board fell out of the open back |
| `stl/housing_v2.stl`, `stl/lid_v2.stl` | Tube moved to the middle of the housing, a square socket for the camera at its base, and a snap-on lid. Not printed yet |

## Print
Print `stl/housing_v2.stl` with the open back on the bed, tube up, and `stl/lid_v2.stl`
flat side down. No supports. PETG or PLA, 0.12 mm layers, 0.4 mm nozzle, 100% infill (the walls are only
three lines thick anyway).

If the tube is too loose in the viewer, raise `rib_d` by 0.1 and print again. If it's
too tight, lower it.

The camera may differ slightly from Seeed's model, which shows the older OV2640. If
the board is tight, raise `gap`. If the camera won't go into its socket, raise `cam_fit`.
If the lid is too hard to snap on, lower `snap`. If the camera's flex won't reach the
socket, move the tube back toward the camera with `tube_off` (`[6.9, -0.6]` is where v1 had it).

## Assemble
Ease the camera forward off the board on its flex and press it into the square socket,
lens first. Then push the board in past the lips and snap the lid over the back. The
lid's side walls go on the long sides; the ends stay open for the USB plug and the antenna.

## Fit
- Slide the tube in and out while watching `http://door-cam.local/` until the picture
  is best, then rotate the unit to level the image.
- Clip the USB cable to the door just below the unit, so a tug on the cable can't pull
  the tube out.
- Point the antenna up, away from the door.

## Limits
The camera's square body is wider than the bore, so only the lens barrel enters the
tube. It sits 2.5 mm into it. The lens can't get closer to the glass than the bore depth minus the barrel's
length, and sliding the tube out only moves it farther away.
