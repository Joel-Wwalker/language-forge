"""Toylang stdlib. The names that user programs call.

The codegen prelude imports a smaller subset of these (just the ones it
shadows: print, len, str). Everything else is available because user
programs can import it explicitly, and because the runtime module is on
sys.path during execution.
"""
from .runtime import (
    # Output / input
    toy_print as print,
    toy_input as input,
    # Collections
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
    # Strings
    toy_str as str,
    toy_split as split,
    toy_join as join,
    toy_upper as upper,
    toy_lower as lower,
    toy_replace as replace,
    # Numbers
    toy_int as int,
    toy_float as float,
    # Files / processes
    toy_read_file as read_file,
    toy_write_file as write_file,
    toy_argv as argv,
    toy_exit as exit,
)

__all__ = [
    "print", "input",
    "list", "len", "get", "set", "push", "pop", "dict", "has", "keys", "range",
    "str", "split", "join", "upper", "lower", "replace",
    "int", "float",
    "read_file", "write_file", "argv", "exit",
]
