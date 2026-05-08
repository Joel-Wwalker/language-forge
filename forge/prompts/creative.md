# Creative content (Phase 1.5 Stage D)

You are writing a short prose intro for a programming language's README.
The language has already been generated; you're adding personality on top
of templated infrastructure.

## Spec for context

```json
{{SPEC}}
```

## Your job

Write a 2-3 sentence prose intro that flavors the README with the
persona's voice and the era's vibes. Don't repeat the origin story
verbatim: that lives elsewhere on the README. Be specific about what
makes this language feel like THIS language, not just any language in
its family.

If the spec has a `customization.docs_persona` or `customization.persona`,
let it color the prose. If a `keyword_theme` (pirate, Shakespearean,
Latin, cozy, corporate) is set, lean into the theme's tone: but write
in modern English; don't translate the prose itself into the theme.

Tone:

- Concrete, not abstract. Say what the language *does*, not what it
  *is about*.
- Honest about scope. Don't promise features the language doesn't have.
- 80-180 words. Shorter is better than longer.
- No marketing words ("powerful", "elegant", "robust", "seamless").
- No hedges ("in this fictional scenario", "though limited in scope").
- One sentence's worth of personality, not a personal manifesto.

## Output

Plain text. No fences, no headers. Just 2-3 sentences.
