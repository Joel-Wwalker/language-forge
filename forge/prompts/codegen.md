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
  - `&&` becomes `and`, `||` becomes `or`, `!` becomes `not `
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

## S-expression family (when `options.syntax == "s_expression"`)

The grammar has no precedence layer. Operators like `+`, `<`, `and` are
matched as `NAME` tokens, then appear as the head of a `call` rule.
Codegen MUST detect operator-headed calls and emit Python infix.

CRITICAL: every form in s_expression code is an EXPRESSION (`call` rule
in the grammar), but Python distinguishes statements from expressions.
You must track whether you're emitting in statement position (top-level,
inside `(do ...)`, inside a function body) or expression position
(arithmetic operand, condition of an if, etc.). The cleanest way is to
have TWO methods: `emit_stmt(node)` and `emit_expr(node)`. They share
the operator-detection logic but emit differently for `set!`, `do`, `if`,
`fn`, and `while`.

Here is a complete reference implementation pattern. Adapt it to your
visitor style but DO NOT leave any branch as a stub.

```python
ARITHMETIC_OPS = {"+", "-", "*", "/", "mod"}
COMPARISON_OPS = {"=", "!=", "<", ">", "<=", ">="}
LOGICAL_OPS    = {"and", "or"}

def _head_and_args(call_node):
    # call: "(" NAME args? ")"  becomes  NAME is children[0], args (if any) come next
    head = str(call_node.children[0])
    rest = call_node.children[1:]
    args = []
    if rest and getattr(rest[0], "data", None) == "args":
        args = list(rest[0].children)
    return head, args

def emit_expr(self, node):
    """Emit a Python expression string for any `call`-rule node. Always
    returns a single-line string suitable for use in an expression context."""
    if isinstance(node, Token):
        return str(node)
    if node.data == "int_lit":   return str(node.children[0])
    if node.data == "float_lit": return str(node.children[0])
    if node.data == "string_lit":return str(node.children[0])
    if node.data == "true_lit":  return "True"
    if node.data == "false_lit": return "False"
    if node.data == "null_lit":  return "None"
    if node.data == "name_ref":  return str(node.children[0])
    if node.data == "call":
        head, args_nodes = _head_and_args(node)
        args = [self.emit_expr(a) for a in args_nodes]
        if head in ARITHMETIC_OPS and len(args) == 2:
            py_op = {"mod": "%"}.get(head, head)
            return f"({args[0]} {py_op} {args[1]})"
        if head == "=" and len(args) == 2:
            return f"({args[0]} == {args[1]})"
        if head in COMPARISON_OPS and len(args) == 2:
            return f"({args[0]} {head} {args[1]})"
        if head in LOGICAL_OPS and len(args) == 2:
            return f"({args[0]} {head} {args[1]})"
        if head == "not" and len(args) == 1:
            return f"(not {args[0]})"
        if head == "if" and len(args) == 3:
            # Lisp `if` is an expression: emit Python ternary.
            return f"({args[1]} if _toy_truthy({args[0]}) else {args[2]})"
        if head == "do":
            # `(do e1 e2 ... eN)` in expression position uses a tuple
            # subscript trick to evaluate all and return the last:
            #   (e1, e2, ..., eN)[-1]
            # The empty case is invalid input; assume at least one form.
            if not args:
                return "None"
            if len(args) == 1:
                return args[0]
            return f"({', '.join(args)})[-1]"
        if head == "fn":
            # (fn (params) body)  becomes  lambda params: body
            # This is the EXPRESSION form. If body is multi-statement
            # (contains set! or multiple do-forms), prefer a named
            # nested def via emit_stmt instead.
            params_node = args_nodes[0] if args_nodes else None
            params = " "
            if params_node is not None and getattr(params_node, "data", None) == "params":
                params = ", ".join(str(p) for p in params_node.children)
            body_args = args_nodes[1:]
            if len(body_args) == 1:
                body = self.emit_expr(body_args[0])
            else:
                body_exprs = [self.emit_expr(b) for b in body_args]
                body = f"({', '.join(body_exprs)})[-1]"
            return f"(lambda {params}: {body})"
        if head == "set!" and len(args) == 2:
            # set! in expression position: walrus operator (Python 3.8+).
            # `(... (set! x 5) ...)` is unusual; preferable to keep set!
            # in statement position via emit_stmt.
            return f"({args[0]} := {args[1]})"
        # Plain function call.
        return f"{head}({', '.join(args)})"
    # Fallback: stringify
    return str(node)

def emit_stmt(self, node, indent=""):
    """Emit one or more Python statement lines for a top-level form or
    function-body form. Returns a string with embedded newlines."""
    if node.data == "var_decl":
        # (def NAME expr)
        name = str(node.children[0])
        val = self.emit_expr(node.children[1])
        return f"{indent}{name} = {val}"
    if node.data == "func_def":
        # (defn NAME (params) form+)
        name = str(node.children[0])
        params_node = node.children[1] if len(node.children) > 1 and getattr(node.children[1], "data", None) == "params" else None
        params = ", ".join(str(p) for p in params_node.children) if params_node else ""
        body_forms = node.children[2:] if params_node else node.children[1:]
        return self._emit_function(indent, name, params, body_forms)
    if node.data == "if_stmt":
        # (if cond then else)
        cond = self.emit_expr(node.children[0])
        then_s = self.emit_stmt(node.children[1], indent + "    ") if hasattr(node.children[1], "data") and node.children[1].data == "call" and self._head(node.children[1]) == "do" else f"{indent}    {self.emit_expr(node.children[1])}"
        else_s = self.emit_stmt(node.children[2], indent + "    ") if hasattr(node.children[2], "data") and node.children[2].data == "call" and self._head(node.children[2]) == "do" else f"{indent}    {self.emit_expr(node.children[2])}"
        return f"{indent}if _toy_truthy({cond}):\n{then_s}\n{indent}else:\n{else_s}"
    if node.data == "while_stmt":
        # (while cond form+)
        cond = self.emit_expr(node.children[0])
        body_forms = node.children[1:]
        body = "\n".join(self.emit_stmt(f, indent + "    ") for f in body_forms)
        return f"{indent}while _toy_truthy({cond}):\n{body}"
    if node.data == "return_stmt":
        if not node.children:
            return f"{indent}return"
        val = self.emit_expr(node.children[0])
        return f"{indent}return {val}"
    if node.data == "expr_stmt":
        # A bare form. Could be (set! x v), (do ...), or any expression.
        # Special-case set! and do to emit clean statement-form Python.
        e = node.children[0]
        if getattr(e, "data", None) == "call":
            head, args_nodes = _head_and_args(e)
            if head == "set!" and len(args_nodes) == 2:
                target = str(args_nodes[0])
                val = self.emit_expr(args_nodes[1])
                return f"{indent}{target} = {val}"
            if head == "do":
                lines = []
                for f in args_nodes:
                    lines.append(self.emit_stmt_or_expr(f, indent))
                return "\n".join(lines)
        # Fall through: emit as an expression statement.
        return f"{indent}{self.emit_expr(e)}"
    # Fallback
    return f"{indent}{self.emit_expr(node)}"

def _emit_function(self, indent, name, params, body_forms):
    """Emit `def name(params): ...` with implicit-last-expression return.

    For each body form except the LAST: emit as a statement.
    For the LAST: emit `return <expr>` (so the function returns a value).
    Detect free assignments to enclosing-scope variables and emit
    `nonlocal` declarations at the top of the body.
    """
    # 1. Find names that are free-assigned inside this body.
    declared = set([p.strip() for p in params.split(",") if p.strip()])
    free_assigned = self._scan_free_assigns(body_forms, declared)
    nonlocals = sorted(n for n in free_assigned if n in self._enclosing_scope)
    globals_ = sorted(n for n in free_assigned if n not in self._enclosing_scope and n in self._module_scope)

    inner_indent = indent + "    "
    head = f"{indent}def {name}({params}):"
    nl_lines = []
    if nonlocals:
        nl_lines.append(f"{inner_indent}nonlocal {', '.join(nonlocals)}")
    if globals_:
        nl_lines.append(f"{inner_indent}global {', '.join(globals_)}")

    # 2. Track enclosing scope for nested defs.
    self._enclosing_scope = self._enclosing_scope | declared
    body_lines = []
    for i, form in enumerate(body_forms):
        is_last = (i == len(body_forms) - 1)
        if is_last:
            # Emit the last form as `return <value>` unless it's
            # explicitly a return_stmt or a control-flow statement.
            if getattr(form, "data", None) in ("return_stmt", "if_stmt",
                                               "while_stmt", "var_decl",
                                               "func_def"):
                body_lines.append(self.emit_stmt(form, inner_indent))
            else:
                body_lines.append(f"{inner_indent}return {self.emit_expr(form) if not (getattr(form, 'data', None) == 'expr_stmt') else self.emit_expr(form.children[0])}")
        else:
            body_lines.append(self.emit_stmt(form, inner_indent))

    return "\n".join([head] + nl_lines + body_lines)
```

The implementation above is dense; the principles:

1. **Two emit methods**: `emit_expr` (returns a string) and `emit_stmt`
   (returns one or more lines with indent). Never leave a branch as a
   `...` placeholder.
2. **`(do ...)` in expression position** evaluates all forms and returns
   the last. Use Python's tuple-subscript trick: `(e1, e2, e3)[-1]`.
   NEVER emit `()[-1]` (empty tuple, IndexError).
3. **`(if cond then else)` in expression position** emits a Python
   ternary: `(then if _toy_truthy(cond) else else)`.
4. **`(set! name value)`** in statement position emits `name = value`.
   In expression position, use the walrus operator `(name := value)`.
5. **`(defn name (a b) form+)`**: the LAST body form becomes
   `return <expr>`; earlier forms are statements. Closures capturing an
   enclosing variable need `nonlocal x` at the top of the body.
6. **`(fn (params) body)`**: emit `lambda params: body`. If body is
   multi-form, wrap as `lambda params: (e1, e2, e3)[-1]`. NEVER emit
   `lambda: ()[-1]` (zero-form body) . that is always a bug; pass
   `None` instead.
7. **Booleans / null**: `true` becomes `True`, `false` becomes `False`, `nil` becomes `None`.
8. **Comments**: `;` line comments. Handled by the parser, no codegen change.
9. **Operator translation in calls**: arithmetic/comparison/logical heads
   in `call` nodes become Python infix; everything else is a regular
   function call.

## Stack-based family (when `options.syntax == "stack_based"`)

The fundamental shape is different: programs are a SEQUENCE OF WORDS that manipulate an implicit data stack. The reference compiler `generated/forthlang/codegen.py` has a complete working implementation; copy and adapt that pattern.

Codegen approach:
- A global Python list `_stack` is the data stack. `push(v)` appends; `pop()` removes the last item.
- Number / string / boolean / null literals emit `push(value)`.
- Variable name references (declared via `variable name`) emit `pushv("name")` (push the address).
- `@` (fetch) and `!` (store) are stdlib functions that pop the address + value.
- Stack manipulation words (`dup`, `drop`, `swap`, `over`, `rot`, `nip`, `tuck`) are stdlib functions on `_stack`.
- Arithmetic / comparison / logical words (`+`, `-`, `*`, `/`, `mod`, `=`, `<>`, `<`, `>`, `<=`, `>=`, `and`, `or`, `not`) pop two values, push the result.
- `:` colon definitions emit `def name():` with the body as nested calls.
- `if cond_body else else_body then` emits `if _toy_truthy(pop()):` / `else:` (consumes top of stack).
- `begin body until` emits `while True: body; if _toy_truthy(pop()): break`.
- `do body loop` emits `for _do_i in range(start, limit):` (pops start + limit).
- `." text"` emits `_print_str("text")` (no trailing newline).
- `.` (period) emits `_print_top()` (pops + prints with newline).
- `cr` emits `_cr()` (newline).

Key gotchas:
- Word names that aren't valid Python identifiers (`+`, `<=`, `?`, `!`) must be MANGLED at definition AND call sites: `+ → _op_add`, `<= → _op_le`, `? → _q`, `! → _bang`. Define a `_py_name(word)` helper and apply consistently.
- The codegen MUST track which names were declared via `variable` so name references emit `pushv(name)` not a function call.
- Forth defaults are global; nested `:` definitions inside another `:` definition still create top-level Python functions. Don't try to model lexical scopes.

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

- `boolean_evaluation = eager` becomes DO NOT translate `&&`/`||` to Python `and`/`or` (which short-circuit). Translate them to a runtime helper, e.g. `_eager_and(lhs, rhs)`, that evaluates both sides. Define the helper in `runtime.py`.
- `boolean_evaluation = short_circuit` becomes standard Python `and`/`or` (current behavior).
- `default_mutability = immutable` becomes emit Python assignment for `let mut x = ...` AND for the FIRST `let x = ...` (initial binding), but reject reassignment of plain `let x = ...` at codegen time with a clear error message.
- `error_handling = exceptions` becomes support `try { ... } catch (e) { ... }` (or `try: ... except e: ...`) and `throw expr` becomes Python `raise Exception(str(expr))`.
- `error_handling = result_type` becomes built-in `Result` value type. Provide `Ok(x)` / `Err(msg)` constructors in the runtime.
- `loop_forms` may include `c_for` (`for (init; cond; step) { body }`), `foreach` (`for x in iter`), `repeat_until`, `loop_break` (Rust-style `loop { ... break value; }`). Translate each to its closest Python equivalent.
- `multiple_returns = tuple` becomes `return a, b` becomes `return (a, b)` in Python; destructuring `let (x, y) = f()` becomes `(x, y) = f()`.

## Output format

Return ONLY a single fenced ```python code block with the full file contents. No prose, no partial code, no separate sections.
