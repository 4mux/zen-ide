import { Color, Shape, registerShape } from "./shape.js";
import { Vector3 } from "./vector3.js";

export class Circle extends Shape {
  #center;
  #radius;

  constructor(center = new Vector3(), radius = 1, color = Color.BLUE) {
    super("Circle", color);
    this.#center = center;
    this.#radius = radius;
  }

  get radius() { return this.#radius; }
  get center() { return this.#center; }

  area()      { return Math.PI * this.#radius ** 2; }
  perimeter() { return 2 * Math.PI * this.#radius; }
  centroid()  { return this.#center; }

  describe() {
    return `${super.describe()}\n  radius=${this.#radius}  center=${this.#center}`;
  }
}

registerShape(Circle);
