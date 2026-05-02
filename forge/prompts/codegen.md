# Codegen prompt

Generate `codegen.py` for the target language. Transpiles the parse tree into Python source.

## Resolved spec

```json
{{SPEC}}
```

## CRITICAL: AST shape

The parser returns a **Lark `Tree`** object. NOT a dict. NOT an `ast.AST`. You walk it like this:

```python
from lark import Tree, Token

def visit(node):
    if isinstance(node, Token):
        return str(node)            # NOT node.value, NOT node["type"]
    # node is a Tree
    method = getattr(self, f"visit_{node.data}", None)  # node.data, NOT node["type"]
    return method(node)             # children at node.children
```

Do NOT write `tree["type"]`, `tree["children"]`, `tree["body"]`, or anything dict-like. Lark Trees are not subscriptable. Use `tree.data`, `tree.children`, and check `isinstance(x, Token)` for leaves.

The rule names you'll dispatch on are exactly the ones in the parser prompt: `var_decl`, `func_def`, `params`, `if_stmt`, `else_clause`, `while_stmt`, `return_stmt`, `block`, `expr_stmt`, `assign_op`, `logical_or`, `logical_and`, `equality`, `comparison`, `term`, `factor`, `unary`, `call`, `trailer`, `args`, `int_lit`, `float_lit`, `string_lit`, `true_lit`, `false_lit`, `null_lit`, `name_ref`, `paren`, `passthru`.

## Requirements

- Expose `generate(tree) -> str`. The returned string is a complete, runnable Python program.
- Prepend a PRELUDE that imports the full stdlib so user programs can call any of them without explicit imports. Use this exact shape (replace `<lang_name>` with the spec's `lang_name`):
  ```python
  from <lang_name>.runtime import (
      toy_print as print,
      toy_input as input,
      toy_list as list,
      toy_len as len,
      toy_get as get,
      toy_set as set,
      toy_push as push,
      toy_pop as pop,
      toy_dict as dict,
      toy_has as has,
      toy_keys as keys,
      toy_range as range,
      toy_str as str,
      toy_split as split,
      toy_join as join,
      toy_upper as upper,
      toy_lower as lower,
      toy_replace as replace,
      toy_int as int,
      toy_float as float,
      toy_read_file as read_file,
      toy_write_file as write_file,
      toy_argv as argv,
      toy_exit as exit,
      toy_truthy as _toy_truthy,
  )
  ```
  Only include names that appear in `spec.stdlib.functions` (plus `toy_truthy as _toy_truthy`, always).
- Operator translation:
  - `&&` → `and`, `||` → `or`, `!` → `not `
  - Other arithmetic/comparison operators map 1:1 to Python.
- Truthiness: emit `if _toy_truthy(cond):` (NOT `if cond:`) so language-level truthiness is consistent.
- Closures: when a nested function assigns to a name from an enclosing function scope, emit a `nonlocal` declaration. When a nested function assigns to a module-scope name, emit `global`. Implement this via a scope-analysis pass per function:
  - `declared = parameters ∪ var-decls ∪ inner-func-defs in this body`
  - `assigned = names appearing as LHS of plain assignment (no var) in this body`
  - `free_assigned = assigned − declared`
  - Each name in `free_assigned` becomes either `nonlocal` (if it appears in any enclosing function's `declared`) or `global`.
- Top-level `var x = expr;` becomes `x = expr` at module level.
- `func name(args) { body }` becomes `def name(args): body` at the appropriate scope.
- `if (cond) { ... } else if (...) { ... } else { ... }` becomes `if/elif/else` in Python.
- `while (cond) { body }` becomes `while _toy_truthy(cond): body`.
- `expr_stmt` whose expression is `assign_op` becomes a Python assignment statement, NOT an expression.
- Indent with 4 spaces.

## Natural-language phrasebook

If `spec.customization.natural_language` is set, the parser will use
custom sentence templates but the AST node names stay the same
(`var_decl`, `func_def`, `if_stmt`, etc.). Codegen dispatches on those
names regardless. The only thing you may need to honor:

- `true_word` / `false_word` / `null_word` are the spec-level forms
  in `boolean_keywords` and `null_keyword`. Just use those when emitting
  literal `true`/`false`/`None` from the AST.

Otherwise, codegen runs unchanged.

## Naming convention

Read `spec.naming_convention`. Use it consistently in transpiled identifier
names. The runtime helpers stay `toy_*` (we don't rename those), but any
identifiers the user writes should retain their original casing in the
transpiled Python.

## Null model

Read `spec.null_model`. Affects how absence is represented:

- `nullable`: standard. The spec's `null_keyword` produces `None` in Python.
- `option`: emit `Some(x)` / `None` constructors. The runtime ships
  `Some`, `is_some`, `unwrap` helpers. The codegen treats the spec's
  `null_keyword` as `None` (the empty Option), not as a Python `None`.
- `none`: the spec's `null_keyword` is reserved but never produced. Any
  function that previously returned null must use the spec's `error_handling`
  (panic, exceptions, or Result) for failure.

## Extended option behaviors

The `options` block contains additional axes the user may have customized. Honor them:

- `boolean_evaluation = eager` → DO NOT translate `&&`/`||` to Python `and`/`or` (which short-circuit). Translate them to a runtime helper, e.g. `_eager_and(lhs, rhs)`, that evaluates both sides. Define the helper in `runtime.py`.
- `boolean_evaluation = short_circuit` → standard Python `and`/`or` (current behavior).
- `default_mutability = immutable` → emit Python assignment for `let mut x = ...` AND for the FIRST `let x = ...` (initial binding), but reject reassignment of plain `let x = ...` at codegen time with a clear error message.
- `error_handling = exceptions` → support `try { ... } catch (e) { ... }` (or `try: ... except e: ...`) and `throw expr` → Python `raise Exception(str(expr))`.
- `error_handling = result_type` → built-in `Result` value type. Provide `Ok(x)` / `Err(msg)` constructors in the runtime.
- `loop_forms` may include `c_for` (`for (init; cond; step) { body }`), `foreach` (`for x in iter`), `repeat_until`, `loop_break` (Rust-style `loop { ... break value; }`). Translate each to its closest Python equivalent.
- `multiple_returns = tuple` → `return a, b` becomes `return (a, b)` in Python; destructuring `let (x, y) = f()` becomes `(x, y) = f()`.

## Output format

Return ONLY a single fenced ```python code block with the full file contents. No prose, no partial code, no separate sections.
