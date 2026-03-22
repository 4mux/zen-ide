extern crate shapes;

use shapes::shape::Color;

#[test]
fn color_display_red()    { assert_eq!(format!("{}", Color::Red),    "Red"); }
#[test]
fn color_display_green()  { assert_eq!(format!("{}", Color::Green),  "Green"); }
#[test]
fn color_display_blue()   { assert_eq!(format!("{}", Color::Blue),   "Blue"); }
#[test]
fn color_display_yellow() { assert_eq!(format!("{}", Color::Yellow), "Yellow"); }
#[test]
fn color_display_white()  { assert_eq!(format!("{}", Color::White),  "White"); }

mod dummy {
    use shapes::shape::{Color, Shape};
    use shapes::vector3::Vec3;

    pub struct DummyShape {
        pub name: String,
        pub color: Color,
    }

    impl Shape for DummyShape {
        fn name(&self) -> &str { &self.name }
        fn color(&self) -> Color { self.color }
        fn area(&self) -> f64 { 42.0 }
        fn perimeter(&self) -> f64 { 10.0 }
        fn centroid(&self) -> Vec3 { Vec3::new(1.0, 2.0, 3.0) }
    }
}

use dummy::DummyShape;
use shapes::shape::Shape;

#[test]
fn dispatches_area() {
    let s = DummyShape { name: "Test".into(), color: Color::Red };
    assert!((s.area() - 42.0).abs() < 1e-10);
}

#[test]
fn dispatches_perimeter() {
    let s = DummyShape { name: "Test".into(), color: Color::Red };
    assert!((s.perimeter() - 10.0).abs() < 1e-10);
}

#[test]
fn dispatches_centroid() {
    let s = DummyShape { name: "Test".into(), color: Color::Red };
    let c = s.centroid();
    assert!((c.x - 1.0).abs() < 1e-10);
    assert!((c.y - 2.0).abs() < 1e-10);
    assert!((c.z - 3.0).abs() < 1e-10);
}

#[test]
fn describe_contains_name_and_color() {
    let s = DummyShape { name: "TestShape".into(), color: Color::Yellow };
    let desc = s.describe();
    assert!(desc.contains("TestShape"));
    assert!(desc.contains("Yellow"));
}
