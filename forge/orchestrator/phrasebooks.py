"""Pre-baked natural-language phrasebooks.

Each phrasebook is a sentence-template dict that fits the
`customization.natural_language` schema. Pick one from the GUI and the
generator emits a Lark grammar that accepts those exact phrases.

Each template uses `<name>`, `<value>`, `<cond>`, `<body>`, `<else>`,
`<params>`, `<args>` as syntactic slots. Other text is literal.

Adding a new phrasebook: add a key here, list it in the GUI's preset
picker, and the rest of the pipeline picks it up automatically.
"""
from __future__ import annotations


PHRASEBOOKS: dict[str, dict[str, str]] = {
    "english_storybook": {
        "var_decl":    "set <name> to <value>.",
        "func_def":    "to <name> with <params> do <body>.",
        "if_stmt":     "if <cond> then <body> otherwise <else>.",
        "while_stmt":  "while <cond> repeat <body>.",
        "return_stmt": "give back <value>.",
        "print_form":  "say <args>",
        "true_word":   "yes",
        "false_word":  "no",
        "null_word":   "nothing",
        "and_word":    "and",
        "or_word":     "or",
        "not_word":    "not",
    },
    "shakespeare": {
        "var_decl":    "let <name> be <value>.",
        "func_def":    "summon <name> with <params> thus <body>.",
        "if_stmt":     "perchance <cond> then <body> otherwise <else>.",
        "while_stmt":  "whilst <cond> proceed <body>.",
        "return_stmt": "yield <value>.",
        "print_form":  "speak <args>",
        "true_word":   "verily",
        "false_word":  "naught",
        "null_word":   "nothing",
        "and_word":    "and",
        "or_word":     "or",
        "not_word":    "nay",
    },
    "child_speak": {
        "var_decl":    "make <name> equal <value>.",
        "func_def":    "the way to <name> with <params> is <body>.",
        "if_stmt":     "when <cond> do <body> else <else>.",
        "while_stmt":  "keep doing <body> while <cond>.",
        "return_stmt": "the answer is <value>.",
        "print_form":  "tell <args>",
        "true_word":   "true",
        "false_word":  "false",
        "null_word":   "nope",
        "and_word":    "and",
        "or_word":     "or",
        "not_word":    "not",
    },
    "ritual": {
        "var_decl":    "let it be known that <name> is <value>.",
        "func_def":    "to invoke <name> upon <params> one must <body>.",
        "if_stmt":     "should <cond> hold then <body> else <else>.",
        "while_stmt":  "as long as <cond> persists, <body>.",
        "return_stmt": "the result, henceforth, is <value>.",
        "print_form":  "proclaim <args>",
        "true_word":   "verum",
        "false_word":  "falsum",
        "null_word":   "void",
        "and_word":    "and",
        "or_word":     "or",
        "not_word":    "not",
    },
}


def list_phrasebooks() -> list[dict]:
    """Compact listing for the GUI dropdown."""
    return [
        {"key": k, "preview": _preview(v)} for k, v in PHRASEBOOKS.items()
    ]


def _preview(book: dict[str, str]) -> str:
    """One-line example using a few slots filled in."""
    var = book.get("var_decl", "var <name> = <value>;")
    return (var
            .replace("<name>", "greeting")
            .replace("<value>", '"hello"')
            .strip())


def get_phrasebook(key: str | None) -> dict[str, str]:
    if not key:
        return {}
    return dict(PHRASEBOOKS.get(key, {}))
