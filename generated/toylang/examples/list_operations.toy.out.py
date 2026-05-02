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

nums = list(3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5)
print("count:", len(nums))
i = 0
total = 0
biggest = get(nums, 0)
while _toy_truthy((i < len(nums))):
    x = get(nums, i)
    total = (total + x)
    if _toy_truthy((x > biggest)):
        biggest = x
    i = (i + 1)
print("sum:", total)
print("max:", biggest)
print("avg:", (total / len(nums)))
