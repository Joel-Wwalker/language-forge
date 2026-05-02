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

width = 60
height = 22
max_iter = 30
y = 0
while _toy_truthy((y < height)):
    row = ""
    x = 0
    while _toy_truthy((x < width)):
        cx = ((-2.0) + ((3.0 * x) / width))
        cy = ((-1.2) + ((2.4 * y) / height))
        zx = 0.0
        zy = 0.0
        i = 0
        while _toy_truthy((i < max_iter)):
            if _toy_truthy((((zx * zx) + (zy * zy)) >= 4.0)):
                i = max_iter
            else:
                tmp = (((zx * zx) - (zy * zy)) + cx)
                zy = (((2.0 * zx) * zy) + cy)
                zx = tmp
                i = (i + 1)
        if _toy_truthy((((zx * zx) + (zy * zy)) < 4.0)):
            row = (row + "#")
        else:
            row = (row + " ")
        x = (x + 1)
    print(row)
    y = (y + 1)
