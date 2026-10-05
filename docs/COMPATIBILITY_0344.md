# Shader Tree mask continuation — 0.3.44

Native material partitions preserve the current group-mask input, so Multiply/Add and opacity build on preceding masks rather than restarting at white. Layer masks targeting an enclosing material group are captured once before its lowest material, retained across native partitions, and applied at group exit. The parameter compositor similarly places these masks before entering the target group. Nested texture-only scopes retain independent mask defaults.

This is a focused compatibility update, not full Modo parity. Arithmetic/inverted BSDF blending, arbitrary procedural semantics, complex masks outside captured membership, and the other 0.3.43 limitations remain. No render or Modo tests were run. Deferred regression scripts cover mask continuation and group targeting; visual comparison with Modo is still required.

Opaque override pruning is conservative when enclosing groups or earlier masks exist, so it cannot discard a lower material that a later group mask reveals. This may retain additional graph nodes.
