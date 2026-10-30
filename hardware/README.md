# Peephole camera sleeve

Replaces the door viewer with a sleeve for a long-FPC OV2640/OV3660 camera.
The XIAO ESP32S3 Sense stays inside the apartment.

## Layouts
- **dome** (current default): the camera sits in a 20mm round housing on the
  outside face of the door, sticking out ~11mm. Only the ribbon goes through
  the hole. Used automatically when the hole is too small for the camera.
- **flush**: the camera sits inside the hole with the lens flush with the door.
  Needs a ~14mm (9/16") hole.

This door's viewer barrel is 12.0mm, so the hole is most likely 1/2" (12.7mm).
That is too small for an 8.5mm square camera module to sit inside, so
`layout = "auto"` picks **dome**.

## Files
- `peephole-sleeve/peephole_sleeve.scad`: parametric model (open in OpenSCAD, Customizer panel)
- `peephole-sleeve/stl/sleeve_half.stl`: one clamshell half. **Print it twice** (the halves are identical)
- `peephole-sleeve/stl/clip.stl`: C-clip that locks the sleeve from the inside

The STLs use values for this door: 34mm thick, ~13mm hole (modelled as 12.7mm). Regenerate after
measuring the camera module.

## Measure first
| Parameter | What to measure |
|---|---|
| `hole_d` | The hole itself (calipers' inside jaws). Barrel OD was 12.0mm |
| `door_t` | Door thickness at its edge. This sets where the clip groove is |
| `lens_d`, `lens_len` | Camera lens barrel diameter, and how far it sticks out of the square holder |
| `cam_w`, `cam_len` | Square lens holder width and depth (holder + sensor board) |
| `flex_w` | Ribbon width where it passes through the door (not the wide connector end) |

## Assembly (dome layout)
1. Unscrew the old viewer and store it for move-out.
2. From the inside, pass the camera module **out** through the hole, corner
   first (an 8.5mm square is 12.0mm across the diagonal, so this needs a hole
   of at least ~12.3mm). The wide connector end stays inside.
3. Outside, lay the camera into one half (lens into the round bore, ribbon
   down the channel), close the other half over it. A drop of CA glue on the
   housing holds the halves.
4. Optional: drop a 13mm × 1mm clear acrylic disc into the front recess.
5. Push the sleeve into the hole, rotate so the image is upright.
6. Inside, snap the C-clip into the groove against the door.
7. Plug the ribbon into the XIAO (use a 24-pin 0.5mm FPC extension if needed).

## Print settings
PETG or ASA, 0.4mm nozzle, 0.12–0.16mm layers, 3+ walls, 100% infill for the
sleeve. Print the halves flat on the split face (already oriented). No supports.

## Fire-rated door
The original viewer is UL-listed for a 20-minute fire door. A plastic sleeve
melts and leaves an open hole, so this is for **fit testing and prototyping**.
For permanent use, get the landlord's OK and make the final sleeve from metal,
or reinstall the original viewer.

# Inside enclosure

`enclosure/enclosure.scad` → `enclosure/stl/enclosure_body.stl` + `enclosure/stl/enclosure_lid.stl`. Outside size
30 × 55 × 19mm.

- The back has a 24mm hole that drops over the sleeve's clip, so the box
  centres itself on the peephole (peephole centre is 40mm above the box's
  bottom edge).
- The XIAO sits on rails in the lower half, USB-C pointing down through the
  bottom wall, so the cable runs straight down the door toward the hinge.
- The camera ribbon comes out of the sleeve and curls down into the board's
  camera connector. There's a 4mm gap between the clip recess and the board.
- Lid: friction lip plus two M2 × 6mm self-tapping screws. 4 × 4 mic holes sit
  over the board. Stick the WiFi antenna to the inside of the lid, the part
  farthest from the door (important if the door is steel).
- Side vents next to the ribbon space. The ESP32-S3 gets warm when streaming.

## Check against the real board
| Parameter | Default | What to check |
|---|---|---|
| `usb_z` | 7mm | USB-C centre height above the box floor, with the board on the rails |
| `rail_h` | 4mm | Enough clearance for the parts on the underside of the stack |
| Stack height | ≤ 9mm | Rails top out at 6mm, lid lip starts at 15mm |

## Mounting
Command strips on the back, below the hole (about 30 × 26mm free). Cut the
strips to fit if needed. Press the box over the clip first, then press the
strips on.
