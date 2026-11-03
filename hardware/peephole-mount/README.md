# Peephole mount

Films through the existing door viewer, so the door isn't changed and its fire
rating isn't affected. A tube slides into the viewer's bore, and a cup on its end
grips the XIAO's square camera module, with the board behind it and USB pointing down.

## Print
1. Print `stl/fit_test.stl`. The three rings are 10.2, 10.3 and 10.4 mm: the thinnest
   collar is 10.2 and the thickest is 10.4. Find the tightest one that still slides.
2. If it isn't 10.3, change `tube_od` in `peephole_mount.scad` and re-export.
3. Measure the camera module and set `cam_w`. It's only estimated from a photo so far.
4. Print `stl/mount.stl` with the tube end on the bed. No supports. PETG, 0.12 mm
   layers, 3+ walls.

## Fit
- Slide the tube in and out while watching `http://door-cam.local/` until the picture
  is best, then rotate it to level the image.
- Take the weight off the tube: clip the USB cable to the door just below the board,
  so a tug on the cable can't pull it out.
- Keep the WiFi antenna on the room side of the board, away from the door.

## Limits
The camera's square body is wider than the bore, so only the lens barrel enters the
tube. The lens can't get closer to the glass than the bore depth minus the barrel's
length, and sliding the tube out only moves it farther away.
