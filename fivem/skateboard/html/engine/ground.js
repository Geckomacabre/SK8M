// The ground the game gives: heights on a square grid (n x n samples, `cell` metres apart, the first at x0, z0, in
// Skate space with y up) -> the triangles the engine rides, two a cell, facing up. A cell with a corner the game
// found no ground under (NaN) is left out: a hole, not a spike.
export function gridTriangles({ n, cell, x0, z0, h }) {
  const out = new Float32Array((n - 1) * (n - 1) * 18);
  let at = 0;
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = h[j * n + i], b = h[j * n + i + 1], c = h[(j + 1) * n + i], d = h[(j + 1) * n + i + 1];
      if (a !== a || b !== b || c !== c || d !== d) continue;
      const x = x0 + i * cell, z = z0 + j * cell, X = x + cell, Z = z + cell;
      // (b - a) x (c - a) has to point up (+y): corners go a, c, b and b, c, d
      out.set([x, a, z, x, c, Z, X, b, z, X, b, z, x, c, Z, X, d, Z], at);
      at += 18;
    }
  }
  return at === out.length ? out : out.slice(0, at);
}
