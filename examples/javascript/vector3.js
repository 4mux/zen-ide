/** Immutable 3-D vector with operator-style methods. */
export class Vector3 {
  #x; #y; #z;

  constructor(x = 0, y = 0, z = 0) {
    this.#x = x;
    this.#y = y;
    this.#z = z;
    Object.freeze(this);
  }

  get x() { return this.#x; }
  get y() { return this.#y; }
  get z() { return this.#z; }

  length() {
    return Math.sqrt(this.#x ** 2 + this.#y ** 2 + this.#z ** 2);
  }

  normalized() {
    const len = this.length();
    return len === 0 ? new Vector3() : new Vector3(this.#x / len, this.#y / len, this.#z / len);
  }

  add(other) { return new Vector3(this.#x + other.x, this.#y + other.y, this.#z + other.z); }
  sub(other) { return new Vector3(this.#x - other.x, this.#y - other.y, this.#z - other.z); }
  scale(s)   { return new Vector3(this.#x * s, this.#y * s, this.#z * s); }

  dot(other) {
    return this.#x * other.x + this.#y * other.y + this.#z * other.z;
  }

  cross(other) {
    return new Vector3(
      this.#y * other.z - this.#z * other.y,
      this.#z * other.x - this.#x * other.z,
      this.#x * other.y - this.#y * other.x,
    );
  }

  // Symbol.iterator — enables destructuring: const [x, y, z] = vec
  [Symbol.iterator]() {
    return [this.#x, this.#y, this.#z][Symbol.iterator]();
  }

  toString() {
    return `(${this.#x}, ${this.#y}, ${this.#z})`;
  }
}
