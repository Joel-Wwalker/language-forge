# Tests prompt

Generate the canonical test programs for the target language. Each test is a pair: a source file plus a `<name>.expected_output.txt` file.

## Resolved spec

```json
{{SPEC}}
```

## Required canonical tests (ALL EIGHT, names are EXACT)

You MUST emit ALL of the following:

| name           | what it must do                                                                                    |
|----------------|----------------------------------------------------------------------------------------------------|
| `hello_world`  | prints exactly `Hello, World!`                                                                      |
| `arithmetic`   | basic int math + operator precedence, multiple `print` lines                                       |
| `variables`    | declaration, assignment, reuse, multiple `print` lines                                             |
| `conditionals` | if/else with comparison operators, plus an `else if`/`elif`, plus AND and OR tests                  |
| `loops`        | sum 1..10 → prints `55`                                                                              |
| `functions`    | definition, call, return value, recursion (factorial(5) = 120 + at least one more call)             |
| `closures`     | function returning a function that captures + mutates a variable (counter; print three increments)  |
| `strings`      | concatenation, `len()`, plus a `print` with multiple mixed-type arguments                           |

## Output format. JSON object, exactly one fenced block

Return ONLY one fenced ```json code block. The JSON value is an object whose keys are filenames (relative to `tests/`) and whose values are the file contents as STRINGS. Filenames literally contain the dot-extension from the spec (`{{SPEC.file_extension}}` when the model interpolates, but you should write it literally, e.g. `.toy`).

You MUST produce 16 keys total: 8 source files + 8 `.expected_output.txt` files.

### CRITICAL JSON encoding rules

- Every newline inside a string value MUST be the two characters `\` and `n`. Never embed a literal newline inside a JSON string.
- Every double-quote inside a string value MUST be `\"`.
- Every backslash inside a string value MUST be `\\`.
- The result must be VALID JSON parseable by `json.loads`. Run it through a mental JSON parser before finalizing.
- Do NOT wrap the JSON in extra prose. Do NOT use markdown headings inside the response.
- Do NOT abbreviate with `// ...` or `... and so on`. Emit every test in full.

### Anti-patterns (do NOT do these)

- ❌ Multiple fenced blocks (one per test). Use ONE block with one JSON object.
- ❌ A YAML-like or Python-dict-like value. Use STRICT JSON.
- ❌ Skipping a test or leaving a value as `"TODO"`.
- ❌ A trailing comma inside the object (JSON forbids it).
- ❌ Mixing the spec's syntax with a different syntax flavor (e.g. semicolons in a python_like spec).

### Concrete example for c_like syntax (extension `.toy`)

```json
{
  "hello_world.toy": "// Canonical: hello_world\nprint(\"Hello, World!\");\n",
  "hello_world.expected_output.txt": "Hello, World!\n",
  "arithmetic.toy": "// Canonical: arithmetic\nprint(1 + 2 * 3);\nprint((1 + 2) * 3);\nprint(20 - 4 - 3);\n",
  "arithmetic.expected_output.txt": "7\n9\n13\n"
}
```

### Concrete example for stack_based syntax (extension `.fth`)

For stack_based languages, programs are postfix sequences of words. Comments are `\` (line) and `( paren )`. Test calls evaluate by pushing args, calling the word, then printing with `.`. Booleans print as `true` / `false`; null is `nil`.

```json
{
  "hello_world.fth": "\\ Canonical: hello_world\n.\" Hello, World!\" cr\n",
  "hello_world.expected_output.txt": "Hello, World!\n",
  "arithmetic.fth": "\\ Canonical: arithmetic\n2 3 + .\n6 7 * .\n",
  "arithmetic.expected_output.txt": "5\n42\n",
  "functions.fth": "\\ Canonical: functions\n: factorial ( n -- n! )\n  dup 1 <= if drop 1 else dup 1 - factorial * then ;\n5 factorial .\n",
  "functions.expected_output.txt": "120\n"
}
```

### Concrete example for s_expression syntax (extension `.lsp`)

For s_expression languages, every form is `(operator operand operand ...)`. Comments are `;`. Use prefix arithmetic (`(+ a b)`), not infix. Booleans are unquoted symbols `true` / `false`; null is `nil`. List output prints in s-expression form `(1 2 3)` not `[1, 2, 3]`.

```json
{
  "hello_world.lsp": "; Canonical: hello_world\n(print \"Hello, World!\")\n",
  "hello_world.expected_output.txt": "Hello, World!\n",
  "arithmetic.lsp": "; Canonical: arithmetic\n(print (+ 1 (* 2 3)))\n(print (* (+ 1 2) 3))\n(print (- 20 4 3))\n",
  "arithmetic.expected_output.txt": "7\n9\n13\n",
  "variables.lsp": "; Canonical: variables\n(def x 10)\n(def y \"hello\")\n(print x)\n(print y)\n(set! x 20)\n(print x)\n",
  "variables.expected_output.txt": "10\nhello\n20\n",
  "functions.lsp": "; Canonical: functions\n(defn add (a b) (+ a b))\n(defn factorial (n) (if (<= n 1) 1 (* n (factorial (- n 1)))))\n(print (add 3 4))\n(print (factorial 5))\n",
  "functions.expected_output.txt": "7\n120\n"
}
```

(Truncated for brevity above: your real response must include all 16 entries.)

Each `expected_output.txt` MUST end with a single trailing newline (`\n`). Use the spec's syntax exactly: braces vs. indents vs. parens, `;` (lisp) vs. `;` (c-like statement terminator) vs. newline, `//` vs. `#` vs. `;` comments, `&&`/`||`/`!` vs. `and`/`or`/`not`.

## Natural-language phrasebook (HIGHEST PRIORITY when present)

If `spec.customization.natural_language` is set, EVERY test program must
be written using those sentence templates. NOT the spec's default syntax.

For each phrasebook entry, substitute:
- `<name>` → an actual identifier
- `<value>` / `<expr>` / `<cond>` → an actual expression
- `<body>` → a block of statements
- `<else>` → an else block
- `<params>` → a comma-separated parameter list
- `<args>` → a comma-separated argument list

Example: if `var_decl = "set <name> to <value>."`, the variables test
might have a line like `set greeting to "hello".`

Example: if `if_stmt = "if <cond> then <body> otherwise <else>."`, the
conditionals test uses that EXACT form for every if statement.

If a phrasebook entry exists for a construct, use it. If not, fall back
to the spec's default form for that construct. Mix is OK if some
constructs have entries and others don't.

The expected_output.txt is the program's stdout, NOT the source. Output
format follows the spec's `boolean_keywords` and `null_keyword` (which
the resolver may have updated to match phrasebook word entries).

## Naming convention

Read `spec.naming_convention`. Every identifier you introduce in test
programs must follow that convention. snake_case becomes `make_counter`
and `total_sum`; camelCase becomes `makeCounter` and `totalSum`;
PascalCase becomes `MakeCounter` and `TotalSum`. Match the convention in
ALL EIGHT canonical tests so the language has visual consistency.

## Null model

If `spec.null_model = none`, do not use the spec's null literal anywhere
in the test programs. If `null_model = option`, prefer `Some(value)` and
the empty Option for absence. The default (`nullable`) is the original
behavior.
