use crate::shape::{Color, Shape};
use crate::vector3::Vec3;

pub struct Rectangle {
    origin: Vec3,
    width: f64,
    height: f64,
    color: Color,
}

impl Rectangle {
    pub fn new(origin: Vec3, width: f64, height: f64, color: Color) -> Self {
        Self { origin, width, height, color }
    }

    pub fn width(&self) -> f64 {
        self.width
    }

    pub fn height(&self) -> f64 {
        self.height
    }
}

impl Shape for Rectangle {
    fn name(&self) -> &str { "Rectangle" }
    fn color(&self) -> Color { self.color }

    fn area(&self) -> f64 {
        self.width * self.height
    }

    fn perimeter(&self) -> f64 {
        2.0 * (self.width + self.height)
    }

    fn centroid(&self) -> Vec3 {
        Vec3::new(
            self.origin.x + self.width / 2.0,
            self.origin.y + self.height / 2.0,
            self.origin.z,
        )
    }
}
