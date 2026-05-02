# LANGUAGE.md prompt

Generate `LANGUAGE.md`: the formal language reference. This is the
document a serious user reads when they want to know how the language
actually behaves. It must be technically thorough.

## Resolved spec

```json
{{SPEC}}
```

## Required structure

Use these section headings, in this order:

```
# <Lang Name>

## At a glance
## Lexical structure
## Grammar
## Types and values
## Variables and bindings
## Expressions
## Statements
## Functions
## Errors
## Standard library
## Memory and lifetime
## Examples
## Compatibility and limits
```

## Section requirements

- **At a glance**: 4 to 6 bullets. Syntax family, typing discipline,
  memory model, one distinguishing feature.
- **Lexical structure**: comments accepted, identifier rules, full
  keyword list, string literal forms, numeric literal forms, operators
  grouped by precedence.
- **Grammar**: a Lark-style EBNF for every statement form and every
  expression layer. No paraphrase. The actual grammar.
- **Types and values**: for dynamic, document the runtime tagged union
  (int, float, string, bool, null, function). For static, document the
  type system, annotation syntax, and inference rules.
- **Variables and bindings**: declaration syntax (match the spec
  exactly: `var`, `let`, `let mut`, etc.), scoping rules, shadowing.
- **Expressions**: each operator group with a short example. Precedence
  and associativity. Boolean evaluation strategy (short-circuit vs eager).
- **Statements**: each statement form with syntax and a 1-3 line example.
- **Functions**: definition, call, recursion, closures, multiple returns
  if supported, parameter passing.
- **Errors**: match `error_handling.kind` (panic_only / exceptions /
  result_type) and document the surface syntax plus behavior.
- **Standard library**: for every function in `spec.stdlib.functions`,
  give name, signature, behavior, and a one-line example.
- **Memory and lifetime**: quote `memory_model.notes`, then add 1 to 2
  paragraphs on observable consequences.
- **Examples**: three small annotated programs. Different from the
  canonical tests. Use the language's distinctive features.
- **Compatibility and limits**: list `feature_bans` from
  `spec.customization` if any. Note the Python transpilation target
  and any honest implications (integers are arbitrary-precision in
  practice, etc.).

## Voice rules (strict)

This is reference documentation. Read like Niklaus Wirth wrote it.

- No em-dashes or en-dashes. Periods, commas, colons.
- No marketing words: "elegant", "robust", "comprehensive", "powerful",
  "leverage", "harness", "seamless", "delve".
- Short declarative sentences.
- Code examples use the spec's exact syntax. Do not mix flavors.
- Do not announce ("here is the section that...", "we will now describe...").

## Output format

Return one fenced ```markdown code block. No prose outside the block.
