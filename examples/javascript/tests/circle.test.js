import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { Circle } from "../src/circle.js";
import { Color }  from "../src/shape.js";
import { Vector3 } from "../src/vector3.js";

describe("Circle", () => {
  describe("defaults", () => {
    it("uses BLUE as default color", () => {
      const c = new Circle();
      assert.equal(c.color, Color.BLUE);
    });

    it("defaults center to (0,0,0) and radius to 1", () => {
      const c = new Circle();
      assert.equal(c.radius, 1);
      assert.equal(c.center.toString(), "(0, 0, 0)");
    });
  });

  describe("area", () => {
    it("returns π·r²", () => {
      const c = new Circle(new Vector3(), 5);
      assert.ok(Math.abs(c.area() - Math.PI * 25) < 1e-10);
    });
  });

  describe("perimeter", () => {
    it("returns 2·π·r", () => {
      const c = new Circle(new Vector3(), 3);
      assert.ok(Math.abs(c.perimeter() - 2 * Math.PI * 3) < 1e-10);
    });
  });

  describe("centroid", () => {
    it("equals the center", () => {
      const center = new Vector3(1, 2, 0);
      const c = new Circle(center, 4);
      assert.equal(c.centroid(), center);
    });
  });

  describe("describe", () => {
    it("includes radius and center", () => {
      const c = new Circle(new Vector3(1, 2, 0), 5, Color.RED);
      const d = c.describe();
      assert.ok(d.includes("radius=5"));
      assert.ok(d.includes("(1, 2, 0)"));
      assert.ok(d.includes("RED"));
    });
  });

  describe("getters", () => {
    it("exposes radius and center", () => {
      const center = new Vector3(3, 4, 0);
      const c = new Circle(center, 7, Color.GREEN);
      assert.equal(c.radius, 7);
      assert.equal(c.center, center);
      assert.equal(c.name, "Circle");
    });
  });
});
