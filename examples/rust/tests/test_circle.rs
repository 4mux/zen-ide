extern crate shapes;

use shapes::circle::Circle;
use shapes::shape::{Color, Shape};
use shapes::vector3::Vec3;
use std::f64::consts::PI;

const EPS: f64 = 1e-10;

#[test]
fn has_name_and_color() {
    let c = Circle::new(Vec3::new(0.0, 0.0, 0.0), 1.0, Color::Blue);
    assert_eq!(c.name(), "Circle");
    assert_eq!(c.color(), Color::Blue);
}

#[test]
fn computes_area() {
    let c = Circle::new(Vec3::new(0.0, 0.0, 0.0), 5.0, Color::Red);
    assert!((c.area() - PI * 25.0).abs() < EPS);
}

#[test]
fn computes_perimeter() {
    let c = Circle::new(Vec3::new(0.0, 0.0, 0.0), 3.0, Color::Red);
    assert!((c.perimeter() - 2.0 * PI * 3.0).abs() < EPS);
}

#[test]
fn returns_center_as_centroid() {
    let c = Circle::new(Vec3::new(3.0, 4.0, 5.0), 2.0, Color::Green);
    let cen = c.centroid();
    assert!((cen.x - 3.0).abs() < EPS);
    assert!((cen.y - 4.0).abs() < EPS);
    assert!((cen.z - 5.0).abs() < EPS);
}

#[test]
fn stores_radius() {
    let c = Circle::new(Vec3::new(0.0, 0.0, 0.0), 7.5, Color::White);
    assert!((c.radius() - 7.5).abs() < EPS);
}
