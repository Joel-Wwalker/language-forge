"""prologlang runtime — terms, unification, resolution engine.

This is the load-bearing file. The prologlang->Python codegen emits
a `from slot_lgc_009.runtime import (...)` prelude that pulls in:
  - Term classes (Var, Atom, Num, Compound)
  - The substitution-walking primitive (walk)
  - The unification function (unify)
  - The knowledge base (KnowledgeBase) and the solver (solve)
  - Print helpers used by `?-` directive emission

Conventions:
  - Var carries both a source name (for pretty-printing) and a unique
    integer id (for substitution lookup). Two Vars with different ids
    are different variables even if they share a name — this matters
    when the same clause is used multiple times in a proof tree.
  - Substitutions are flat dicts `{var_id: bound_term}`. Walk follows
    chains through the dict. Unify returns a fresh extended dict on
    success, None on failure (no mutation; the simplicity costs some
    speed but makes backtracking trivial — old dicts are just dropped).
  - Solve is a generator that yields each successful substitution.
    Backtracking is implicit: the consumer calls next() and the
    generator resumes after its last yield, advancing to the next
    clause / next member match / etc.
  - Built-in predicates live in stdlib.register_builtins(kb); see that
    module for the dispatch table.

See LOGICLANG_DESIGN.md §2-§5 for the full design.
"""
from __future__ import annotations

import sys
from typing import Generator, Optional


# ---------------------------------------------------------------------------
# Term representation
# ---------------------------------------------------------------------------
#
# Four kinds of terms:
#   - Var    : a variable, identified by (name, id). The id is the lookup
#              key in substitutions; the name is for pretty-printing.
#   - Atom   : a symbolic constant. `tom`, `[]`, `foo_bar`.
#   - Num    : an integer or float literal.
#   - Compound: functor name + list of argument terms. The compound
#              `parent(tom, bob)` has functor "parent" and args
#              `[Atom("tom"), Atom("bob")]`.
#
# Lists are represented via the cons functor `.` — `[1, 2, 3]` is
# `Compound(".", [Num(1), Compound(".", [Num(2), Compound(".", [Num(3), Atom("[]")])])])`.
# Helper constructors below (NIL, make_list, make_cons) keep the
# codegen and stdlib readable.


class Var:
    """A Prolog variable.

    `name` is for pretty-printing (e.g. "X" in user source). `id` is the
    unique integer used as the key in substitutions. Two Vars share an
    identity iff their ids match.
    """
    __slots__ = ("name", "id")

    def __init__(self, name: str, id: int):
        self.name = name
        self.id = id

    def __repr__(self):
        # Anonymous variables (from `_`) get auto-named at parse time
        # like `_G42`; keep the var's own name for repr.
        return f"Var({self.name!r}, {self.id})"


class Atom:
    """A Prolog atom — a symbolic constant. Equality is name-based."""
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Atom) and self.name == other.name

    def __hash__(self):
        return hash(("Atom", self.name))

    def __repr__(self):
        return f"Atom({self.name!r})"


class Num:
    """A Prolog number — int or float. Equality is value-based."""
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, Num) and self.value == other.value

    def __hash__(self):
        return hash(("Num", self.value))

    def __repr__(self):
        return f"Num({self.value!r})"


class Compound:
    """A compound term: functor + arguments. Equality is structural.

    The functor + arity (length of args) is the predicate identity for
    knowledge-base lookup. `parent/2` and `parent/3` are different
    predicates even though they share a functor.
    """
    __slots__ = ("functor", "args")

    def __init__(self, functor: str, args: list):
        self.functor = functor
        self.args = args

    def __eq__(self, other):
        return (
            isinstance(other, Compound)
            and self.functor == other.functor
            and self.args == other.args
        )

    def __hash__(self):
        return hash(("Compound", self.functor, tuple(self.args)))

    def __repr__(self):
        return f"Compound({self.functor!r}, {self.args!r})"


# The empty list atom. Reused everywhere so we can use `is` checks
# alongside equality (Atom's __eq__ handles both).
NIL = Atom("[]")


def make_list(elements: list) -> "Atom | Compound":
    """Build a Prolog list term from a Python list of terms.

    `[]` -> Atom("[]")
    `[a, b, c]` -> Compound(".", [a, Compound(".", [b, Compound(".", [c, NIL])])])
    """
    result = NIL
    for elem in reversed(elements):
        result = Compound(".", [elem, result])
    return result


def make_partial_list(elements: list, tail) -> "Atom | Compound":
    """Build `[e1, e2, ... | tail]` — a list with a non-nil tail.

    `[h | t]` -> Compound(".", [h, t])
    `[a, b | t]` -> Compound(".", [a, Compound(".", [b, t])])
    """
    result = tail
    for elem in reversed(elements):
        result = Compound(".", [elem, result])
    return result


# ---------------------------------------------------------------------------
# Variable id generator
# ---------------------------------------------------------------------------
#
# Two callers need fresh variable ids:
#   1. The parser, when it sees an anonymous `_` (each becomes a fresh var).
#   2. The solver, when it uses a clause (every var in the clause gets
#      renamed to a fresh id so it doesn't collide with the goal's vars).
#
# A single module-level counter is simplest. It's not thread-safe; the
# Forge orchestrator runs prologlang programs in subprocesses, not threads,
# so this is fine.


class NameGen:
    """Sequential integer id generator for fresh variables."""
    def __init__(self, start: int = 100000):
        # Start high so user-source vars (which get ids 0..N at codegen
        # time) don't collide with runtime-fresh ones.
        self._n = start

    def fresh(self) -> int:
        self._n += 1
        return self._n


# ---------------------------------------------------------------------------
# Walk: follow a variable through the substitution chain
# ---------------------------------------------------------------------------


def walk(term, subs: dict):
    """Resolve a term to its current binding under `subs`.

    Follows chains of variable bindings until we hit a term that isn't
    a bound variable. Idempotent: calling walk(walk(t)) == walk(t).

    Used everywhere before pattern-matching on a term's shape — otherwise
    you'd dispatch on `Var` when the var is actually bound to (say) a
    Compound, and miss the structural unification path.
    """
    while isinstance(term, Var) and term.id in subs:
        term = subs[term.id]
    return term


def walk_deep(term, subs: dict):
    """Recursively walk a term, resolving bindings at every level.

    Used for pretty-printing solutions and for `is/2` arithmetic
    evaluation (which needs fully-ground operands).
    """
    term = walk(term, subs)
    if isinstance(term, Compound):
        return Compound(term.functor, [walk_deep(a, subs) for a in term.args])
    return term


# ---------------------------------------------------------------------------
# Unification
# ---------------------------------------------------------------------------


def unify(t1, t2, subs: dict) -> Optional[dict]:
    """Unify two terms under `subs`.

    Returns the extended substitution on success, or None on failure.
    Returns the SAME dict (no copy) when no new binding was needed —
    callers must not mutate. Returns a NEW dict when extending.

    No occurs check (matches standard Prolog default; see
    LOGICLANG_DESIGN.md §2 / §10 Q5).
    """
    t1 = walk(t1, subs)
    t2 = walk(t2, subs)

    # Same variable: trivially unifies.
    if isinstance(t1, Var) and isinstance(t2, Var) and t1.id == t2.id:
        return subs

    # One side is a variable: bind it to the other.
    if isinstance(t1, Var):
        new_subs = dict(subs)
        new_subs[t1.id] = t2
        return new_subs
    if isinstance(t2, Var):
        new_subs = dict(subs)
        new_subs[t2.id] = t1
        return new_subs

    # Both atoms: names must match.
    if isinstance(t1, Atom) and isinstance(t2, Atom):
        return subs if t1.name == t2.name else None

    # Both numbers: values must match (note: int(1) == float(1.0) per
    # Python's equality, which matches Prolog's =:= but not == — we use
    # value equality here because terms with structurally-equal Num
    # values should unify).
    if isinstance(t1, Num) and isinstance(t2, Num):
        return subs if t1.value == t2.value else None

    # Both compounds: functor + arity must match, then recursively unify
    # corresponding args.
    if isinstance(t1, Compound) and isinstance(t2, Compound):
        if t1.functor != t2.functor or len(t1.args) != len(t2.args):
            return None
        for a, b in zip(t1.args, t2.args):
            subs = unify(a, b, subs)
            if subs is None:
                return None
        return subs

    # Type mismatch (Atom vs Num, etc.): fail.
    return None


# ---------------------------------------------------------------------------
# Fresh-rename a clause for each use
# ---------------------------------------------------------------------------
#
# When the solver uses a clause to resolve a goal, every variable in the
# clause must be renamed to fresh ids. Otherwise, two simultaneous uses
# of the same clause (think: recursive predicate where the recursive call
# is just another use of the same clause) would share variables and
# unify incorrectly.


def rename_term(term, mapping: dict, name_gen: NameGen):
    """Return a fresh copy of `term` with every Var renamed via `mapping`.

    `mapping` is the per-clause-use rename table: `{old_id: new_var}`.
    Reuses the same fresh Var for repeated occurrences of the same
    original var within the clause.
    """
    if isinstance(term, Var):
        if term.id not in mapping:
            mapping[term.id] = Var(term.name, name_gen.fresh())
        return mapping[term.id]
    if isinstance(term, Compound):
        return Compound(term.functor, [rename_term(a, mapping, name_gen)
                                       for a in term.args])
    # Atom / Num are immutable values; share them.
    return term


def rename_clause(head, body: list, name_gen: NameGen):
    """Rename all variables in a clause (head + body goals) to fresh ids.

    Returns a (new_head, new_body) pair. The mapping is per-call, so
    each clause use is independent.
    """
    mapping: dict[int, Var] = {}
    new_head = rename_term(head, mapping, name_gen)
    new_body = [rename_term(g, mapping, name_gen) for g in body]
    return new_head, new_body


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


class KnowledgeBase:
    """The set of clauses (facts + rules) the program can prove against.

    Clauses are indexed by (functor, arity) for O(1) lookup of candidate
    clauses given a goal. v1 does not implement first-argument indexing
    (the next standard optimization) — none of the canonical tests need it.

    The KB also owns:
      - name_gen: hands out fresh variable ids for clause renaming.
      - builtins: dispatch table for built-in predicates (populated by
        stdlib.register_builtins).
    """

    def __init__(self):
        self._clauses: dict[tuple, list] = {}
        self.name_gen = NameGen()
        self.builtins: dict[tuple, callable] = {}

    def add_clause(self, head, body: list) -> None:
        """Insert a clause. `body=[]` for facts, list of goals for rules.

        The head is a Compound or an Atom (nullary predicate). Indexing
        normalizes both into the (functor, arity) key.
        """
        if isinstance(head, Atom):
            key = (head.name, 0)
        elif isinstance(head, Compound):
            key = (head.functor, len(head.args))
        else:
            raise TypeError(f"clause head must be Atom or Compound, got {type(head).__name__}")
        self._clauses.setdefault(key, []).append((head, body))

    def clauses_for(self, goal) -> list:
        """Return the list of (head, body) clauses for goals matching this term.

        Returns an empty list if no clauses are defined for this
        (functor, arity). Note: returns the list directly (caller
        doesn't mutate); the solver iterates it.
        """
        if isinstance(goal, Compound):
            return self._clauses.get((goal.functor, len(goal.args)), [])
        if isinstance(goal, Atom):
            return self._clauses.get((goal.name, 0), [])
        return []

    def register_builtin(self, functor: str, arity: int, impl) -> None:
        """Register a built-in predicate. `impl` is a callable:
            impl(args, rest, subs, kb) -> Generator[dict, None, None]
        yielding each successful substitution.
        """
        self.builtins[(functor, arity)] = impl

    def is_builtin(self, goal) -> bool:
        if isinstance(goal, Compound):
            return (goal.functor, len(goal.args)) in self.builtins
        if isinstance(goal, Atom):
            return (goal.name, 0) in self.builtins
        return False

    def get_builtin(self, goal):
        if isinstance(goal, Compound):
            return self.builtins.get((goal.functor, len(goal.args)))
        if isinstance(goal, Atom):
            return self.builtins.get((goal.name, 0))
        return None


# ---------------------------------------------------------------------------
# Solver — depth-first search with chronological backtracking
# ---------------------------------------------------------------------------


def solve(goals: list, subs: dict, kb: KnowledgeBase) -> Generator[dict, None, None]:
    """Solve a list of goals under `subs` against knowledge base `kb`.

    Yields each substitution that satisfies all goals, in DFS order
    (clauses tried in insertion order; left-to-right within a body).

    Backtracking is implicit: when the consumer asks for the next
    solution, the generator resumes after the last yield, advancing
    the clause-iteration loop (or the non-deterministic-builtin's
    internal loop) to the next alternative.
    """
    if not goals:
        # All goals satisfied. Yield the current substitution.
        yield subs
        return

    goal, *rest = goals
    goal = walk(goal, subs)

    # Built-in dispatch: if the goal's (functor, arity) is registered as
    # a built-in, the builtin's impl yields each success.
    if kb.is_builtin(goal):
        impl = kb.get_builtin(goal)
        # Extract args for compound; for nullary atoms, args is empty.
        args = goal.args if isinstance(goal, Compound) else []
        yield from impl(args, rest, subs, kb)
        return

    # User-defined clause dispatch.
    candidates = kb.clauses_for(goal)
    if not candidates:
        # No clauses for this predicate — fail silently (matches standard
        # Prolog with `unknown=fail` flag; we don't error).
        return

    for clause_head, clause_body in candidates:
        new_head, new_body = rename_clause(clause_head, clause_body, kb.name_gen)
        new_subs = unify(goal, new_head, subs)
        if new_subs is None:
            continue
        # Solve the renamed body, then continue with `rest`.
        yield from solve(new_body + rest, new_subs, kb)


# ---------------------------------------------------------------------------
# Pretty-printing
# ---------------------------------------------------------------------------
#
# Used for the canonical Prolog output format. Bindings are walked deeply
# so any nested variables are resolved before printing.


def term_to_string(term, subs: Optional[dict] = None, *,
                   quote_atoms: bool = True) -> str:
    """Format a term in Prolog form for output.

    If `subs` is provided, walks bindings before printing. Lists print
    in `[a, b, c]` form (or `[a, b | T]` for partial lists).

    `quote_atoms=True` (default): atoms with spaces / special chars get
    single-quoted, suitable for `write_canonical/1`-style output where
    the result should be re-parseable Prolog source.

    `quote_atoms=False`: atoms print bare, matching standard Prolog's
    `write/1` semantics (`write('Hello, World!')` outputs `Hello, World!`
    not `'Hello, World!'`).
    """
    if subs is not None:
        term = walk(term, subs)

    if isinstance(term, Var):
        # Pretty-name for unbound vars: use the original source name
        # (e.g. "X") if present, otherwise an auto-generated "_NNN".
        if term.name and term.name != "_":
            return f"_{term.id}" if term.name.startswith("_") else f"_{term.name}{term.id}"
        return f"_G{term.id}"

    if isinstance(term, Atom):
        return _quote_atom_if_needed(term.name) if quote_atoms else term.name

    if isinstance(term, Num):
        v = term.value
        # Print floats with at least one decimal; ints as ints. Avoids
        # Prolog's "is this a float or an int" ambiguity in output.
        if isinstance(v, float):
            # Keep Python's float-str (which handles 3.14, 1e10, etc.)
            return repr(v)
        return str(v)

    if isinstance(term, Compound):
        # List rendering: walk the cons chain into a flat representation.
        if term.functor == "." and len(term.args) == 2:
            return _list_to_string(term, subs, quote_atoms=quote_atoms)
        # General compound.
        functor = _quote_atom_if_needed(term.functor) if quote_atoms else term.functor
        args_str = ", ".join(term_to_string(a, subs, quote_atoms=quote_atoms)
                             for a in term.args)
        return f"{functor}({args_str})"

    # Fallback — shouldn't happen on well-formed terms.
    return repr(term)


def _list_to_string(term, subs: Optional[dict], *, quote_atoms: bool = True) -> str:
    """Render a cons-chain as `[a, b, c]` or `[a, b | T]`."""
    elements = []
    current = term
    if subs is not None:
        current = walk(current, subs)
    while (isinstance(current, Compound) and current.functor == "."
           and len(current.args) == 2):
        elements.append(term_to_string(current.args[0], subs,
                                       quote_atoms=quote_atoms))
        current = current.args[1]
        if subs is not None:
            current = walk(current, subs)
    # Reached the end of the list — either NIL or a partial-list tail.
    if isinstance(current, Atom) and current.name == "[]":
        return "[" + ", ".join(elements) + "]"
    # Improper list / partial list: render the tail after `|`.
    tail = term_to_string(current, subs, quote_atoms=quote_atoms)
    return "[" + ", ".join(elements) + " | " + tail + "]"


def _quote_atom_if_needed(name: str) -> str:
    """Single-quote an atom name if it contains special chars or doesn't
    start with lowercase. The empty-list atom `[]` and other built-in
    atoms with brackets/punctuation print bare."""
    if not name:
        return "''"
    # The empty list atom and the cons functor render unchanged.
    if name == "[]":
        return "[]"
    # Atoms that are all lowercase-letters/digits/underscores and start
    # with a lowercase letter print bare.
    if name[0].islower() and all(c.isalnum() or c == "_" for c in name):
        return name
    # Otherwise quote and escape internal quotes.
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


# ---------------------------------------------------------------------------
# Query-result printing helpers (called from generated Python)
# ---------------------------------------------------------------------------


def print_solutions(gen, free_vars: list) -> None:
    """Run a directive's solution generator once and let side-effects
    (write/1, nl/0 inside the goal) produce the output.

    v1 batch-mode semantics: top-level directives `:- Goal.` and
    `?- Goal.` are synonymous (see LOGICLANG_DESIGN.md §10 Q8) and
    are treated as run-once: consume the FIRST solution, stop. The
    user controls output via explicit `write/1` calls in the goal.

    The `free_vars` parameter is preserved for API compatibility but
    not used in v1 — bindings aren't auto-printed. (Real Prolog's
    interactive prompt does this; batch-mode programs don't.)

    If the goal fails on every alternative, we print nothing — same
    as a directive that just silently fails. The user's explicit
    output is what they see.
    """
    for _ in gen:
        return  # consumed first solution; commit and stop


def write_term(term, subs: dict) -> None:
    """Implementation of write/1 — print the term, no newline.

    Atoms print bare (no surrounding quotes) — matches standard
    Prolog's write/1 semantics. For canonical (re-parseable) output
    the user would use `write_canonical/1`, which v1 doesn't yet
    ship as a separate predicate.
    """
    sys.stdout.write(term_to_string(term, subs, quote_atoms=False))


def write_nl() -> None:
    """Implementation of nl/0 — print a newline."""
    sys.stdout.write("\n")


# Ensure deep recursion works for the canonical tests' factorial(7) etc.
# Done once at module load; codegen's prelude doesn't have to repeat it.
sys.setrecursionlimit(10000)

# === FORGE_STDLIB_SHIM_BEGIN ===
# Auto-applied by Forge: deterministic stdlib helpers the codegen
# PRELUDE imports. Do not edit between BEGIN/END markers; rerun the
# generator to refresh.
import sys as _shim_sys
import builtins as _shim_builtins

def toy_input(prompt=""):
    return _shim_builtins.input(prompt)

def toy_list(*items):
    """`list(1, 2, 3)` returns a fresh Python list."""
    return _shim_builtins.list(items)

def toy_get(coll, k, default=None):
    """Read element by index (list, string) or key (dict). Returns default if absent."""
    if isinstance(coll, _shim_builtins.list):
        if isinstance(k, int) and 0 <= k < _shim_builtins.len(coll):
            return coll[k]
        return default
    if isinstance(coll, dict):
        return coll.get(k, default)
    if isinstance(coll, str):
        if isinstance(k, int) and 0 <= k < _shim_builtins.len(coll):
            return coll[k]
        return default
    raise TypeError("get(): unsupported type " + type(coll).__name__)

def toy_set(coll, k, v):
    """Mutate element by index or key. Returns the collection."""
    if isinstance(coll, _shim_builtins.list):
        if not isinstance(k, int):
            raise TypeError("set(): list keys must be integers")
        while _shim_builtins.len(coll) <= k:
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
    """`dict("a", 1, "b", 2)` returns {"a": 1, "b": 2}. dict() returns {}."""
    if _shim_builtins.len(pairs) % 2 != 0:
        raise ValueError("dict() needs an even number of arguments")
    return _shim_builtins.dict(_shim_builtins.zip(pairs[0::2], pairs[1::2]))

def toy_has(coll, k):
    if isinstance(coll, dict):
        return k in coll
    if isinstance(coll, _shim_builtins.list):
        return isinstance(k, int) and 0 <= k < _shim_builtins.len(coll)
    if isinstance(coll, str):
        return k in coll
    return False

def toy_keys(d):
    return _shim_builtins.list(d.keys())

def toy_range(a, b=None):
    if b is None:
        return _shim_builtins.list(_shim_builtins.range(a))
    return _shim_builtins.list(_shim_builtins.range(a, b))

def toy_split(s, sep):
    return s.split(sep)

def toy_join(sep, lst):
    parts = []
    for x in lst:
        if x is True:
            parts.append("true")
        elif x is False:
            parts.append("false")
        elif x is None:
            parts.append("null")
        else:
            parts.append(_shim_builtins.str(x))
    return sep.join(parts)

def toy_upper(s):
    return s.upper()

def toy_lower(s):
    return s.lower()

def toy_replace(s, old, new):
    return s.replace(old, new)

def toy_int(v):
    return _shim_builtins.int(v)

def toy_float(v):
    return _shim_builtins.float(v)

def toy_read_file(path):
    with _shim_builtins.open(path, "r", encoding="utf-8") as _f:
        return _f.read()

def toy_write_file(path, content):
    with _shim_builtins.open(path, "w", encoding="utf-8") as _f:
        _f.write(content)
    return None

def toy_argv():
    return _shim_builtins.list(_shim_sys.argv[1:])

def toy_exit(code=0):
    _shim_sys.exit(_shim_builtins.int(code))

# === FORGE_STDLIB_SHIM_END ===
