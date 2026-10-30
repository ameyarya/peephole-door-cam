// Peephole camera sleeve
// Replaces a door viewer with a clamshell tube for an OV2640/OV3660
// long-FPC camera module. Two layouts:
//   flush - camera sits inside the hole, lens flush with the door (needs ~14mm hole)
//   dome  - camera sits in a small housing on the outside face, only the
//           ribbon runs through the hole (works with 1/2" / 12.7mm holes)
//
// Parts:
//   - two clamshell halves (close around the camera + ribbon cable)
//   - a C-clip that snaps into a groove on the inside face of the door
//
// Coordinates: z = 0 is the OUTSIDE face of the door, +z points into the
// apartment. All dimensions in mm.
//
// Print in PETG/ASA for fit testing. See README.md about fire-rated doors.

/* [Door - measure these] */
hole_d      = 12.7;   // door hole diameter; measured ~13, kept at 12.7 so the tube (12.4) fits either way
door_t      = 34.0;   // door thickness (measured)
fit_gap     = 0.3;    // diametral clearance between tube and hole

/* [Layout] */
layout      = "auto"; // [auto, flush, dome]

/* [Outer flange / housing] */
flange_d    = 20.0;   // outside flange or housing diameter
flange_t    = 3.0;    // outside flange thickness (flush layout only)
chamfer     = 1.5;    // outer edge chamfer on the dome housing
window_d    = 13.0;   // optional clear acrylic disc diameter (0 = no window)
window_t    = 1.0;    // acrylic disc thickness

/* [Camera module - measure yours] */
lens_d      = 8.2;    // lens barrel diameter + clearance
lens_len    = 4.0;    // how far the lens barrel sticks out of the square holder
cam_w       = 8.6;    // square lens holder / sensor board width
cam_len     = 6.0;    // holder + sensor board depth behind the lens barrel
cam_clear   = 0.3;    // clearance around the square body

/* [Ribbon cable] */
flex_w      = 9.0;    // ribbon width where it runs through the door (+ clearance)
flex_th     = 2.0;    // channel height for the ribbon (it is ~0.3 thick)

/* [Inside retaining clip] */
clip_d      = 22.0;   // clip outer diameter
clip_t      = 2.5;    // clip thickness
groove_dep  = 0.8;    // groove depth in the tube wall
clip_open   = 0.82;   // C opening as a fraction of groove diameter (snap fit)

/* [Output] */
part        = "print"; // [print, assembled, half, clip]

$fn = 96;
eps = 0.01;

tube_d    = hole_d - fit_gap;
tube_len  = door_t + clip_t + 2.5;          // sticks out past the inside face
groove_d  = tube_d - 2 * groove_dep;
pocket_w  = cam_w + cam_clear;
win_t     = window_d > 0 ? window_t : 0;

// Thinnest wall if the camera sat inside the hole: pocket corner vs. tube surface
flush_wall = tube_d / 2 - pocket_w / 2 * sqrt(2);
dome = layout == "dome" || (layout == "auto" && flush_wall < 0.6);

// Outside part: thin flange (flush) or a housing deep enough for the camera (dome)
front_t   = dome ? win_t + lens_len + cam_len : flange_t;
lens_z0   = -front_t + win_t;               // front of lens
cam_z0    = lens_z0 + lens_len;             // start of square body
cam_z1    = cam_z0 + cam_len;               // = 0 in the dome layout

corner_wall = (dome ? flange_d : tube_d) / 2 - pocket_w / 2 * sqrt(2);
echo(str(dome ? "Dome" : "Flush", " layout. Tube OD ", tube_d,
         " mm, wall at pocket corners ", corner_wall, " mm, sticks out ",
         front_t, " mm from the door"));
assert(corner_wall >= 0.6,
       "Camera body is too wide: pocket corners break through the wall (try layout = dome)");
assert(flex_w / 2 < tube_d / 2 - 0.8, "Ribbon channel too wide for the tube");

module sleeve() {
    difference() {
        union() {
            if (dome) {
                translate([0, 0, -front_t])
                    cylinder(d1 = flange_d - 2 * chamfer, d2 = flange_d, h = chamfer);
                translate([0, 0, -front_t + chamfer]) cylinder(d = flange_d, h = front_t - chamfer);
            } else {
                translate([0, 0, -front_t]) cylinder(d = flange_d, h = front_t);
            }
            cylinder(d = tube_d, h = tube_len);
        }
        // window recess; kept shallow and wide so a 160 deg lens doesn't vignette
        if (window_d > 0)
            translate([0, 0, -front_t - eps]) cylinder(d = window_d, h = window_t + eps);
        // lens barrel
        translate([0, 0, -front_t - eps]) cylinder(d = lens_d, h = cam_z0 + front_t + eps);
        // square holder + sensor board
        translate([-pocket_w / 2, -pocket_w / 2, cam_z0]) cube([pocket_w, pocket_w, cam_len]);
        // ribbon channel, wide side across the split plane
        translate([-flex_w / 2, -flex_th / 2, cam_z1 - eps])
            cube([flex_w, flex_th, tube_len - cam_z1 + 2 * eps]);
        // clip groove right at the inside face of the door
        translate([0, 0, door_t])
            difference() {
                cylinder(d = tube_d + 1, h = clip_t + 0.3);
                translate([0, 0, -eps]) cylinder(d = groove_d, h = clip_t + 0.3 + 2 * eps);
            }
    }
}

// One clamshell half; side = 1 keeps x >= 0, side = -1 keeps x <= 0
module half(side = 1) {
    intersection() {
        sleeve();
        translate([side > 0 ? 0 : -50, -50, -front_t - 1]) cube([50, 100, tube_len + front_t + 2]);
    }
}

module clip() {
    open_w = groove_d * clip_open;
    difference() {
        cylinder(d = clip_d, h = clip_t);
        translate([0, 0, -eps]) cylinder(d = groove_d + 0.2, h = clip_t + 2 * eps);
        // C opening, pushes on sideways over the groove
        translate([0, -open_w / 2, -eps]) cube([clip_d, open_w, clip_t + 2 * eps]);
    }
}

// Lay each half flat on its split face
module half_flat(side) {
    if (side > 0) rotate([0, -90, 0]) half(1);
    else          rotate([0, 90, 0]) half(-1);
}

if (part == "print") {
    translate([0, -flange_d * 0.75, 0]) half_flat(1);
    translate([0,  flange_d * 0.75, 0]) half_flat(-1);
    translate([-clip_d, 0, 0]) clip();
} else if (part == "assembled") {
    color("silver") sleeve();
    color("orange") translate([0, 0, door_t]) clip();
    // ghost of the door
    %translate([0, 0, door_t / 2]) difference() {
        cube([60, 60, door_t], center = true);
        cylinder(d = hole_d, h = door_t + 1, center = true);
    }
} else if (part == "half") {
    half_flat(1);
} else if (part == "clip") {
    clip();
}
