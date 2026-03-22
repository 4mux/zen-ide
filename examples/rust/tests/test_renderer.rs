extern crate shapes;

use shapes::circle::Circle;
use shapes::rectangle::Rectangle;
use shapes::renderer::Renderer;
use shapes::shape::{Color, Shape};
use shapes::vector3::Vec3;
use std::f64::consts::PI;

fn make_circle(r: f64) -> Box<dyn Shape> {
    Box::new(Circle::new(Vec3::new(0.0, 0.0, 0.0), r, Color::Blue))
}

fn make_rect(w: f64, h: f64) -> Box<dyn Shape> {
    Box::new(Rectangle::new(Vec3::new(0.0, 0.0, 0.0), w, h, Color::Green))
}

#[test]
fn starts_empty() {
    let r = Renderer::new();
    assert_eq!(r.count(), 0);
    assert!((r.total_area() - 0.0).abs() < 1e-10);
}

#[test]
fn counts_shapes() {
    let mut r = Renderer::new();
    r.add(make_circle(1.0));
    r.add(make_rect(2.0, 3.0));
    assert_eq!(r.count(), 2);
}

#[test]
fn computes_total_area() {
    let mut r = Renderer::new();
    r.add(make_circle(1.0));
    r.add(make_rect(2.0, 3.0));
    let expected = PI * 1.0 + 6.0;
    assert!((r.total_area() - expected).abs() < 1e-10);
}

#[test]
fn filters_by_color() {
    let mut r = Renderer::new();
    r.add(make_circle(1.0));   // Blue
    r.add(make_rect(2.0, 3.0)); // Green
    r.add(make_circle(2.0));   // Blue
    let blues = r.filter(|s| s.color() == Color::Blue);
    assert_eq!(blues.len(), 2);
}

#[test]
fn filters_by_area() {
    let mut r = Renderer::new();
    r.add(make_rect(3.0, 3.0));   // 9
    r.add(make_rect(10.0, 5.0));  // 50
    r.add(make_circle(1.0));      // ~3.14
    let big = r.filter(|s| s.area() > 20.0);
    assert_eq!(big.len(), 1);
}

#[test]
fn renders_to_writer() {
    let mut r = Renderer::new();
    r.add(make_circle(1.0));
    let mut buf = Vec::new();
    r.render(&mut buf);
    let output = String::from_utf8(buf).unwrap();
    assert!(output.contains("Rendering 1 shape(s)"));
    assert!(output.contains("Circle"));
}
