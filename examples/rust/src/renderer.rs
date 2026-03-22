use crate::shape::Shape;
use std::io::Write;

pub struct Renderer {
    shapes: Vec<Box<dyn Shape>>,
}

impl Renderer {
    pub fn new() -> Self {
        Self { shapes: Vec::new() }
    }

    pub fn add(&mut self, shape: Box<dyn Shape>) {
        self.shapes.push(shape);
    }

    pub fn render(&self, out: &mut dyn Write) {
        writeln!(out, "=== Rendering {} shape(s) ===", self.shapes.len()).unwrap();
        for s in &self.shapes {
            writeln!(out, "{}\n", s.describe()).unwrap();
        }
        writeln!(out, "Total area: {:.2}", self.total_area()).unwrap();
    }

    pub fn total_area(&self) -> f64 {
        self.shapes.iter().map(|s| s.area()).sum()
    }

    pub fn count(&self) -> usize {
        self.shapes.len()
    }

    pub fn filter<F: Fn(&dyn Shape) -> bool>(&self, pred: F) -> Vec<&dyn Shape> {
        self.shapes.iter()
            .map(|s| s.as_ref())
            .filter(|s| pred(*s))
            .collect()
    }
}

impl Default for Renderer {
    fn default() -> Self {
        Self::new()
    }
}
