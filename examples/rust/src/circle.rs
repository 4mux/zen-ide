use crate::shape::{Color, Shape};
use crate::vector3::Vec3;
use std::f64::consts::PI;

pub struct Circle {
    center: Vec3,
    radius: f64,
    color: Color,
}

impl Circle {
    pub fn new(center: Vec3, radius: f64, color: Color) -> Self {
        Self { center, radius, color }
    }

    pub fn radius(&self) -> f64 {
        self.radius
    }
}

impl Shape for Circle {
    fn name(&self) -> &str { "Circle" }
    fn color(&self) -> Color { self.color }

    fn area(&self) -> f64 {
        PI * self.radius * self.radius
    }

    fn perimeter(&self) -> f64 {
        2.0 * PI * self.radius
    }

    fn centroid(&self) -> Vec3 {
        self.center
    }
}
