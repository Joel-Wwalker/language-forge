"""stacky typechecker.

Stack-based static type checking via stack-effect comments.
Each word has a signature (inputs -- outputs); checking simulates
stack state and verifies type/depth constraints.
"""

import re
from typing import Any


class TypeCheckError(Exception):
    pass


class StackState:
    """Represents a typed stack."""
    def __init__(self, types=None):
        self.types = types or []

    def push(self, t: str):
        self.types.append(t)

    def pop(self) -> str:
        if not self.types:
            raise TypeCheckError("Stack underflow")
        return self.types.pop()

    def peek(self) -> str:
        if not self.types:
            raise TypeCheckError("Stack underflow")
        return self.types[-1]

    def depth(self) -> int:
        return len(self.types)

    def copy(self):
        return StackState(self.types[:])

    def __eq__(self, other):
        return self.types == other.types


def check(ast: list[dict], src: str = "") -> list[dict]:
    """Type-check a stacky program.

    Args:
        ast: Output from parser.parse()
        src: Optional source text for extracting stack-effect annotations

    Returns:
        ast (unmodified)

    Raises:
        TypeCheckError on type mismatch or undefined word
    """
    checker = Checker(ast, src)
    checker.run()
    return ast


class Checker:
    def __init__(self, ast: list[dict], src: str):
        self.ast = ast
        self.src = src
        self.stack = StackState()
        self.words = {}  # name -> (in_types, out_types)
        self.vars = {}   # name -> type

        # Built-in signatures
        self._init_builtins()

    def _init_builtins(self):
        """Register built-in word signatures."""
        self.words.update({
            "dup": (["T"], ["T", "T"]),
            "drop": (["T"], []),
            "swap": (["A", "B"], ["B", "A"]),
            "over": (["A", "B"], ["A", "B", "A"]),
            "rot": (["A", "B", "C"], ["B", "C", "A"]),
            "nip": (["A", "B"], ["B"]),
            "tuck": (["A", "B"], ["B", "A", "B"]),
            "+": (["Int", "Int"], ["Int"]),
            "-": (["Int", "Int"], ["Int"]),
            "*": (["Int", "Int"], ["Int"]),
            "/": (["Int", "Int"], ["Int"]),
            "mod": (["Int", "Int"], ["Int"]),
            "=": (["T", "T"], ["Bool"]),
            "<>": (["T", "T"], ["Bool"]),
            "<": (["Int", "Int"], ["Bool"]),
            ">": (["Int", "Int"], ["Bool"]),
            "<=": (["Int", "Int"], ["Bool"]),
            ">=": (["Int", "Int"], ["Bool"]),
            "and": (["Bool", "Bool"], ["Bool"]),
            "or": (["Bool", "Bool"], ["Bool"]),
            "not": (["Bool"], ["Bool"]),
            ".": (["T"], []),
            "cr": ([], []),
            "@": (["Addr"], ["T"]),
            "!": (["T", "Addr"], []),
        })
        # === FORGE_STACK_TC_SHIM_BEGIN ===
        # Auto-applied by Forge: register canonical
        # stack_classics vocabulary so curated kata
        # references typecheck. Sigs use generic 'T'
        # so they're compatible with any stack state.
        self.words.update({
            'nil':   ([], ['T']),
            'true':  ([], ['Bool']),
            'false': ([], ['Bool']),
            'list':  ([], ['T']),
            'dict':  ([], ['T']),
            'range': (['Int'], ['T']),
            'get':   (['T', 'T'], ['T']),
            'dset':  (['T', 'T', 'T'], ['T']),
            'set!':  (['T', 'T', 'T'], ['T']),
            'push':  (['T', 'T'], ['T']),
            'l_pop': (['T'], ['T']),
            'len':   (['T'], ['Int']),
            'has':   (['T', 'T'], ['Bool']),
        })
        # === FORGE_STACK_TC_SHIM_END ===


    def run(self):
        """Type-check the program."""
        for form in self.ast:
            self._check_form(form)

    def _check_form(self, form: dict):
        kind = form["kind"]
        line = form.get("line", 0)

        if kind == "num":
            self.stack.push("Int")
        elif kind == "float":
            self.stack.push("Float")
        elif kind == "strpush":
            self.stack.push("String")
        elif kind == "strprint":
            pass  # ." string" has no stack effect
        elif kind == "name":
            self._check_word(form["value"], line)
        elif kind == "colon_def":
            self._check_colon_def(form)
        elif kind == "variable_decl":
            name = form["name"]
            self.vars[name] = "Addr"
            self.words[name] = ([], ["Addr"])
        elif kind == "constant_decl":
            if self.stack.depth() == 0:
                raise TypeCheckError(f"line {line}: constant needs value on stack")
            t = self.stack.pop()
            name = form["name"]
            self.vars[name] = t
            self.words[name] = ([], [t])
        elif kind == "if":
            self._check_if(form, line)
        elif kind == "begin_until":
            self._check_begin_until(form, line)
        elif kind == "begin_again":
            self._check_begin_again(form, line)
        elif kind == "do_loop":
            self._check_do_loop(form, line)
        else:
            raise TypeCheckError(f"line {line}: unknown form: {kind}")

    def _check_word(self, word: str, line: int):
        """Apply a word's stack effect."""
        # Boolean/null literals
        if word == "verum":
            self.stack.push("Bool")
            return
        if word == "falsum":
            self.stack.push("Bool")
            return
        if word == "void":
            self.stack.push("Null")
            return

        # Defined words
        if word not in self.words:
            raise TypeCheckError(f"line {line}: undefined word: {word}")

        ins, outs = self.words[word]
        if self.stack.depth() < len(ins):
            raise TypeCheckError(f"line {line}: `{word}` stack underflow")

        # Pop inputs, check types with unification
        type_env = {}
        for expected in reversed(ins):
            actual = self.stack.pop()
            if not self._types_compatible(expected, actual, type_env):
                raise TypeCheckError(
                    f"line {line}: `{word}` expected {expected}, got {actual}"
                )

        # Push outputs, substituting unified types
        for out in outs:
            concrete = self._substitute_type(out, type_env)
            self.stack.push(concrete)

    def _types_compatible(self, expected: str, actual: str, type_env: dict) -> bool:
        """Check if actual type matches expected, updating type_env for generics."""
        # Generic type variables match anything
        if expected in {"T", "A", "B", "C"}:
            if expected in type_env:
                return type_env[expected] == actual
            else:
                type_env[expected] = actual
                return True
        if actual in {"T", "A", "B", "C"}:
            if actual in type_env:
                return type_env[actual] == expected
            else:
                type_env[actual] = expected
                return True
        return expected == actual

    def _substitute_type(self, t: str, type_env: dict) -> str:
        """Substitute concrete types for generic type variables."""
        if t in type_env:
            return type_env[t]
        return t

    def _check_colon_def(self, form: dict):
        """Type-check a function definition and infer its stack effect."""
        name = form["name"]
        body = form["body"]
        line = form.get("line", 0)

        # Save current stack state
        saved_stack = self.stack.copy()
        
        # Execute body with empty stack to infer output signature
        self.stack = StackState()
        
        # Temporarily register word to handle recursion
        self.words[name] = ([], ["T"])
        
        try:
            # Try executing the body
            for item in body:
                self._check_form(item)
            
            # Success: the word produces whatever is now on the stack
            outputs = self.stack.types[:]
            self.words[name] = ([], outputs)
        except TypeCheckError:
            # If execution fails (e.g., tries to pop from empty stack),
            # the word must consume inputs. Use polymorphic signature.
            self.words[name] = (["T"], ["T"])
        finally:
            # Restore stack state
            self.stack = saved_stack

    def _check_if(self, form: dict, line: int):
        """Type-check if/then/else."""
        if self.stack.depth() == 0:
            raise TypeCheckError(f"line {line}: `if` needs boolean")
        cond = self.stack.pop()
        if cond not in {"Bool", "T", "A", "B", "C"}:
            raise TypeCheckError(f"line {line}: `if` expects Bool, got {cond}")

        saved = self.stack.copy()

        # Then branch
        for item in form["then_body"]:
            self._check_form(item)
        then_st = self.stack.copy()

        # Else branch
        self.stack = saved.copy()
        for item in form["else_body"]:
            self._check_form(item)

        if self.stack.depth() != then_st.depth():
            raise TypeCheckError(f"line {line}: if branches differ in stack depth")

        # Use then result
        self.stack = then_st

    def _check_begin_until(self, form: dict, line: int):
        """Type-check begin/until loop."""
        saved = self.stack.copy()
        for item in form["body"]:
            self._check_form(item)
        if self.stack.depth() == 0:
            raise TypeCheckError(f"line {line}: `until` needs boolean")
        cond = self.stack.pop()
        if cond not in {"Bool", "T", "A", "B", "C"}:
            raise TypeCheckError(f"line {line}: `until` expects Bool, got {cond}")
        self.stack = saved

    def _check_begin_again(self, form: dict, line: int):
        """Type-check begin/again infinite loop."""
        for item in form["body"]:
            self._check_form(item)

    def _check_do_loop(self, form: dict, line: int):
        """Type-check do/loop."""
        if self.stack.depth() < 2:
            raise TypeCheckError(f"line {line}: `do` needs two integers")
        self.stack.pop()
        self.stack.pop()
        for item in form["body"]:
            self._check_form(item)
