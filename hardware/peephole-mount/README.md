# Door unit

A housing for the whole XIAO ESP32S3 Sense, with a tube that slides into the door
viewer's inner bore. It films through the existing viewer, so the door isn't changed
and its fire rating isn't affected. The unit hangs from the tube on its own, with
nothing stuck to the door.

![Housing with the board inside](preview.png)

- **Back:** open. The board goes in from the back and snaps past two small lips.
- **Bottom:** USB-C plug, plus room for a microSD card.
- **Top:** a slot for the WiFi antenna's cable.
- **Front:** the camera's lens barrel sits in the tube's opening, which centres it.

Housing 25.4 × 21.5 × 12.8 mm. The tube is 10.3 mm across and reaches 16 mm into the
viewer, stopping 2 mm short of the glass.

The board's dimensions come from Seeed's 3D model of the XIAO ESP32S3 Sense. The model
was checked against it: no part of the board touches the plastic, with at least
0.2 mm to spare. Not printed or fit-tested yet.

## Print
1. Print `stl/fit_test.stl`. The three rings are 10.2, 10.3 and 10.4 mm: the thinnest
   collar is 10.2 and the thickest is 10.4. Find the tightest one that still slides.
2. If it isn't 10.3, change `tube_od` in `peephole_mount.scad` and re-export.
3. Print `stl/housing.stl` with the open back on the bed. No supports: the front
   bridges across. PETG, 0.12 mm layers, 3+ walls.

The camera may differ slightly from Seeed's model, which shows the older OV2640. If
the board is tight, raise `gap`.

## Fit
- Slide the tube in and out while watching `http://door-cam.local/` until the picture
  is best, then rotate the unit to level the image.
- Clip the USB cable to the door just below the unit, so a tug on the cable can't pull
  the tube out.
- Point the antenna up, away from the door.

## Limits
The camera's square body is wider than the bore, so only the lens barrel enters the
tube. The lens can't get closer to the glass than the bore depth minus the barrel's
length, and sliding the tube out only moves it farther away.
