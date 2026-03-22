use crate::vector3::Vec3;
use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Color {
    Red,
    Green,
    Blue,
    Yellow,
    White,
}

impl fmt::Display for Color {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Color::Red    => write!(f, "Red"),
            Color::Green  => write!(f, "Green"),
            Color::Blue   => write!(f, "Blue"),
            Color::Yellow => write!(f, "Yellow"),
            Color::White  => write!(f, "White"),
        }
    }
}

pub trait Shape {
    fn name(&self) -> &str;
    fn color(&self) -> Color;
    fn area(&self) -> f64;
    fn perimeter(&self) -> f64;
    fn centroid(&self) -> Vec3;

    fn describe(&self) -> String {
        let c = self.centroid();
        format!(
            "[{}] {}\n  area:      {:.2}\n  perimeter: {:.2}\n  centroid:  ({:.2}, {:.2}, {:.2})",
            self.name(), self.color(),
            self.area(), self.perimeter(),
            c.x, c.y, c.z,
        )
    }
}
