import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { Color, Shape, colorName, getRegisteredShapes, registerShape } from "../src/shape.js";

class ConcreteShape extends Shape {
  constructor(color) { super("Concrete", color); }
  area()      { return 10; }
  perimeter() { return 20; }
  centroid()  { return null; }
}

describe("Color", () => {
  it("each value is a unique Symbol", () => {
    const values = Object.values(Color);
    const unique = new Set(values);
    assert.equal(unique.size, values.length);
  });
});

describe("colorName", () => {
  it("returns the key name for a known color", () => {
    assert.equal(colorName(Color.RED),    "RED");
    assert.equal(colorName(Color.BLUE),   "BLUE");
    assert.equal(colorName(Color.GREEN),  "GREEN");
    assert.equal(colorName(Color.YELLOW), "YELLOW");
    assert.equal(colorName(Color.WHITE),  "WHITE");
  });

  it("returns UNKNOWN for an unrecognised symbol", () => {
    assert.equal(colorName(Symbol("X")), "UNKNOWN");
  });
});

describe("Shape (abstract)", () => {
  it("cannot be instantiated directly", () => {
    assert.throws(() => new Shape("X", Color.RED), TypeError);
  });

  it("exposes name and color via getters", () => {
    const s = new ConcreteShape(Color.YELLOW);
    assert.equal(s.name,  "Concrete");
    assert.equal(s.color, Color.YELLOW);
  });

  it("describe() includes name, color, area, and perimeter", () => {
    const s = new ConcreteShape(Color.RED);
    const d = s.describe();
    assert.ok(d.includes("Concrete"));
    assert.ok(d.includes("RED"));
    assert.ok(d.includes("10.0000"));
    assert.ok(d.includes("20.0000"));
  });

  it("toString() includes class name and color", () => {
    const s = new ConcreteShape(Color.BLUE);
    assert.ok(s.toString().includes("ConcreteShape"));
    assert.ok(s.toString().includes("BLUE"));
  });
});

describe("registerShape / getRegisteredShapes", () => {
  it("registered class appears in registry", () => {
    class TestShape extends Shape {
      constructor() { super("Test", Color.WHITE); }
      area()      { return 0; }
      perimeter() { return 0; }
      centroid()  { return null; }
    }
    registerShape(TestShape);
    const reg = getRegisteredShapes();
    assert.ok(reg.has("TestShape"));
  });

  it("returns a defensive copy", () => {
    const a = getRegisteredShapes();
    const b = getRegisteredShapes();
    assert.notEqual(a, b);
  });
});
