"""mllang — dynamic ML reference compiler (OCaml-flavored subset).

The reference for the ml_like syntax family, parallel to:
  - toylang (c_like)
  - lisplang (s_expression)
  - forthlang (stack_based)

Language surface: OCaml-flavored subset. `let` / `let rec` bindings,
expression-form `if then else`, pattern matching on lists / ADTs /
tuples, strict evaluation, dynamic typing. See `MLLANG_DESIGN.md`
in the workspace root for the full design.
"""
