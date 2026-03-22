/** Color enum via frozen object with Symbol values. */
export const Color = Object.freeze({
  RED:    Symbol("RED"),
  GREEN:  Symbol("GREEN"),
  BLUE:   Symbol("BLUE"),
  YELLOW: Symbol("YELLOW"),
  WHITE:  Symbol("WHITE"),
});

export function colorName(color) {
  return Object.keys(Color).find((k) => Color[k] === color) ?? "UNKNOWN";
}

// --- Class registry ---
const _registry = new Map();

/** Class decorator (stage-3) — registers a Shape subclass by name. */
export function registerShape(cls) {
  _registry.set(cls.name, cls);
  return cls;
}

export function getRegisteredShapes() {
  return new Map(_registry);
}

/** Abstract base for all shapes. */
export class Shape {
  #name;
  #color;

  constructor(name, color = Color.BLUE) {
    if (new.target === Shape) {
      throw new TypeError("Shape is abstract — instantiate a subclass");
    }
    this.#name  = name;
    this.#color = color;
  }

  get name()  { return this.#name; }
  get color() { return this.#color; }

  area()      { throw new Error("area() not implemented"); }
  perimeter() { throw new Error("perimeter() not implemented"); }
  centroid()  { throw new Error("centroid() not implemented"); }

  describe() {
    return (
      `${this.name} [${colorName(this.color)}]  ` +
      `area=${this.area().toFixed(4)}  ` +
      `perimeter=${this.perimeter().toFixed(4)}  ` +
      `centroid=${this.centroid()}`
    );
  }

  toString() {
    return `<${this.constructor.name} color=${colorName(this.color)}>`;
  }
}
