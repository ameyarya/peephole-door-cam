// Door unit: a housing for the whole XIAO ESP32S3 Sense, with a tube that
// friction-fits in the door viewer's inner bore. It hangs from the tube on its own,
// with nothing stuck to the door. Slide it in and out to find the best picture.
//
// The board goes in from the open back and snaps past two small lips, then a lid
// snaps over the back. The tube is in the middle of the housing's face. The camera
// comes off its place on the board on its flex cable into a square socket at the
// base of the tube, which holds it square and centred.
// USB-C points down, and the WiFi antenna's cable leaves through the top.
//
// Board positions come from Seeed's 3D model of the XIAO ESP32S3 Sense, in its own
// coordinates: x runs along the board (USB at +x, which is down), y runs from the
// back of the main board toward the door, z runs across the board.
// Print the housing with the open back on the bed and the lid flat side down.
// No supports.
// All dimensions in mm.

/* [Viewer - measured] */
bore_d      = 10.5;   // inner bore of the viewer
bore_depth  = 18.0;   // from the viewer's inner face to the eyepiece glass
tip_gap     = 2.0;    // tube stops this far short of the glass

/* [Tube] */
tube_od     = 10.1;   // slides freely in the bore
rib_d       = 10.6;   // four thin ribs reach just past the bore and crush to fit, so
rib_w       = 0.8;    // the tube grips without a fit test
rib_lead    = 2.0;    // ribs start this far back from the tip, to ease it in
tube_id     = 8.3;    // the lens barrel is 7.85 across
collar_h    = 1.5;    // taper from the socket's boss to the tube

/* [Camera socket] */
cam_w       = 8.0;    // the camera's square body
cam_h       = 2.1;
cam_fit     = 8.2;    // the socket, a snug push fit. Raise it if the camera won't go in
cam_d       = 2.0;    // socket depth, a little less than the body so it can't rattle
tube_off    = [0, 0]; // tube position from the middle of the housing's face, along and across.
                      // The camera follows it on its flex; move it back toward [6.9, -0.6]
                      // (the camera's place on the board) if the flex won't reach

/* [Housing] */
wall        = 1.2;    // three 0.4 mm lines
front_t     = 1.2;    // front wall, between the camera body and the tube
gap         = 0.35;   // clearance around the boards, allowing for prints coming out small
lip         = 0.6;    // how far each snap lip reaches over the main board
lip_h       = 0.8;

/* [Lid] */
lid_t       = 1.2;    // the lid's back plate
lid_gap     = 0.15;   // between the lid's side walls and the housing
skirt_h     = 3.0;    // how far the lid's side walls reach over the housing
snap        = 0.4;    // how far each snap catch sticks out

/* [Output] */
part        = "housing"; // [housing, lid]

$fn = 96;
eps = 0.01;

// ---- the board, from Seeed's 3D model ----
board_x  = [-8.97, 12.75];   // antenna end of the expansion board to the camera's far edge
board_z  = [-15.00, 2.78];   // main board, across
back_y   = -0.25;            // back face of the main board
cam_y    = 10.05;            // front face of the camera's square body
lens     = [8.75, -6.75];    // lens axis, x and z
lens_top = 13.71;
usb      = [-10.59, -1.65];  // USB-C port, across (z), on the +x edge
usb_y    = 4.21;             // the port's front face
ufl      = [-12.39, -9.29];  // antenna socket, across (z), at the -x end
sd       = [-12.52, -1.34];  // microSD card, across (z): it sticks out past the +x edge
sd_y     = 8.25;             // the card's front face
plug_w   = 13.0;             // a USB-C plug's moulding is about 12 x 7
plug_d   = 7.0;

in_x0 = board_x[0] - gap;  in_x1 = board_x[1] + gap;
in_z0 = board_z[0] - gap;  in_z1 = board_z[1] + gap;
y0    = back_y - gap - lip_h;          // the open back, on the bed
y_in  = cam_y + gap;                   // inside face of the front wall
y_out = y_in + front_t;                // outside face
tube_at = [(in_x0 + in_x1) / 2 + tube_off[0], (in_z0 + in_z1) / 2 + tube_off[1]];
boss_w = cam_fit + 2 * wall;           // square boss around the camera socket
y_tube = y_in + cam_d + front_t;       // base of the tube, on top of the boss
cam_shift = y_in - (cam_y - cam_h);    // how far the camera comes forward off the board
tube_len = bore_depth - tip_gap;       // how far the tube can go into the viewer

assert(tube_od < bore_d, "Tube is wider than the viewer's bore");
assert(rib_d - bore_d < 0.3, "Ribs are too tight to push in");
assert(tube_id > 7.85 + 0.2, "The lens barrel won't fit in the tube");
assert(cam_fit > cam_w, "The camera won't fit in its socket");
assert(cam_d < cam_h, "The socket is deeper than the camera");
assert(abs(tube_at[0] - (in_x0 + in_x1) / 2) + boss_w / 2 <= (in_x1 - in_x0) / 2 + wall + eps &&
       abs(tube_at[1] - (in_z0 + in_z1) / 2) + boss_w / 2 <= (in_z1 - in_z0) / 2 + wall + eps,
       "The boss overhangs the housing");
echo(str("Housing ", in_x1 - in_x0 + 2 * wall, " x ", in_z1 - in_z0 + 2 * wall, " x ", y_tube - y0,
         " mm, tube ", tube_od, " x ", tube_len, " mm, camera ", cam_shift, " mm forward and ",
         tube_at - lens, " across, lens ",
         lens_top + cam_shift - y_tube, " mm into the tube"));

module housing() {
    difference() {
        union() {
            // shell
            translate([in_x0 - wall, y0, in_z0 - wall])
                cube([in_x1 - in_x0 + 2 * wall, y_out - y0, in_z1 - in_z0 + 2 * wall]);
            // square boss for the camera socket, then a taper and the tube, on the lens axis
            translate([tube_at[0] - boss_w / 2, y_out - eps, tube_at[1] - boss_w / 2])
                cube([boss_w, y_tube - y_out + eps, boss_w]);
            translate([tube_at[0], y_tube - eps, tube_at[1]]) rotate([-90, 0, 0]) {
                cylinder(d1 = boss_w, d2 = tube_od, h = collar_h);
                cylinder(d = tube_od, h = collar_h + tube_len);
                for (a = [45 : 90 : 315]) rotate([0, 0, a])
                    translate([tube_od / 2 - 0.3, -rib_w / 2, collar_h])
                        cube([(rib_d - tube_od) / 2 + 0.3, rib_w, tube_len - rib_lead]);
            }
        }
        // the board's pocket, open at the back
        translate([in_x0, y0 - eps, in_z0]) cube([in_x1 - in_x0, y_in - y0 + eps, in_z1 - in_z0]);
        // the camera's square socket. Its corners stop the camera; the lens goes on through
        translate([tube_at[0] - cam_fit / 2, y_in - eps, tube_at[1] - cam_fit / 2])
            cube([cam_fit, cam_d + eps, cam_fit]);
        // the view: through the front and down the tube
        translate([tube_at[0], y_in - eps, tube_at[1]]) rotate([-90, 0, 0])
            cylinder(d = tube_id, h = y_tube - y_in + collar_h + tube_len + 3 * eps);
        // USB-C plug and microSD card, through the bottom wall, open to the back
        translate([in_x1 - eps, y0 - eps, (usb[0] + usb[1]) / 2 - plug_w / 2])
            cube([wall + 2 * eps, usb_y + plug_d / 2 - y0, plug_w]);
        translate([in_x1 - eps, y0 - eps, sd[0] - gap])
            cube([wall + 2 * eps, sd_y + gap - y0, sd[1] - sd[0] + 2 * gap]);
        // antenna cable, through the top wall, open to the back
        translate([in_x0 - wall - eps, y0 - eps, ufl[0] - 0.5])
            cube([wall + 2 * eps, 3.5 - y0, ufl[1] - ufl[0] + 1]);
    }
    // Snap lips along the two long sides. They lean in as they rise, so they print
    // without support, and their flat tops hold the back of the main board.
    for (side = [[in_z0, 1], [in_z1, -1]])
        translate([in_x0, y0, side[0]]) rotate([0, 90, 0])
            linear_extrude(in_x1 - in_x0)
                polygon([[0, 0], [0, lip_h], [-side[1] * lip, lip_h]]);
    // Catches for the lid, outside the two long sides. Sloped underneath, flat on top.
    for (side = [[in_z0 - wall, -1], [in_z1 + wall, 1]])
        translate([in_x0 - wall, y0, side[0]]) rotate([0, 90, 0])
            linear_extrude(in_x1 - in_x0 + 2 * wall)
                polygon([[0, catch_y - snap * 1.5], [0, catch_y], [-side[1] * snap, catch_y]]);
}

catch_y = 1.6;   // the catch's flat top, measured from the open back

// A lid that snaps over the back. Its two side walls reach over the housing's long
// sides and click past the catches. The ends stay open for the USB plug and the
// antenna cable. Two bars press the board against the lips.
module lid() {
    ox0 = in_x0 - wall;  ox1 = in_x1 + wall;
    oz0 = in_z0 - wall - snap - lid_gap;  oz1 = in_z1 + wall + snap + lid_gap;  // clears the catches
    // back plate
    translate([ox0, y0 - lid_t, oz0 - wall]) cube([ox1 - ox0, lid_t, oz1 - oz0 + 2 * wall]);
    for (side = [[oz0, -1], [oz1, 1]]) {
        // side wall
        translate([ox0, y0 - eps, side[1] < 0 ? oz0 - wall : oz1]) cube([ox1 - ox0, skirt_h, wall]);
        // its catch, pointing in to just short of the wall, past the housing's catch:
        // flat face toward the back, sloped toward the tip
        translate([ox0, y0, side[0]]) rotate([0, 90, 0]) linear_extrude(ox1 - ox0)
            polygon([[0, catch_y + 0.1], [side[1] * snap, catch_y + 0.1], [0, skirt_h]]);
    }
    // bars that hold the board down
    for (z = [in_z0 + 1.2, in_z1 - 2.2])
        translate([in_x0 + 2, y0 - eps, z]) cube([in_x1 - in_x0 - 4, back_y - 0.15 - y0 + eps, 1.0]);
}

// The model's y (toward the door) becomes print z, with the open back on the bed.
if (part == "housing") rotate([90, 0, 0]) translate([0, -y0, 0]) housing();
if (part == "lid")     rotate([90, 0, 0]) translate([0, -(y0 - lid_t), 0]) lid();
