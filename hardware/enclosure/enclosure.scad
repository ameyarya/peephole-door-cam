// Inside enclosure for the XIAO ESP32S3 Sense
// Sticks to the inside face of the door with Command strips, directly over
// the peephole sleeve. The back has a hole that drops over the sleeve's clip,
// so the box self-centres on the peephole.
//
// Layout (looking at the door from inside):
//   top    - opening for the sleeve end + clip, ribbon curls into the box
//   bottom - XIAO on rails, USB-C pointing down, cable exits the bottom wall
//   lid    - mic holes over the board, stick the WiFi antenna to its inside
//
// Coordinates: z = 0 is the door surface, +z points into the room,
// +y is up. All dimensions in mm.

/* [Box] */
wall        = 2.0;
inner_w     = 26.0;   // inside width
inner_h     = 51.0;   // inside height
inner_d     = 15.0;   // inside depth (door to lid)
corner_r    = 3.0;    // outside corner radius

/* [Peephole sleeve (from peephole_sleeve.scad)] */
recess_d    = 24.0;   // hole for the clip (clip is 22)
recess_gap  = 1.0;    // space between the recess and the top inside wall

/* [XIAO ESP32S3 Sense] */
board_w     = 17.8;   // XIAO width
board_l     = 21.0;   // XIAO length
board_gap   = 0.4;    // clearance around the board
rail_h      = 4.0;    // rail height, clears parts on the underside of the stack
usb_z       = 7.0;    // USB-C centre height above the inside floor - CHECK
usb_w       = 12.0;   // opening for the plug's overmould
usb_h       = 7.0;

/* [Lid] */
lid_t       = 2.0;
lip_depth   = 2.0;
lip_t       = 1.2;
lip_gap     = 0.2;    // clearance between the lip and the inside wall
screw_d     = 2.4;    // M2 clearance in the lid
pilot_d     = 1.6;    // M2 self-tapping pilot in the bosses
boss_d      = 5.0;
mic_holes   = 4;      // grid size over the board centre (0 = none)
mic_hole_d  = 1.2;
mic_pitch   = 2.5;

/* [Output] */
part        = "print"; // [print, body, lid, assembled]

$fn = 64;
eps = 0.01;

outer_w   = inner_w + 2 * wall;
outer_h   = inner_h + 2 * wall;
body_d    = wall + inner_d;
tube_y    = wall + inner_h - recess_gap - recess_d / 2;  // peephole centre
board_y0  = wall + 1;                                    // USB end of the board
board_cy  = board_y0 + board_l / 2;
boss_x    = inner_w / 2 - boss_d / 2 + 0.5;  // sunk into the walls, not tangent
boss_y    = wall + inner_h - boss_d / 2 + 0.5;

assert(recess_d < inner_w, "Clip recess is wider than the box");
assert(tube_y - recess_d / 2 > board_y0 + board_l + 2,
       "No room between the board and the peephole for the ribbon to bend");
assert(norm([boss_x, boss_y - tube_y]) > recess_d / 2 + boss_d / 2,
       "Screw bosses hit the clip recess");
echo(str("Enclosure ", outer_w, " x ", outer_h, " x ", body_d + lid_t,
         " mm, peephole centre ", tube_y, " mm above the bottom edge"));

// Rounded box: x centred, y from 0, z from 0
module rbox(w, h, d, r) {
    hull()
        for (x = [-w / 2 + r, w / 2 - r], y = [r, h - r])
            translate([x, y, 0]) cylinder(r = r, h = d);
}

module body() {
    difference() {
        union() {
            difference() {
                rbox(outer_w, outer_h, body_d, corner_r);
                translate([0, wall, wall])
                    rbox(inner_w, inner_h, body_d, corner_r - wall);
            }
            // screw bosses, top corners beside the recess
            for (sx = [-1, 1])
                translate([sx * boss_x, boss_y, 0]) cylinder(d = boss_d, h = body_d);
            // board rails and side guides
            for (sx = [-1, 1]) {
                translate([sx * (board_w / 2 - 1.5) - 1, board_y0, 0])
                    cube([2, board_l, wall + rail_h]);
                translate([sx * (board_w / 2 + board_gap + 0.75) - 0.75, board_y0, 0])
                    cube([1.5, board_l, wall + rail_h + 2]);
            }
        }
        // drops over the sleeve end and clip
        translate([0, tube_y, -eps]) cylinder(d = recess_d, h = wall + 2 * eps);
        // pilot holes
        for (sx = [-1, 1])
            translate([sx * boss_x, boss_y, wall]) cylinder(d = pilot_d, h = body_d);
        // USB-C through the bottom wall
        translate([-usb_w / 2, -eps, wall + usb_z - usb_h / 2])
            cube([usb_w, wall + 2 * eps, usb_h]);
        // vent slots in the side walls, beside the ribbon space
        for (sx = [-1, 1], i = [0 : 2])
            translate([sx * (outer_w / 2) - wall, tube_y - 8 + i * 4, wall + 4])
                cube([2 * wall, 1.6, inner_d - 7]);
    }
}

module lid() {
    difference() {
        union() {
            rbox(outer_w, outer_h, lid_t, corner_r);
            // friction lip that sits inside the walls
            translate([0, wall + lip_gap, lid_t - eps])
                difference() {
                    rbox(inner_w - 2 * lip_gap, inner_h - 2 * lip_gap, lip_depth, corner_r - wall);
                    translate([0, lip_t, -eps])
                        rbox(inner_w - 2 * (lip_gap + lip_t), inner_h - 2 * (lip_gap + lip_t),
                             lip_depth + 2 * eps, max(corner_r - wall - lip_t, 0.5));
                }
        }
        // clear the bosses
        for (sx = [-1, 1])
            translate([sx * boss_x, boss_y, lid_t - eps]) cylinder(d = boss_d + 0.6, h = lip_depth + 1);
        // screw holes
        for (sx = [-1, 1])
            translate([sx * boss_x, boss_y, -eps]) cylinder(d = screw_d, h = lid_t + 2 * eps);
        // mic holes over the board
        if (mic_holes > 0)
            for (i = [0 : mic_holes - 1], j = [0 : mic_holes - 1])
                translate([(i - (mic_holes - 1) / 2) * mic_pitch,
                           board_cy + (j - (mic_holes - 1) / 2) * mic_pitch, -eps])
                    cylinder(d = mic_hole_d, h = lid_t + 2 * eps);
    }
}

if (part == "print") {
    body();
    translate([outer_w + 5, 0, 0]) lid();
} else if (part == "body") {
    body();
} else if (part == "lid") {
    lid();
} else if (part == "assembled") {
    body();
    // lid flipped onto the open face
    color("orange") translate([0, 0, body_d + lid_t]) mirror([0, 0, 1]) lid();
    // ghost of the XIAO
    %translate([-board_w / 2, board_y0, wall + rail_h]) cube([board_w, board_l, 8]);
    // ghost of the sleeve end + clip
    %translate([0, tube_y, 0]) { cylinder(d = 22, h = 2.5); cylinder(d = 12.4, h = 5); }
}
