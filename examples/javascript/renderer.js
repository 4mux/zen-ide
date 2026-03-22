/** Collects shapes, renders them, and provides filter/aggregate helpers. */
export class Renderer {
  #shapes = [];

  add(shape) {
    this.#shapes.push(shape);
    return this;
  }

  get count() { return this.#shapes.length; }

  render() {
    const header = `=== Renderer (${this.count} shapes) ===`;
    const body   = this.#shapes.map((s) => s.describe()).join("\n");
    const footer = `Total area: ${this.totalArea().toFixed(4)}`;
    return [header, body, footer].join("\n");
  }

  filter(predicate) {
    return this.#shapes.filter(predicate);
  }

  totalArea() {
    return this.#shapes.reduce((sum, s) => sum + s.area(), 0);
  }

  sortedByArea({ reverse = false } = {}) {
    const sorted = [...this.#shapes].sort((a, b) => a.area() - b.area());
    return reverse ? sorted.reverse() : sorted;
  }

  // Generator — yields shapes lazily
  *[Symbol.iterator]() {
    yield* this.#shapes;
  }
}
