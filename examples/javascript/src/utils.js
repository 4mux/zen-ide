/** Measures execution time of a synchronous callback. */
export function timer(label, fn) {
  const start = performance.now();
  fn();
  const ms = (performance.now() - start).toFixed(2);
  console.log(`[${label}] ${ms} ms`);
}

/** Generator that yields the first n Fibonacci numbers. */
export function* fibonacci(n) {
  let [a, b] = [0, 1];
  for (let i = 0; i < n; i++) {
    yield a;
    [a, b] = [b, a + b];
  }
}

/** Split an array into fixed-size chunks. */
export function chunk(arr, size) {
  const result = [];
  for (let i = 0; i < arr.length; i += size) {
    result.push(arr.slice(i, i + size));
  }
  return result;
}

/** Flatten one level of nesting. */
export function flatten(nested) {
  return nested.flat();
}

/** Group an array of objects by a key function. */
export function groupBy(arr, keyFn) {
  return arr.reduce((map, item) => {
    const key = keyFn(item);
    const bucket = map.get(key) ?? [];
    bucket.push(item);
    map.set(key, bucket);
    return map;
  }, new Map());
}
