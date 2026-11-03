// Door unit: a housing for the whole XIAO ESP32S3 Sense, with a tube that
// friction-fits in the door viewer's inner bore. It hangs from the tube on its own,
// with nothing stuck to the door. Slide it in and out to find the best picture.
//
// The board goes in from the open back and snaps past two small lips. The camera's
// lens barrel sits in the tube's opening, which centres it.
// USB-C points down, and the WiFi antenna's cable leaves through the top.
//
// Board positions come from Seeed's 3D model of the XIAO ESP32S3 Sense, in its own
// coordinates: x runs along the board (USB at +x, which is down), y runs from the
// back of the main board toward the door, z runs across the board.
// Print with the open back on the bed. No supports: the front bridges across.
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
collar_d    = 11.0;   // stiffens the joint between tube and housing
collar_h    = 1.5;

/* [Housing] */
wall        = 1.2;    // three 0.4 mm lines
front_t     = 1.2;    // front wall, between the camera body and the tube
gap         = 0.35;   // clearance around the boards, allowing for prints coming out small
lip         = 0.6;    // how far each snap lip reaches over the main board
lip_h       = 0.8;

/* [Output] */
part        = "housing"; // [housing]

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
tube_len = bore_depth - tip_gap;       // how far the tube can go into the viewer

assert(tube_od < bore_d, "Tube is wider than the viewer's bore");
assert(rib_d - bore_d < 0.3, "Ribs are too tight to push in");
assert(tube_id > 7.85 + 0.2, "The lens barrel won't fit in the tube");
assert(lens[0] + collar_d / 2 <= in_x1 + wall + eps, "Collar overhangs the housing");
echo(str("Housing ", in_x1 - in_x0 + 2 * wall, " x ", in_z1 - in_z0 + 2 * wall, " x ", y_out - y0,
         " mm, tube ", tube_od, " x ", tube_len, " mm, lens ", lens_top - y_out, " mm into the tube"));

module housing() {
    difference() {
        union() {
            // shell
            translate([in_x0 - wall, y0, in_z0 - wall])
                cube([in_x1 - in_x0 + 2 * wall, y_out - y0, in_z1 - in_z0 + 2 * wall]);
            // collar and tube, on the lens axis
            translate([lens[0], y_out - eps, lens[1]]) rotate([-90, 0, 0]) {
                cylinder(d1 = collar_d, d2 = tube_od, h = collar_h);
                cylinder(d = tube_od, h = collar_h + tube_len);
                for (a = [45 : 90 : 315]) rotate([0, 0, a])
                    translate([tube_od / 2 - 0.3, -rib_w / 2, collar_h])
                        cube([(rib_d - tube_od) / 2 + 0.3, rib_w, tube_len - rib_lead]);
            }
        }
        // the board's pocket, open at the back
        translate([in_x0, y0 - eps, in_z0]) cube([in_x1 - in_x0, y_in - y0 + eps, in_z1 - in_z0]);
        // the view: through the front and down the tube
        translate([lens[0], y_in - eps, lens[1]]) rotate([-90, 0, 0])
            cylinder(d = tube_id, h = front_t + collar_h + tube_len + 3 * eps);
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
}

// The model's y (toward the door) becomes print z, with the open back on the bed.
if (part == "housing") rotate([90, 0, 0]) translate([0, -y0, 0]) housing();
