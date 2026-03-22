extern crate shapes;

use shapes::rectangle::Rectangle;
use shapes::shape::{Color, Shape};
use shapes::vector3::Vec3;

const EPS: f64 = 1e-10;

#[test]
fn has_name_and_color() {
    let r = Rectangle::new(Vec3::new(0.0, 0.0, 0.0), 4.0, 5.0, Color::Green);
    assert_eq!(r.name(), "Rectangle");
    assert_eq!(r.color(), Color::Green);
}

#[test]
fn stores_width_and_height() {
    let r = Rectangle::new(Vec3::new(0.0, 0.0, 0.0), 10.0, 3.0, Color::Red);
    assert!((r.width() - 10.0).abs() < EPS);
    assert!((r.height() - 3.0).abs() < EPS);
}

#[test]
fn computes_area() {
    let r = Rectangle::new(Vec3::new(0.0, 0.0, 0.0), 6.0, 4.0, Color::Red);
    assert!((r.area() - 24.0).abs() < EPS);
}

#[test]
fn computes_perimeter() {
    let r = Rectangle::new(Vec3::new(0.0, 0.0, 0.0), 6.0, 4.0, Color::Red);
    assert!((r.perimeter() - 20.0).abs() < EPS);
}

#[test]
fn computes_centroid_from_origin() {
    let r = Rectangle::new(Vec3::new(2.0, 3.0, 0.0), 10.0, 4.0, Color::Blue);
    let c = r.centroid();
    assert!((c.x - 7.0).abs() < EPS);
    assert!((c.y - 5.0).abs() < EPS);
    assert!((c.z - 0.0).abs() < EPS);
}

#[test]
fn computes_centroid_at_zero_origin() {
    let r = Rectangle::new(Vec3::new(0.0, 0.0, 0.0), 8.0, 6.0, Color::Yellow);
    let c = r.centroid();
    assert!((c.x - 4.0).abs() < EPS);
    assert!((c.y - 3.0).abs() < EPS);
}
