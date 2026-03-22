import { Color, Shape, registerShape } from "./shape.js";
import { Vector3 } from "./vector3.js";

export class Rectangle extends Shape {
  #origin;
  #width;
  #height;

  constructor(origin = new Vector3(), width = 1, height = 1, color = Color.GREEN) {
    super("Rectangle", color);
    this.#origin = origin;
    this.#width  = width;
    this.#height = height;
  }

  get origin() { return this.#origin; }
  get width()  { return this.#width; }
  get height() { return this.#height; }

  area()      { return this.#width * this.#height; }
  perimeter() { return 2 * (this.#width + this.#height); }

  centroid() {
    return this.#origin.add(new Vector3(this.#width / 2, this.#height / 2, 0));
  }

  describe() {
    return (
      `${super.describe()}\n` +
      `  origin=${this.#origin}  w=${this.#width}  h=${this.#height}`
    );
  }
}

registerShape(Rectangle);
