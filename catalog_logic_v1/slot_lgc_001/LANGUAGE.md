# slot_lgc_001 language reference

Family: `logic_like`.
Typing: `dynamic`.
Memory: `host_gc`.

## Lexical syntax

- Line comments: `%`
- Block comments: `/* ... */`
- Statement terminator: `'.'`
- Block style: clause-based

## Function definition

```
double(X, Y) :- Y is X * 2.
```

## Variable declaration

```
X = 10
```

## Booleans + null

- True: `true`
- False: `false`
- Null: `[]`

## Operators

- **arithmetic**: `+`, `-`, `*`, `/`, `//`, `mod`, `**`
- **comparison**: `=:=`, `=\=`, `<`, `>`, `=<`, `>=`
- **logical**: `,`, `;`, `\+`

## Stdlib

- `print` — Print to stdout with newline.
- `input` — Read one line from stdin (no trailing newline).
- `list` — Build a list from arguments. `list(1, 2, 3)`.
- `len` — Length of a string, list, or dict.
- `get` — Read element by index (list) or key (dict). Returns null if absent.
- `set` — Mutate element by index or key. Returns the collection.
- `push` — Append to the end of a list. Returns the list.
- `pop` — Remove and return the last element of a list.
- `dict` — Build a dict from alternating key, value arguments.
- `has` — True if a dict has the key, or list has the index.
- `keys` — List of keys in a dict (insertion order).
- `range` — List of integers. `range(n)` is 0..n-1; `range(a, b)` is a..b-1.
- `str` — Convert any value to its printable string.
- `split` — Split a string on a separator, return list of pieces.
- `join` — Join a list of strings with a separator.
- `upper` — Uppercase a string.
- `lower` — Lowercase a string.
- `replace` — Replace every occurrence of `old` with `new` in `s`.
- `int` — Convert string or float to int.
- `float` — Convert string or int to float.
- `read_file` — Read a UTF-8 text file as a string.
- `write_file` — Write a string to a file (overwrites). Returns null.
- `argv` — List of command-line arguments after the program name.
- `exit` — Exit the program with an integer status code.
