# --- toylang generated python ---
from toylang.runtime import (
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
    toy_truthy as _toy_truthy,
)

text = "the quick brown fox jumps over the lazy dog"
words = split(text, " ")
print("words:", len(words))
counts = dict()
i = 0
while _toy_truthy((i < len(words))):
    w = get(words, i)
    if _toy_truthy(has(counts, w)):
        set(counts, w, (get(counts, w) + 1))
    else:
        set(counts, w, 1)
    i = (i + 1)
print("'the' appears", get(counts, "the"), "times")
print("unique words:", len(keys(counts)))
