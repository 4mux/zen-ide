/** Demo entry point — exercises cross-file imports, classes, and JS language features. */
import { Circle }    from "./circle.js";
import { Rectangle } from "./rectangle.js";
import { Renderer }  from "./renderer.js";
import { Color, colorName, getRegisteredShapes } from "./shape.js";
import { chunk, fibonacci, flatten, groupBy, timer } from "./utils.js";
import { Vector3 }   from "./vector3.js";

// --- Vector3 demo ---
const a = new Vector3(1, 2, 3);
const b = new Vector3(4, 5, 6);

console.log(`a = ${a}  b = ${b}`);
console.log(`a + b   = ${a.add(b)}`);
console.log(`a dot b = ${a.dot(b)}`);
console.log(`a x b   = ${a.cross(b)}`);
console.log(`|a|     = ${a.length().toFixed(5)}`);
console.log(`norm(a) = ${a.normalized()}\n`);

// Destructuring via Symbol.iterator
const [x, y, z] = a;
console.log(`Unpacked a: x=${x}, y=${y}, z=${z}\n`);

// --- Shape hierarchy + renderer ---
const renderer = new Renderer();
renderer
  .add(new Circle(new Vector3(0, 0, 0), 5, Color.RED))
  .add(new Circle(new Vector3(10, 0, 0), 3))
  .add(new Rectangle(new Vector3(0, 0, 0), 4, 6, Color.YELLOW))
  .add(new Rectangle(new Vector3(5, 5, 0), 10, 2));

console.log(renderer.render());

// --- Filter with arrow function ---
const big = renderer.filter((s) => s.area() > 20);
console.log("\nShapes with area > 20:");
big.forEach((s) => console.log(`  ${s.name} (${colorName(s.color)}) area=${s.area().toFixed(4)}`));

// --- Optional chaining + nullish coalescing ---
const top = renderer.sortedByArea({ reverse: true });
const largest = top[0] ?? null;
console.log(`\nLargest shape: ${largest?.name} area=${largest?.area().toFixed(4)}`);

// --- Generator demo ---
const fibs = [...fibonacci(10)];
console.log(`\nFibonacci(10): ${fibs}`);
console.log(`Chunked(3):    ${JSON.stringify(chunk(fibs, 3))}`);
console.log(`Flattened:     ${flatten(chunk(fibs, 3))}`);

// --- Symbol.iterator on Renderer ---
console.log("\nAll shapes (via for…of):");
for (const shape of renderer) {
  console.log(`  ${shape}`);
}

// --- Class registry ---
const registry = getRegisteredShapes();
console.log(`\nRegistered shapes: ${[...registry.keys()]}`);

// --- Performance timer ---
timer("sort 10k ints", () => [...Array(10_000).keys()].reverse().sort((a, b) => a - b));

// --- Map / Set / destructuring ---
const areaMap = Object.fromEntries([...renderer].map((s) => [s.name, s.area()]));
const uniqueColors = new Set([...renderer].map((s) => colorName(s.color)));
console.log(`\nArea map: ${JSON.stringify(areaMap)}`);
console.log(`Unique colors: ${[...uniqueColors].sort()}`);

// --- groupBy utility ---
const byName = groupBy([...renderer], (s) => s.name);
console.log("\nGrouped by name:");
for (const [name, shapes] of byName) {
  console.log(`  ${name}: ${shapes.length} shape(s)`);
}

// --- Async/await demo (self-contained) ---
async function fetchMockData(id) {
  await new Promise((r) => setTimeout(r, 0)); // simulates async I/O
  return { id, value: id * 2 };
}

(async () => {
  const ids = [1, 2, 3];
  const results = await Promise.all(ids.map(fetchMockData));
  console.log(`\nAsync results: ${JSON.stringify(results)}`);

  // for-await pattern
  async function* asyncRange(n) {
    for (let i = 0; i < n; i++) yield i;
  }
  const asyncVals = [];
  for await (const v of asyncRange(5)) asyncVals.push(v);
  console.log(`Async range:   ${asyncVals}`);
})();
