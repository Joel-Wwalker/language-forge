# README.md prompt

Generate the user-facing `README.md` for the generated language.

## Resolved spec

```json
{{SPEC}}
```

## Required sections

- Title (the language name).
- One short paragraph: what design choices were made and why. Cite
  `design_notes`. No more than three sentences.
- "Hello, World" snippet using the spec's exact syntax.
- "Syntax tour": one runnable snippet per construct (variables, functions,
  conditionals, loops, closures, strings). Each snippet is 3-8 lines.
- "Operators" reference table.
- "How to run":
  ```
  python -m <lang_name>.compile path/to/program<EXT>
  python path/to/program<EXT>.out.py
  ```
- "Memory model": one paragraph quoting `memory_model.notes`.
- "License": MIT.

Keep the whole file under 130 lines.

## Voice rules (strict)

Write the README the way a working software engineer writes a README.
Direct, terse, no marketing. Specifically:

- Do not use em-dashes or en-dashes. Use periods, commas, or colons instead.
- Do not write "elegant", "robust", "comprehensive", "powerful", "seamless",
  "leverage", "unleash", "harness", "delve", "tapestry", "realm".
- Do not start sentences with "Let me" or "I'll".
- No hedging adverbs ("simply", "easily", "just"). Either it is or it isn't.
- Short sentences. One idea per sentence.
- If `customization.docs_persona` is set, follow that voice. Otherwise
  default to "technical" (the rules above).

## docs_persona variants

If `spec.customization.docs_persona` is set, override the technical default:

- `academic_paper`: formal abstract first. "We choose X because Y."
  Include a "Related work" paragraph. Cite `design_notes` as decisions.
- `tutorial_with_exercises`: narrative; each section ends with one or
  two short exercises.
- `historical_fiction`: ground every choice in a fictional notebook from
  some decade. Stay accurate to the actual semantics. No lying.
- `pirate`: pirate voice. Technical content stays correct.

## Output format

Return one fenced ```markdown code block. No prose outside the block.
