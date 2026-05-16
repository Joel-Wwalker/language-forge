"""prologlang — pragmatic Prolog reference compiler (logic_like family).

The reference for the logic_like syntax family, parallel to:
  - toylang (c_like)
  - lisplang (s_expression)
  - forthlang (stack_based)
  - mllang (ml_like)

Language surface: pragmatic Prolog subset. Facts, rules, queries,
chronological backtracking via depth-first search. No cut, no
dynamic database mutation, no DCG, no constraint logic. See
`LOGICLANG_DESIGN.md` in the workspace root for the full design.
"""
