# Stacky

## At a glance

- Stack-based concatenative language with postfix notation.
- Static type system with stack-effect annotations and type inference.
- Memory managed by host garbage collector (Python runtime).
- Variables mutable by default; mutation via explicit fetch and store operators.
- Panic-only error handling; no exceptions or result types.
- Transpiles to Python; inherits arbitrary-precision integers and reference-counting GC.

## Lexical structure

### Comments

Line comments begin with `\` followed by whitespace and continue to end of line.
