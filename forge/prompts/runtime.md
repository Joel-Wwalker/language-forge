# Runtime prompt

Generate `runtime.py`. The codegen prelude imports helpers from this file
and the stdlib re-exports them under user-visible names.

## Resolved spec

```json
{{SPEC}}
```

## Required helpers (codegen depends on these by name)

- `toy_print(*args)`. Joins args with single space, prints with newline.
  Booleans, null, and floats follow the spec's stringification rules:
  spec's `boolean_keywords.true`/`false` and `null_keyword`. Whole-number
  floats print as their integer form (`2.0` becomes `2`).
- `toy_str(v)`. Same stringification, returns a string.
- `toy_truthy(v)`. Language truthiness. Only the spec's null and false
  values are falsy. Empty strings and 0 are truthy.

Use `import builtins as _builtins` and call `_builtins.print` to avoid
recursion when codegen has shadowed `print`.

## Required stdlib helpers (one per `spec.stdlib.functions` entry)

For each function listed in `spec.stdlib.functions`, expose a Python
function named `toy_<name>` with semantics matching the description.
The stdlib module re-exports them under the bare name.

Reference implementations to match:

```python
import sys, os, builtins as _builtins

def toy_input(prompt=""):
    return _builtins.input(prompt)

def toy_list(*items):
    return list(items)

def toy_len(coll):
    return len(coll)

def toy_get(coll, k, default=None):
    if isinstance(coll, list):
        if 0 <= k < len(coll):
            return coll[k]
        return default
    if isinstance(coll, dict):
        return coll.get(k, default)
    raise TypeError(f"get(): unsupported type {type(coll).__name__}")

def toy_set(coll, k, v):
    if isinstance(coll, list):
        # extend with nulls if writing past end
        while len(coll) <= k:
            coll.append(None)
        coll[k] = v
    elif isinstance(coll, dict):
        coll[k] = v
    else:
        raise TypeError("set(): need list or dict")
    return coll

def toy_push(lst, x):
    lst.append(x)
    return lst

def toy_pop(lst):
    return lst.pop()

def toy_dict(*pairs):
    if len(pairs) % 2 != 0:
        raise ValueError("dict() needs an even number of arguments")
    return dict(zip(pairs[0::2], pairs[1::2]))

def toy_has(coll, k):
    if isinstance(coll, dict):
        return k in coll
    if isinstance(coll, list):
        return isinstance(k, int) and 0 <= k < len(coll)
    return False

def toy_keys(d):
    return list(d.keys())

def toy_range(a, b=None):
    if b is None:
        return list(range(a))
    return list(range(a, b))

def toy_split(s, sep):
    return s.split(sep)

def toy_join(sep, lst):
    return sep.join(toy_str(x) for x in lst)

def toy_upper(s):    return s.upper()
def toy_lower(s):    return s.lower()
def toy_replace(s, old, new):
    return s.replace(old, new)

def toy_int(v):    return int(v)
def toy_float(v):  return float(v)

def toy_read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def toy_write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return None

def toy_argv():
    return list(sys.argv[1:])

def toy_exit(code=0):
    sys.exit(int(code))
```

If `boolean_evaluation = eager`, also expose:

```python
def _eager_and(a, b):
    # Force-evaluate both sides, then apply truthiness.
    return toy_truthy(a) and toy_truthy(b)

def _eager_or(a, b):
    return toy_truthy(a) or toy_truthy(b)
```

If `error_handling = result_type`, also expose `Ok` and `Err`:

```python
class _Result:
    def __init__(self, ok, value=None, error=None):
        self.ok = ok; self.value = value; self.error = error

def Ok(v):    return _Result(True, value=v)
def Err(msg): return _Result(False, error=msg)
```

## Output format

Return one fenced ```python code block with the full file contents.
