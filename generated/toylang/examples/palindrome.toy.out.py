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

def is_palindrome(s):
    clean = lower(replace(s, " ", ""))
    i = 0
    j = (len(clean) - 1)
    while _toy_truthy((i < j)):
        if _toy_truthy((get(clean, i) != get(clean, j))):
            return False
        i = (i + 1)
        j = (j - 1)
    return True
tests = list("racecar", "hello", "A man a plan a canal Panama", "step on no pets", "almost")
i = 0
while _toy_truthy((i < len(tests))):
    s = get(tests, i)
    if _toy_truthy(is_palindrome(s)):
        print(s, "->  palindrome")
    else:
        print(s, "->  not")
    i = (i + 1)
