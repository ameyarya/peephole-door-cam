// Sliding camera mount for filming through an existing door viewer.
// A tube friction-fits in the viewer's inner bore, and a cup on its end grips the
// XIAO's square camera module. Slide the tube in and out to find the best picture,
// and rotate it to level the image. Nothing is changed on the door.
//
// Print with the tube end on the bed. No supports: a 45 degree cone joins the tube
// to the cup. Coordinates: z = 0 is the tube's tip, +z runs toward the camera.
// All dimensions in mm.

/* [Viewer - measured] */
bore_d      = 10.5;   // inner bore of the viewer
bore_depth  = 18.0;   // from the viewer's inner face to the eyepiece glass
tip_gap     = 2.0;    // tube stops this far short of the glass

/* [Tube] */
tube_od     = 10.3;   // use the size that worked from the fit test
wall        = 1.0;    // tube wall

/* [Camera module - estimated from a photo, MEASURE] */
cam_w       = 10.4;   // square module width, with clearance
cup_depth   = 3.0;    // how far the cup grips the module
cup_wall    = 1.4;
floor_t     = 1.2;    // between the module and the lens opening
flex_notch  = 8.0;    // gap in the wall on the ribbon cable's side (0 = none)

/* [Output] */
part        = "mount"; // [mount, fit_test]

$fn = 96;
eps = 0.01;

tube_id  = tube_od - 2 * wall;
tube_len = bore_depth - tip_gap;
cup_w    = cam_w + 2 * cup_wall;
cone_h   = (cup_w - tube_od) / 2;   // 45 degrees, from the tube out to the cup's width

assert(tube_od < bore_d, "Tube is wider than the viewer's bore");
assert(tube_id > 6, "Tube bore is too small to see through");
echo(str("Tube ", tube_od, " x ", tube_len, " mm, opening ", tube_id, " mm, cup ", cup_w, " mm"));

module mount() {
    difference() {
        union() {
            cylinder(d = tube_od, h = tube_len);
            hull() {
                translate([0, 0, tube_len - eps]) cylinder(d = tube_od, h = eps);
                translate([-cup_w / 2, -cup_w / 2, tube_len + cone_h]) cube([cup_w, cup_w, eps]);
            }
            translate([-cup_w / 2, -cup_w / 2, tube_len + cone_h])
                cube([cup_w, cup_w, floor_t + cup_depth]);
        }
        // the view through the middle
        translate([0, 0, -eps]) cylinder(d = tube_id, h = tube_len + cone_h + floor_t + 2 * eps);
        // the camera module's pocket
        translate([-cam_w / 2, -cam_w / 2, tube_len + cone_h + floor_t])
            cube([cam_w, cam_w, cup_depth + eps]);
        // room for the ribbon cable
        if (flex_notch > 0)
            translate([cam_w / 2 - eps, -flex_notch / 2, tube_len + cone_h + floor_t])
                cube([cup_wall + 2 * eps, flex_notch, cup_depth + eps]);
    }
}

// Three short rings to find the tightest size that still slides.
module fit_test() {
    ods = [tube_od - 0.1, tube_od, tube_od + 0.1];
    for (i = [0 : 2])
        translate([i * 16, 0, 0]) difference() {
            union() {
                cylinder(d = ods[i], h = 8);
                translate([0, 0, 8]) cylinder(d = 14, h = 1 + i);   // ring height shows the size: 1, 2 or 3 mm
            }
            translate([0, 0, -eps]) cylinder(d = tube_id, h = 12 + 2 * eps);
        }
}

if (part == "mount") mount();
else if (part == "fit_test") fit_test();
