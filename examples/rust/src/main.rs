use shapes::vector3::Vec3;
use shapes::shape::Color;
use shapes::circle::Circle;
use shapes::rectangle::Rectangle;
use shapes::renderer::Renderer;

fn main() {
    // Vector3 operations
    println!("=== Vector3 ===");
    let a = Vec3::new(1.0, 2.0, 3.0);
    let b = Vec3::new(4.0, 5.0, 6.0);
    let sum = a + b;
    println!("a + b = ({:.1}, {:.1}, {:.1})", sum.x, sum.y, sum.z);
    println!("dot(a, b) = {:.1}", a.dot(&b));

    let cross = a.cross(&b);
    println!("cross(a, b) = ({:.1}, {:.1}, {:.1})", cross.x, cross.y, cross.z);
    println!("length(a) = {:.4}", a.length());

    let norm = a.normalized();
    println!("normalized(a) = ({:.4}, {:.4}, {:.4})", norm.x, norm.y, norm.z);

    // Shapes and rendering
    println!();
    let mut r = Renderer::new();
    r.add(Box::new(Circle::new(Vec3::new(0.0, 0.0, 0.0), 5.0, Color::Blue)));
    r.add(Box::new(Circle::new(Vec3::new(3.0, 4.0, 0.0), 2.0, Color::Red)));
    r.add(Box::new(Rectangle::new(Vec3::new(0.0, 0.0, 0.0), 10.0, 4.0, Color::Green)));
    r.add(Box::new(Rectangle::new(Vec3::new(1.0, 1.0, 0.0), 3.0, 3.0, Color::Yellow)));

    r.render(&mut std::io::stdout());

    // Filtering
    println!("\n=== Shapes with area > 20 ===");
    let big = r.filter(|s| s.area() > 20.0);
    for s in &big {
        println!("  {} (area={:.2})", s.name(), s.area());
    }
}
