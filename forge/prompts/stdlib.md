# Stdlib prompt

Generate `stdlib.py`. Re-export every runtime helper under its
user-visible name so generated programs can call `print`, `list`,
`read_file`, etc. directly.

## Resolved spec

```json
{{SPEC}}
```

## Output

For every entry in `spec.stdlib.functions`, re-export the matching
`toy_<name>` from `runtime` as `<name>`. Example shape:

```python
"""Stdlib for the generated language. Names users call from their programs."""
from .runtime import (
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
)

__all__ = [
    "print", "input", "list", "len", "get", "set", "push", "pop", "dict",
    "has", "keys", "range", "str", "split", "join", "upper", "lower",
    "replace", "int", "float", "read_file", "write_file", "argv", "exit",
]
```

Adapt the list to match the actual `spec.stdlib.functions` entries.
Don't omit any function the spec lists. Don't add functions the spec
doesn't list.

Codegen's PRELUDE imports a different set (only the ones it needs to
shadow Python builtins safely). The stdlib module is what user programs
import implicitly through the runtime.

## Output format

Return one fenced ```python code block with the full file contents.
