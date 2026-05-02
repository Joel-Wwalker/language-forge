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

N = 100
is_prime = list()
i = 0
while _toy_truthy((i <= N)):
    push(is_prime, True)
    i = (i + 1)
set(is_prime, 0, False)
set(is_prime, 1, False)
i = 2
while _toy_truthy(((i * i) <= N)):
    if _toy_truthy(get(is_prime, i)):
        j = (i * i)
        while _toy_truthy((j <= N)):
            set(is_prime, j, False)
            j = (j + i)
    i = (i + 1)
found = list()
i = 2
while _toy_truthy((i <= N)):
    if _toy_truthy(get(is_prime, i)):
        push(found, i)
    i = (i + 1)
print("primes up to", N)
print(join(", ", found))
print("count:", len(found))
