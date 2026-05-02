# Repair prompt

A previously generated component is failing verification. Your job is to produce a corrected, complete replacement file.

## Resolved spec

```json
{{SPEC}}
```

## Failing component

`{{COMPONENT}}` (target file: `{{FILENAME}}`)

## Current source of {{FILENAME}}

```{{LANG}}
{{CURRENT_SOURCE}}
```

## Failure report

```
{{FAILURE_REPORT}}
```

## Instructions

1. Read the failure report carefully. The verifier classifies failures as one of: parse error → parser; type error → typechecker; runtime exception → codegen or runtime; wrong output → codegen.
2. Determine the root cause and produce a corrected, COMPLETE replacement file (not a diff).
3. Stay consistent with the resolved spec.
4. Do not break passing tests, read all other components mentally before editing.

## Output format

Return ONLY a single fenced code block (matching the file's language) containing the full corrected file. No prose.
