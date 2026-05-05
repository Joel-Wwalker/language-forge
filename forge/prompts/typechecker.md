# Typechecker prompt

Generate `typechecker.py` for the target language. **Only invoked when `options.typing == "static"`.**

## Resolved spec

```json
{{SPEC}}
```

## CRITICAL: Lark passthrough rules

The grammar uses `?expr: assign`, `?stmt: var_decl | ...` patterns and similar. These `?` rules COLLAPSE in the tree when there's only a single child. So a node arriving at `check_expr` could be:

- A bare passthrough with **1 child** (the inner expression)
- A binary operation with **3 children**: `[lhs, op_token, rhs]`
- A unary operation with **2 children**: `[op_token, operand]`
- A primary literal (no children, just the alias name)

**Always inspect `tree.data` AND `len(tree.children)` before indexing.** Never blindly access `tree.children[2]`. Dispatch like this:

```python
def check_expr(self, tree):
    # Handle passthrough nodes that the grammar collapsed.
    if len(tree.children) == 1 and isinstance(tree.children[0], Tree):
        return self.check_expr(tree.children[0])

    method = getattr(self, f"check_{tree.data}", None)
    if method:
        return method(tree)

    # Binary fold for chains: lhs op rhs op rhs ...
    if len(tree.children) >= 3:
        result_t = self.check_expr(tree.children[0])
        i = 1
        while i + 1 < len(tree.children):
            op = tree.children[i]
            rhs_t = self.check_expr(tree.children[i + 1])
            result_t = self._apply_op(op, result_t, rhs_t, tree)
            i += 2
        return result_t

    if len(tree.children) == 2:    # unary
        return self._apply_unary(tree.children[0], self.check_expr(tree.children[1]), tree)

    raise TypeCheckError(f"unhandled expr shape: {tree.data}, {len(tree.children)} children")
```

Same for statements: `?stmt` passthrough means a `stmt` Tree might just have one child (the actual statement). Always recurse on `tree.children[0]` when you see a passthrough.

## Requirements

- Expose `check(tree) -> tree`. On type errors, raise `TypeCheckError` with a message including line/column.
- Use `tree` from the parser (Lark Tree).
- Maintain a scope stack of `name -> type` mappings. Push on function entry, pop on exit.
- Type rules:
  - Integer literals (`int_lit`) become `int`. Float (`float_lit`) becomes `float`. String (`string_lit`) becomes `string`. Booleans (`true_lit`, `false_lit`) become `bool`. Null becomes the spec's null type.
  - Arithmetic operators require numeric operands; `+` also accepts string + string.
  - Comparisons return `bool`. Logical operators require `bool` and return `bool`.
  - Function definitions register the declared return type; `return` statements must match.
  - Variable declarations with annotations: assigned value must be assignment-compatible.
- Variable declarations without annotations: infer from the RHS expression.
- For incompatible types or unbound names, raise `TypeCheckError` with line/column context (use `tree.meta.line` etc).
- Top-level: walk all top-level statements; functions get checked when defined.

## Common pitfalls

1. **Don't index past the children list.** Always `len(tree.children)` first.
2. **Tokens vs Trees.** Operator slots are Lark `Token` objects (use `str(tok)` for the operator string). Operands are `Tree` objects.
3. **Literal typing.** Each `*_lit` node returns a fixed type. Don't recurse into `int_lit` looking for sub-expressions.
4. **Don't return `None` from `check_expr`.** Every path must return a type string.

## S-expression family (when `options.syntax == "s_expression"`)

Typed Racket / Hy convention: type annotations live in a separate `(: name type)` form that PRECEDES the binding. Example:

```
(: add (-> Int Int Int))
(defn add (a b) (+ a b))

(: x Int)
(def x 10)
```

Grammar-wise the parser exposes these as `:_decl` rules (or similar). The typechecker should:
- Walk `:_decl` annotations BEFORE the matching `def`/`defn` to seed the type environment.
- Type-check function bodies against the annotated return type if present; infer otherwise.
- Operator-headed `call` nodes (`+`, `<`, `and`, etc.) are typed exactly like the equivalent c_like binops: `(+ Int Int) -> Int`, `(< Int Int) -> Bool`, etc.
- Primitive type names are PascalCase: `Int`, `Float`, `String`, `Bool` (not `int`/`float` like c_like).
- `nil` has type `Null` (or whatever the spec's null model dictates). Booleans `true` / `false` are unquoted symbols of type `Bool`.

Inference is the norm in typed Lisps, so it's fine to skip annotations and infer from the binding's RHS unless the spec explicitly demands annotations for every binding.

## Output format

Return ONLY a single fenced ```python code block with the full file contents. No prose. No partial code.
