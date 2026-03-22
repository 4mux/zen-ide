extern crate shapes;

use shapes::vector3::Vec3;

const EPS: f64 = 1e-10;

#[test]
fn creates_with_values() {
    let v = Vec3::new(1.0, 2.0, 3.0);
    assert!((v.x - 1.0).abs() < EPS);
    assert!((v.y - 2.0).abs() < EPS);
    assert!((v.z - 3.0).abs() < EPS);
}

#[test]
fn computes_length() {
    let v = Vec3::new(3.0, 4.0, 0.0);
    assert!((v.length() - 5.0).abs() < EPS);
}

#[test]
fn normalizes() {
    let n = Vec3::new(0.0, 0.0, 5.0).normalized();
    assert!((n.x - 0.0).abs() < EPS);
    assert!((n.y - 0.0).abs() < EPS);
    assert!((n.z - 1.0).abs() < EPS);
}

#[test]
fn adds() {
    let r = Vec3::new(1.0, 2.0, 3.0) + Vec3::new(4.0, 5.0, 6.0);
    assert!((r.x - 5.0).abs() < EPS);
    assert!((r.y - 7.0).abs() < EPS);
    assert!((r.z - 9.0).abs() < EPS);
}

#[test]
fn subtracts() {
    let r = Vec3::new(5.0, 7.0, 9.0) - Vec3::new(1.0, 2.0, 3.0);
    assert!((r.x - 4.0).abs() < EPS);
    assert!((r.y - 5.0).abs() < EPS);
    assert!((r.z - 6.0).abs() < EPS);
}

#[test]
fn scales() {
    let r = Vec3::new(1.0, 2.0, 3.0) * 2.0;
    assert!((r.x - 2.0).abs() < EPS);
    assert!((r.y - 4.0).abs() < EPS);
    assert!((r.z - 6.0).abs() < EPS);
}

#[test]
fn computes_dot_product() {
    let a = Vec3::new(1.0, 2.0, 3.0);
    let b = Vec3::new(4.0, 5.0, 6.0);
    assert!((a.dot(&b) - 32.0).abs() < EPS);
}

#[test]
fn computes_cross_product() {
    let c = Vec3::new(1.0, 0.0, 0.0).cross(&Vec3::new(0.0, 1.0, 0.0));
    assert!((c.x - 0.0).abs() < EPS);
    assert!((c.y - 0.0).abs() < EPS);
    assert!((c.z - 1.0).abs() < EPS);
}

#[test]
fn checks_equality() {
    let a = Vec3::new(1.0, 2.0, 3.0);
    assert_eq!(a, Vec3::new(1.0, 2.0, 3.0));
    assert_ne!(a, Vec3::new(0.0, 0.0, 0.0));
}
