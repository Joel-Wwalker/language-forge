# toylang

Hand-written reference compiler for Language Forge's MVP slice
(`syntax=c_like`, `typing=dynamic`, `memory=host_gc`).

This compiler is the bedrock the verifier was built against: if its 8 canonical
tests pass, the verifier is sound, and we can swap LLM-generated components
in one at a time without losing ground.

## Hello world

```toy
print("Hello, World!");
```

## Run

```bash
python -m toylang.compile path/to/program.toy
python path/to/program.toy.out.py
```

## Operators

| kind        | operators                                |
|-------------|------------------------------------------|
| arithmetic  | `+ - * / %` (also unary `-`)             |
| comparison  | `== != < > <= >=`                        |
| logical     | `&& || !`                                |
| assignment  | `=`                                      |

## Memory model

Transpiles to Python and rides on Python's reference-counting + cycle GC.
Documented as `host_gc` because user programs cannot observe GC behavior
directly.
