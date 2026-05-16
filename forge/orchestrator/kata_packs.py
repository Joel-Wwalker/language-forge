"""Curated kata packs. Hand-written, deterministic, no LLM call.

These supplement the dynamic kata generation with known-good problems
(LeetCode-style classics). Each kata's `reference_solution` is verified
to compile and produce the documented `expected` output on the standard
toylang reference compiler. When loaded onto a non-toylang c_like
language, the self-validation step in `katas.generate_katas` (or its
deterministic cousin `validate_pack`) will catch any keyword-spelling
or stdlib coverage mismatches and drop just those.

Linked-list and binary-tree problems represent nodes as nested dicts:
  - linked list:  `dict("val", v, "next", node_or_null)`
  - binary tree:  `dict("val", v, "left", left_or_null, "right", right_or_null)`

This avoids needing user-defined types (which we don't generate yet)
while still letting the problems exercise the relevant algorithms.
"""
from __future__ import annotations

# Each entry is a complete kata dict. The c_like reference solutions use
# only stdlib functions every healthy generated language has: print, len,
# get, set, push, pop, list, dict, has, keys, range, str, split, join,
# upper, lower, replace, int, float.

CLASSICS_C_LIKE: list[dict] = [
    {
        "id": "two_sum",
        "title": "Two Sum",
        "difficulty": "easy",
        "problem": (
            "Given a list of integers `nums` and an integer `target`, return "
            "the two indices i, j (i < j) such that nums[i] + nums[j] == target. "
            "Assume exactly one solution exists. Return them as list(i, j)."
        ),
        "function_name": "two_sum",
        "starter_code": "func two_sum(nums, target) {\n    // your code\n}\n",
        "reference_solution": (
            "func two_sum(nums, target) {\n"
            "    var seen = dict();\n"
            "    var i = 0;\n"
            "    while (i < len(nums)) {\n"
            "        var n = get(nums, i);\n"
            "        var need = target - n;\n"
            "        if (has(seen, need)) {\n"
            "            return list(get(seen, need), i);\n"
            "        }\n"
            "        set(seen, n, i);\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return list();\n"
            "}\n"
        ),
        "tests": [
            {"call": "two_sum(list(2, 7, 11, 15), 9)", "expected": "[0, 1]"},
            {"call": "two_sum(list(3, 2, 4), 6)",      "expected": "[1, 2]"},
            {"call": "two_sum(list(3, 3), 6)",         "expected": "[0, 1]"},
            {"call": "two_sum(list(-1, 0, 1), 0)",     "expected": "[0, 2]"},
        ],
    },
    {
        "id": "reverse_list",
        "title": "Reverse a list",
        "difficulty": "easy",
        "problem": "Return a new list with the elements of the input in reverse order.",
        "function_name": "reverse",
        "starter_code": "func reverse(lst) {\n    // your code\n}\n",
        "reference_solution": (
            "func reverse(lst) {\n"
            "    var out = list();\n"
            "    var i = len(lst) - 1;\n"
            "    while (i >= 0) {\n"
            "        push(out, get(lst, i));\n"
            "        i = i - 1;\n"
            "    }\n"
            "    return out;\n"
            "}\n"
        ),
        "tests": [
            {"call": "reverse(list(1, 2, 3))",   "expected": "[3, 2, 1]"},
            {"call": "reverse(list())",          "expected": "[]"},
            {"call": "reverse(list(\"a\"))",     "expected": "[a]"},
            {"call": "reverse(list(1, 1, 2))",   "expected": "[2, 1, 1]"},
        ],
    },
    {
        "id": "valid_parens",
        "title": "Valid parentheses",
        "difficulty": "easy",
        "problem": (
            "Return true if the string contains a balanced sequence of `(`, `)`, "
            "`[`, `]`, `{`, `}`. Empty input is balanced."
        ),
        "function_name": "valid_parens",
        "starter_code": "func valid_parens(s) {\n    // your code\n}\n",
        "reference_solution": (
            "func valid_parens(s) {\n"
            "    var stack = list();\n"
            "    var pairs = dict(\")\", \"(\", \"]\", \"[\", \"}\", \"{\");\n"
            "    var i = 0;\n"
            "    while (i < len(s)) {\n"
            "        var c = get(s, i);\n"
            "        if (c == \"(\" || c == \"[\" || c == \"{\") {\n"
            "            push(stack, c);\n"
            "        } else if (c == \")\" || c == \"]\" || c == \"}\") {\n"
            "            if (len(stack) == 0) { return false; }\n"
            "            var top = pop(stack);\n"
            "            if (top != get(pairs, c)) { return false; }\n"
            "        }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return len(stack) == 0;\n"
            "}\n"
        ),
        "tests": [
            {"call": "valid_parens(\"\")",            "expected": "true"},
            {"call": "valid_parens(\"()\")",          "expected": "true"},
            {"call": "valid_parens(\"()[]{}\")",      "expected": "true"},
            {"call": "valid_parens(\"(]\")",          "expected": "false"},
            {"call": "valid_parens(\"([{}])\")",      "expected": "true"},
            {"call": "valid_parens(\"(((\")",         "expected": "false"},
        ],
    },
    {
        "id": "anagram",
        "title": "Anagram check",
        "difficulty": "easy",
        "problem": (
            "Return true if `a` and `b` are anagrams (same letters, same counts). "
            "Case-insensitive; ignore spaces."
        ),
        "function_name": "is_anagram",
        "starter_code": "func is_anagram(a, b) {\n    // your code\n}\n",
        "reference_solution": (
            "func count_chars(s) {\n"
            "    var s2 = lower(replace(s, \" \", \"\"));\n"
            "    var counts = dict();\n"
            "    var i = 0;\n"
            "    while (i < len(s2)) {\n"
            "        var c = get(s2, i);\n"
            "        if (has(counts, c)) {\n"
            "            set(counts, c, get(counts, c) + 1);\n"
            "        } else {\n"
            "            set(counts, c, 1);\n"
            "        }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return counts;\n"
            "}\n"
            "\n"
            "func is_anagram(a, b) {\n"
            "    var ca = count_chars(a);\n"
            "    var cb = count_chars(b);\n"
            "    if (len(keys(ca)) != len(keys(cb))) { return false; }\n"
            "    var ks = keys(ca);\n"
            "    var i = 0;\n"
            "    while (i < len(ks)) {\n"
            "        var k = get(ks, i);\n"
            "        if (!has(cb, k)) { return false; }\n"
            "        if (get(ca, k) != get(cb, k)) { return false; }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return true;\n"
            "}\n"
        ),
        "tests": [
            {"call": "is_anagram(\"listen\", \"silent\")",          "expected": "true"},
            {"call": "is_anagram(\"hello\", \"world\")",            "expected": "false"},
            {"call": "is_anagram(\"Dormitory\", \"Dirty room\")",   "expected": "true"},
            {"call": "is_anagram(\"a\", \"a\")",                    "expected": "true"},
            {"call": "is_anagram(\"a\", \"b\")",                    "expected": "false"},
        ],
    },
    {
        "id": "max_subarray",
        "title": "Maximum subarray sum (Kadane)",
        "difficulty": "medium",
        "problem": (
            "Return the largest sum of any contiguous subarray. The array is "
            "non-empty. Negative numbers are allowed."
        ),
        "function_name": "max_subarray",
        "starter_code": "func max_subarray(nums) {\n    // your code\n}\n",
        "reference_solution": (
            "func max_subarray(nums) {\n"
            "    var best = get(nums, 0);\n"
            "    var here = get(nums, 0);\n"
            "    var i = 1;\n"
            "    while (i < len(nums)) {\n"
            "        var n = get(nums, i);\n"
            "        if (here + n > n) { here = here + n; } else { here = n; }\n"
            "        if (here > best) { best = here; }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return best;\n"
            "}\n"
        ),
        "tests": [
            {"call": "max_subarray(list(-2, 1, -3, 4, -1, 2, 1, -5, 4))", "expected": "6"},
            {"call": "max_subarray(list(1))",                            "expected": "1"},
            {"call": "max_subarray(list(-1, -2, -3))",                   "expected": "-1"},
            {"call": "max_subarray(list(5, 4, -1, 7, 8))",               "expected": "23"},
        ],
    },
    {
        "id": "move_zeros",
        "title": "Move zeros to end",
        "difficulty": "easy",
        "problem": (
            "Return a new list where all 0s are moved to the end, preserving "
            "the relative order of the non-zero elements."
        ),
        "function_name": "move_zeros",
        "starter_code": "func move_zeros(nums) {\n    // your code\n}\n",
        "reference_solution": (
            "func move_zeros(nums) {\n"
            "    var out = list();\n"
            "    var zeros = 0;\n"
            "    var i = 0;\n"
            "    while (i < len(nums)) {\n"
            "        var n = get(nums, i);\n"
            "        if (n == 0) {\n"
            "            zeros = zeros + 1;\n"
            "        } else {\n"
            "            push(out, n);\n"
            "        }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    var z = 0;\n"
            "    while (z < zeros) { push(out, 0); z = z + 1; }\n"
            "    return out;\n"
            "}\n"
        ),
        "tests": [
            {"call": "move_zeros(list(0, 1, 0, 3, 12))",  "expected": "[1, 3, 12, 0, 0]"},
            {"call": "move_zeros(list(0))",               "expected": "[0]"},
            {"call": "move_zeros(list(1, 2, 3))",         "expected": "[1, 2, 3]"},
            {"call": "move_zeros(list(0, 0, 0))",         "expected": "[0, 0, 0]"},
        ],
    },
    {
        "id": "two_pointer_pair_sum",
        "title": "Two-pointer pair sum (sorted)",
        "difficulty": "medium",
        "problem": (
            "Given a SORTED list of integers and a target, return list(i, j) "
            "(i < j) such that nums[i] + nums[j] == target, or list() if no "
            "such pair exists. Use two pointers."
        ),
        "function_name": "pair_sum_sorted",
        "starter_code": "func pair_sum_sorted(nums, target) {\n    // your code\n}\n",
        "reference_solution": (
            "func pair_sum_sorted(nums, target) {\n"
            "    var lo = 0;\n"
            "    var hi = len(nums) - 1;\n"
            "    while (lo < hi) {\n"
            "        var s = get(nums, lo) + get(nums, hi);\n"
            "        if (s == target) { return list(lo, hi); }\n"
            "        if (s < target) { lo = lo + 1; } else { hi = hi - 1; }\n"
            "    }\n"
            "    return list();\n"
            "}\n"
        ),
        "tests": [
            {"call": "pair_sum_sorted(list(1, 2, 3, 4, 6), 6)", "expected": "[1, 3]"},
            {"call": "pair_sum_sorted(list(2, 7, 11, 15), 9)", "expected": "[0, 1]"},
            {"call": "pair_sum_sorted(list(1, 2, 3), 7)",      "expected": "[]"},
            {"call": "pair_sum_sorted(list(-3, 0, 3), 0)",     "expected": "[0, 2]"},
        ],
    },
    {
        "id": "longest_unique_substring",
        "title": "Longest substring without repeating chars",
        "difficulty": "medium",
        "problem": (
            "Return the LENGTH of the longest substring of `s` that has no "
            "repeated characters. Use a sliding window."
        ),
        "function_name": "longest_unique",
        "starter_code": "func longest_unique(s) {\n    // your code\n}\n",
        "reference_solution": (
            "func longest_unique(s) {\n"
            "    var seen = dict();\n"
            "    var lo = 0;\n"
            "    var best = 0;\n"
            "    var i = 0;\n"
            "    while (i < len(s)) {\n"
            "        var c = get(s, i);\n"
            "        if (has(seen, c)) {\n"
            "            if (get(seen, c) >= lo) { lo = get(seen, c) + 1; }\n"
            "        }\n"
            "        set(seen, c, i);\n"
            "        if (i - lo + 1 > best) { best = i - lo + 1; }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return best;\n"
            "}\n"
        ),
        "tests": [
            {"call": "longest_unique(\"abcabcbb\")", "expected": "3"},
            {"call": "longest_unique(\"bbbbb\")",    "expected": "1"},
            {"call": "longest_unique(\"pwwkew\")",   "expected": "3"},
            {"call": "longest_unique(\"\")",         "expected": "0"},
            {"call": "longest_unique(\"abcdef\")",   "expected": "6"},
        ],
    },
    {
        "id": "best_time_to_buy_sell",
        "title": "Best time to buy and sell stock",
        "difficulty": "easy",
        "problem": (
            "Given a list of daily prices, return the maximum profit from a "
            "single buy + later sell. Return 0 if no profit is possible."
        ),
        "function_name": "max_profit",
        "starter_code": "func max_profit(prices) {\n    // your code\n}\n",
        "reference_solution": (
            "func max_profit(prices) {\n"
            "    if (len(prices) == 0) { return 0; }\n"
            "    var lo = get(prices, 0);\n"
            "    var best = 0;\n"
            "    var i = 1;\n"
            "    while (i < len(prices)) {\n"
            "        var p = get(prices, i);\n"
            "        if (p < lo) { lo = p; }\n"
            "        if (p - lo > best) { best = p - lo; }\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return best;\n"
            "}\n"
        ),
        "tests": [
            {"call": "max_profit(list(7, 1, 5, 3, 6, 4))", "expected": "5"},
            {"call": "max_profit(list(7, 6, 4, 3, 1))",    "expected": "0"},
            {"call": "max_profit(list())",                 "expected": "0"},
            {"call": "max_profit(list(2, 4, 1))",          "expected": "2"},
        ],
    },
    {
        "id": "climb_stairs",
        "title": "Climbing stairs (DP)",
        "difficulty": "easy",
        "problem": (
            "There are n stairs; you can take 1 or 2 steps at a time. Return "
            "the number of distinct ways to reach the top."
        ),
        "function_name": "climb",
        "starter_code": "func climb(n) {\n    // your code\n}\n",
        "reference_solution": (
            "func climb(n) {\n"
            "    if (n <= 2) { return n; }\n"
            "    var a = 1;\n"
            "    var b = 2;\n"
            "    var i = 3;\n"
            "    while (i <= n) {\n"
            "        var c = a + b;\n"
            "        a = b;\n"
            "        b = c;\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return b;\n"
            "}\n"
        ),
        "tests": [
            {"call": "climb(1)",  "expected": "1"},
            {"call": "climb(2)",  "expected": "2"},
            {"call": "climb(3)",  "expected": "3"},
            {"call": "climb(5)",  "expected": "8"},
            {"call": "climb(10)", "expected": "89"},
        ],
    },
    {
        "id": "linked_list_reverse",
        "title": "Reverse a linked list",
        "difficulty": "medium",
        "problem": (
            "Linked-list nodes are dicts: `dict(\"val\", v, \"next\", node_or_null)`. "
            "Given the head, return the new head of the reversed list. Empty "
            "input returns null."
        ),
        "function_name": "reverse_ll",
        # Starter shows the helpers as a (read-only-style) preamble so the
        # user knows they can use to_ll() / ll_to_list() in their solution.
        "starter_code": (
            "// Provided helpers (always available to your solution):\n"
            "//   to_ll(items)     - build a linked list from a list of values\n"
            "//   ll_to_list(head) - convert linked list back to a list\n"
            "\n"
            "func reverse_ll(head) {\n"
            "    // your code\n"
            "}\n"
        ),
        # Helpers are PREPENDED to both the reference (during self-validation)
        # and the user's solution (during check_solution), so test calls like
        # `ll_to_list(reverse_ll(to_ll(...)))` work even when the user only
        # writes `reverse_ll`. Without this separation the tests crashed with
        # "name 'll_to_list' is not defined" on user submissions.
        "helpers": (
            "// Build a linked list from a list of values.\n"
            "func to_ll(items) {\n"
            "    var head = null;\n"
            "    var i = len(items) - 1;\n"
            "    while (i >= 0) {\n"
            "        head = dict(\"val\", get(items, i), \"next\", head);\n"
            "        i = i - 1;\n"
            "    }\n"
            "    return head;\n"
            "}\n"
            "\n"
            "// Convert a linked list back to a list, for printing.\n"
            "func ll_to_list(head) {\n"
            "    var out = list();\n"
            "    while (head != null) {\n"
            "        push(out, get(head, \"val\"));\n"
            "        head = get(head, \"next\");\n"
            "    }\n"
            "    return out;\n"
            "}\n"
        ),
        "reference_solution": (
            "func reverse_ll(head) {\n"
            "    var prev = null;\n"
            "    var curr = head;\n"
            "    while (curr != null) {\n"
            "        var nxt = get(curr, \"next\");\n"
            "        set(curr, \"next\", prev);\n"
            "        prev = curr;\n"
            "        curr = nxt;\n"
            "    }\n"
            "    return prev;\n"
            "}\n"
        ),
        "tests": [
            {"call": "ll_to_list(reverse_ll(to_ll(list(1, 2, 3, 4))))",
             "expected": "[4, 3, 2, 1]"},
            {"call": "ll_to_list(reverse_ll(to_ll(list())))", "expected": "[]"},
            {"call": "ll_to_list(reverse_ll(to_ll(list(42))))", "expected": "[42]"},
        ],
    },
    {
        "id": "tree_max_depth",
        "title": "Binary tree max depth",
        "difficulty": "medium",
        "problem": (
            "Tree nodes are dicts: `dict(\"val\", v, \"left\", l, \"right\", r)`. "
            "Return the maximum depth (number of nodes on the longest root-to-leaf "
            "path). Empty tree (null) has depth 0."
        ),
        "function_name": "max_depth",
        "starter_code": (
            "// Provided helpers (always available to your solution):\n"
            "//   node(v, left, right) - build a tree node\n"
            "//   leaf(v)              - shortcut for a leaf node\n"
            "\n"
            "func max_depth(root) {\n"
            "    // your code\n"
            "}\n"
        ),
        "helpers": (
            "func node(v, l, r) {\n"
            "    return dict(\"val\", v, \"left\", l, \"right\", r);\n"
            "}\n"
            "\n"
            "func leaf(v) { return node(v, null, null); }\n"
        ),
        "reference_solution": (
            "func max_depth(root) {\n"
            "    if (root == null) { return 0; }\n"
            "    var l = max_depth(get(root, \"left\"));\n"
            "    var r = max_depth(get(root, \"right\"));\n"
            "    if (l > r) { return l + 1; }\n"
            "    return r + 1;\n"
            "}\n"
        ),
        "tests": [
            {"call": "max_depth(null)", "expected": "0"},
            {"call": "max_depth(leaf(1))", "expected": "1"},
            {"call": "max_depth(node(1, leaf(2), leaf(3)))", "expected": "2"},
            {"call": "max_depth(node(1, node(2, leaf(4), null), leaf(3)))", "expected": "3"},
            {"call": "max_depth(node(1, node(2, node(3, leaf(4), null), null), null))", "expected": "4"},
        ],
    },
]


# ===========================================================================
# Recursive variant: same problems and tests as CLASSICS_C_LIKE, but the
# reference_solution uses recursion instead of `while` + reassignment. For
# `no_mutation` languages (love-style) where `i = i + 1` is illegal but
# function calls and stdlib mutation (`set`, `push`) are fine.
#
# We mirror the IDs and tests verbatim — only `reference_solution` and
# `starter_code` differ. The load-pack endpoint picks this variant when
# `customization.feature_bans` includes `no_mutation`.
# ===========================================================================

def _recursive_kata(template: dict, recursive_reference: str,
                    starter: str | None = None,
                    helpers: str | None = None) -> dict:
    """Helper: copy a CLASSICS_C_LIKE entry and swap in the recursive ref.
    Optionally override the helpers (defaulting to the template's, if any)."""
    new = dict(template)
    new["reference_solution"] = recursive_reference
    new["starter_code"] = starter or template["starter_code"]
    if helpers is not None:
        new["helpers"] = helpers
    elif "helpers" in template:
        new["helpers"] = template["helpers"]
    return new


_BY_ID = {k["id"]: k for k in CLASSICS_C_LIKE}

CLASSICS_C_LIKE_RECURSIVE: list[dict] = [
    _recursive_kata(_BY_ID["two_sum"],
        "func two_sum_loop(nums, target, seen, i) {\n"
        "    if (i >= len(nums)) { return list(); }\n"
        "    var n = get(nums, i);\n"
        "    var need = target - n;\n"
        "    if (has(seen, need)) {\n"
        "        return list(get(seen, need), i);\n"
        "    }\n"
        "    set(seen, n, i);\n"
        "    return two_sum_loop(nums, target, seen, i + 1);\n"
        "}\n"
        "\n"
        "func two_sum(nums, target) {\n"
        "    var seen = dict();\n"
        "    return two_sum_loop(nums, target, seen, 0);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["reverse_list"],
        "func reverse_loop(lst, out, i) {\n"
        "    if (i < 0) { return out; }\n"
        "    push(out, get(lst, i));\n"
        "    return reverse_loop(lst, out, i - 1);\n"
        "}\n"
        "\n"
        "func reverse(lst) {\n"
        "    return reverse_loop(lst, list(), len(lst) - 1);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["valid_parens"],
        "func vp_loop(s, stack, pairs, i) {\n"
        "    if (i >= len(s)) { return len(stack) == 0; }\n"
        "    var c = get(s, i);\n"
        "    if (c == \"(\" || c == \"[\" || c == \"{\") {\n"
        "        push(stack, c);\n"
        "    } else if (c == \")\" || c == \"]\" || c == \"}\") {\n"
        "        if (len(stack) == 0) { return false; }\n"
        "        var top = pop(stack);\n"
        "        if (top != get(pairs, c)) { return false; }\n"
        "    }\n"
        "    return vp_loop(s, stack, pairs, i + 1);\n"
        "}\n"
        "\n"
        "func valid_parens(s) {\n"
        "    var stack = list();\n"
        "    var pairs = dict(\")\", \"(\", \"]\", \"[\", \"}\", \"{\");\n"
        "    return vp_loop(s, stack, pairs, 0);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["anagram"],
        "func cc_loop(s, counts, i) {\n"
        "    if (i >= len(s)) { return counts; }\n"
        "    var c = get(s, i);\n"
        "    if (has(counts, c)) {\n"
        "        set(counts, c, get(counts, c) + 1);\n"
        "    } else {\n"
        "        set(counts, c, 1);\n"
        "    }\n"
        "    return cc_loop(s, counts, i + 1);\n"
        "}\n"
        "\n"
        "func count_chars(s) {\n"
        "    var s2 = lower(replace(s, \" \", \"\"));\n"
        "    return cc_loop(s2, dict(), 0);\n"
        "}\n"
        "\n"
        "func ana_loop(ca, cb, ks, i) {\n"
        "    if (i >= len(ks)) { return true; }\n"
        "    var k = get(ks, i);\n"
        "    if (!has(cb, k)) { return false; }\n"
        "    if (get(ca, k) != get(cb, k)) { return false; }\n"
        "    return ana_loop(ca, cb, ks, i + 1);\n"
        "}\n"
        "\n"
        "func is_anagram(a, b) {\n"
        "    var ca = count_chars(a);\n"
        "    var cb = count_chars(b);\n"
        "    if (len(keys(ca)) != len(keys(cb))) { return false; }\n"
        "    return ana_loop(ca, cb, keys(ca), 0);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["max_subarray"],
        "func max_of(a, b) {\n"
        "    if (a > b) { return a; }\n"
        "    return b;\n"
        "}\n"
        "\n"
        "func ms_loop(nums, here, best, i) {\n"
        "    if (i >= len(nums)) { return best; }\n"
        "    var n = get(nums, i);\n"
        "    var new_here = max_of(here + n, n);\n"
        "    var new_best = max_of(new_here, best);\n"
        "    return ms_loop(nums, new_here, new_best, i + 1);\n"
        "}\n"
        "\n"
        "func max_subarray(nums) {\n"
        "    return ms_loop(nums, get(nums, 0), get(nums, 0), 1);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["move_zeros"],
        "func mz_pad(out, zeros, z) {\n"
        "    if (z >= zeros) { return out; }\n"
        "    push(out, 0);\n"
        "    return mz_pad(out, zeros, z + 1);\n"
        "}\n"
        "\n"
        "func mz_loop(nums, out, zeros, i) {\n"
        "    if (i >= len(nums)) { return mz_pad(out, zeros, 0); }\n"
        "    var n = get(nums, i);\n"
        "    if (n == 0) {\n"
        "        return mz_loop(nums, out, zeros + 1, i + 1);\n"
        "    }\n"
        "    push(out, n);\n"
        "    return mz_loop(nums, out, zeros, i + 1);\n"
        "}\n"
        "\n"
        "func move_zeros(nums) {\n"
        "    return mz_loop(nums, list(), 0, 0);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["two_pointer_pair_sum"],
        "func tp_loop(nums, target, lo, hi) {\n"
        "    if (lo >= hi) { return list(); }\n"
        "    var s = get(nums, lo) + get(nums, hi);\n"
        "    if (s == target) { return list(lo, hi); }\n"
        "    if (s < target) {\n"
        "        return tp_loop(nums, target, lo + 1, hi);\n"
        "    }\n"
        "    return tp_loop(nums, target, lo, hi - 1);\n"
        "}\n"
        "\n"
        "func pair_sum_sorted(nums, target) {\n"
        "    return tp_loop(nums, target, 0, len(nums) - 1);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["longest_unique_substring"],
        "func max_of(a, b) {\n"
        "    if (a > b) { return a; }\n"
        "    return b;\n"
        "}\n"
        "\n"
        # Don't combine `has(...) && get(...) >= lo` into one expression — some
        # languages evaluate `&&` eagerly, which would call get() on a missing
        # key and crash on the comparison. Nested if is portable.
        "func lu_compute_lo(seen, c, lo) {\n"
        "    if (has(seen, c)) {\n"
        "        if (get(seen, c) >= lo) {\n"
        "            return get(seen, c) + 1;\n"
        "        }\n"
        "    }\n"
        "    return lo;\n"
        "}\n"
        "\n"
        "func lu_loop(s, seen, lo, best, i) {\n"
        "    if (i >= len(s)) { return best; }\n"
        "    var c = get(s, i);\n"
        "    var new_lo = lu_compute_lo(seen, c, lo);\n"
        "    set(seen, c, i);\n"
        "    var new_best = max_of(best, i - new_lo + 1);\n"
        "    return lu_loop(s, seen, new_lo, new_best, i + 1);\n"
        "}\n"
        "\n"
        "func longest_unique(s) {\n"
        "    return lu_loop(s, dict(), 0, 0, 0);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["best_time_to_buy_sell"],
        "func min_of(a, b) {\n"
        "    if (a < b) { return a; }\n"
        "    return b;\n"
        "}\n"
        "\n"
        "func max_of2(a, b) {\n"
        "    if (a > b) { return a; }\n"
        "    return b;\n"
        "}\n"
        "\n"
        "func mp_loop(prices, lo, best, i) {\n"
        "    if (i >= len(prices)) { return best; }\n"
        "    var p = get(prices, i);\n"
        "    var new_lo = min_of(lo, p);\n"
        "    var new_best = max_of2(best, p - new_lo);\n"
        "    return mp_loop(prices, new_lo, new_best, i + 1);\n"
        "}\n"
        "\n"
        "func max_profit(prices) {\n"
        "    if (len(prices) == 0) { return 0; }\n"
        "    return mp_loop(prices, get(prices, 0), 0, 1);\n"
        "}\n"
    ),
    _recursive_kata(_BY_ID["climb_stairs"],
        "func cs_loop(a, b, i, n) {\n"
        "    if (i > n) { return b; }\n"
        "    return cs_loop(b, a + b, i + 1, n);\n"
        "}\n"
        "\n"
        "func climb(n) {\n"
        "    if (n <= 2) { return n; }\n"
        "    return cs_loop(1, 2, 3, n);\n"
        "}\n"
    ),
    # linked_list_reverse: recursion-only reference + recursion-only helpers
    # so no_mutation languages can run them. Helpers field is separate so
    # the user's solution gets to_ll/ll_to_list automatically.
    _recursive_kata(_BY_ID["linked_list_reverse"],
        recursive_reference=(
            "func rl_loop(prev, curr) {\n"
            "    if (curr == null) { return prev; }\n"
            "    var nxt = get(curr, \"next\");\n"
            "    set(curr, \"next\", prev);\n"
            "    return rl_loop(curr, nxt);\n"
            "}\n"
            "\n"
            "func reverse_ll(head) {\n"
            "    return rl_loop(null, head);\n"
            "}\n"
        ),
        helpers=(
            "func to_ll_loop(items, head, i) {\n"
            "    if (i < 0) { return head; }\n"
            "    var new_head = dict(\"val\", get(items, i), \"next\", head);\n"
            "    return to_ll_loop(items, new_head, i - 1);\n"
            "}\n"
            "\n"
            "func to_ll(items) {\n"
            "    return to_ll_loop(items, null, len(items) - 1);\n"
            "}\n"
            "\n"
            "func ll_to_list_loop(head, out) {\n"
            "    if (head == null) { return out; }\n"
            "    push(out, get(head, \"val\"));\n"
            "    return ll_to_list_loop(get(head, \"next\"), out);\n"
            "}\n"
            "\n"
            "func ll_to_list(head) {\n"
            "    return ll_to_list_loop(head, list());\n"
            "}\n"
        ),
    ),
    # tree_max_depth: already recursive; helpers stay the same as base variant
    # (they're already recursion-only). Inherits helpers from _BY_ID via
    # _recursive_kata's default behavior.
    _recursive_kata(_BY_ID["tree_max_depth"],
        recursive_reference=(
            "func max_depth(root) {\n"
            "    if (root == null) { return 0; }\n"
            "    var l = max_depth(get(root, \"left\"));\n"
            "    var r = max_depth(get(root, \"right\"));\n"
            "    if (l > r) { return l + 1; }\n"
            "    return r + 1;\n"
            "}\n"
        ),
    ),
]


# Curated packs surfaced by /api/kata-packs and the GUI's preset list.
# ===========================================================================
# Per-kata metadata for the LeetCode-style problem library: tags, examples,
# constraints, and which test indices are "sample" (visible / Run button)
# vs "hidden" (Submit button). Layered onto CLASSICS_C_LIKE + RECURSIVE so
# both variants share the same metadata.
#
# `examples` are PUBLIC: shown on the problem page. They have explanation
# text in addition to input/output.
# `constraints` are PUBLIC: shown on the problem page.
# `sample_test_indices`: which entries of `tests[]` Run executes (default
#   is the first one if not specified). Submit always runs ALL tests.
# `acceptance_rate`: rough difficulty stat for the library list, just
#   indicative — we don't track real submissions yet.
# ===========================================================================

CLASSICS_META: dict[str, dict] = {
    "two_sum": {
        "tags": ["array", "hash-table"],
        "acceptance_rate": 0.51,
        "examples": [
            {"input": "nums = [2, 7, 11, 15], target = 9", "output": "[0, 1]",
             "explanation": "nums[0] + nums[1] == 2 + 7 == 9, so we return [0, 1]."},
            {"input": "nums = [3, 2, 4], target = 6", "output": "[1, 2]",
             "explanation": "nums[1] + nums[2] == 2 + 4 == 6."},
        ],
        "constraints": [
            "2 <= len(nums) <= 10^4",
            "-10^9 <= nums[i], target <= 10^9",
            "Exactly one valid pair exists.",
        ],
        "sample_test_indices": [0],
    },
    "reverse_list": {
        "tags": ["array", "two-pointer"],
        "acceptance_rate": 0.78,
        "examples": [
            {"input": "list(1, 2, 3)", "output": "[3, 2, 1]"},
            {"input": "list()", "output": "[]"},
        ],
        "constraints": ["0 <= len(lst) <= 10^4"],
        "sample_test_indices": [0],
    },
    "valid_parens": {
        "tags": ["stack", "string"],
        "acceptance_rate": 0.42,
        "examples": [
            {"input": "\"()\"", "output": "true"},
            {"input": "\"()[]{}\"", "output": "true"},
            {"input": "\"(]\"", "output": "false"},
        ],
        "constraints": ["0 <= len(s) <= 10^4", "s contains only `()[]{}`"],
        "sample_test_indices": [0, 1, 2, 3],  # show enough to cover patterns
    },
    "anagram": {
        "tags": ["hash-table", "string", "sorting"],
        "acceptance_rate": 0.65,
        "examples": [
            {"input": "a = \"listen\", b = \"silent\"", "output": "true"},
            {"input": "a = \"hello\", b = \"world\"", "output": "false"},
        ],
        "constraints": [
            "1 <= len(a), len(b) <= 5 * 10^4",
            "Comparison is case-insensitive and ignores spaces.",
        ],
        "sample_test_indices": [0, 1],
    },
    "max_subarray": {
        "tags": ["array", "dynamic-programming", "divide-and-conquer"],
        "acceptance_rate": 0.50,
        "examples": [
            {"input": "[-2, 1, -3, 4, -1, 2, 1, -5, 4]", "output": "6",
             "explanation": "Subarray [4, -1, 2, 1] sums to 6."},
            {"input": "[1]", "output": "1"},
        ],
        "constraints": ["1 <= len(nums) <= 10^5", "-10^4 <= nums[i] <= 10^4"],
        "sample_test_indices": [0, 1],
    },
    "move_zeros": {
        "tags": ["array", "two-pointer"],
        "acceptance_rate": 0.61,
        "examples": [
            {"input": "[0, 1, 0, 3, 12]", "output": "[1, 3, 12, 0, 0]"},
            {"input": "[0]", "output": "[0]"},
        ],
        "constraints": ["1 <= len(nums) <= 10^4"],
        "sample_test_indices": [0],
    },
    "two_pointer_pair_sum": {
        "tags": ["array", "two-pointer", "sorted"],
        "acceptance_rate": 0.60,
        "examples": [
            {"input": "nums = [1, 2, 3, 4, 6], target = 6", "output": "[1, 3]",
             "explanation": "nums[1] + nums[3] = 2 + 4 = 6."},
            {"input": "nums = [1, 2, 3], target = 7", "output": "[]",
             "explanation": "No pair sums to 7."},
        ],
        "constraints": [
            "0 <= len(nums) <= 10^4",
            "nums is sorted in non-decreasing order.",
        ],
        "sample_test_indices": [0, 1],
    },
    "longest_unique_substring": {
        "tags": ["hash-table", "string", "sliding-window"],
        "acceptance_rate": 0.34,
        "examples": [
            {"input": "\"abcabcbb\"", "output": "3",
             "explanation": "The longest unique-char substring is \"abc\" (length 3)."},
            {"input": "\"bbbbb\"", "output": "1"},
            {"input": "\"\"", "output": "0"},
        ],
        "constraints": ["0 <= len(s) <= 5 * 10^4"],
        "sample_test_indices": [0, 1, 3],
    },
    "best_time_to_buy_sell": {
        "tags": ["array", "dynamic-programming", "greedy"],
        "acceptance_rate": 0.54,
        "examples": [
            {"input": "[7, 1, 5, 3, 6, 4]", "output": "5",
             "explanation": "Buy at 1, sell at 6, profit 5."},
            {"input": "[7, 6, 4, 3, 1]", "output": "0",
             "explanation": "Prices only fall, no profitable trade."},
        ],
        "constraints": ["0 <= len(prices) <= 10^5"],
        "sample_test_indices": [0, 1],
    },
    "climb_stairs": {
        "tags": ["math", "dynamic-programming", "recursion"],
        "acceptance_rate": 0.52,
        "examples": [
            {"input": "n = 2", "output": "2",
             "explanation": "Two ways: [1,1] or [2]."},
            {"input": "n = 3", "output": "3",
             "explanation": "Three ways: [1,1,1], [1,2], [2,1]."},
        ],
        "constraints": ["1 <= n <= 45"],
        "sample_test_indices": [1, 2, 3],
    },
    "linked_list_reverse": {
        "tags": ["linked-list", "recursion"],
        "acceptance_rate": 0.74,
        "examples": [
            {"input": "to_ll(list(1, 2, 3, 4))", "output": "head of [4, 3, 2, 1]",
             "explanation": "Reversing pointers in-place."},
        ],
        "constraints": ["0 <= length <= 5000", "Node values fit in int."],
        "sample_test_indices": [0, 1],
    },
    "tree_max_depth": {
        "tags": ["tree", "dfs", "binary-tree", "recursion"],
        "acceptance_rate": 0.74,
        "examples": [
            {"input": "leaf(1)", "output": "1"},
            {"input": "node(1, leaf(2), leaf(3))", "output": "2"},
        ],
        "constraints": ["0 <= number of nodes <= 10^4"],
        "sample_test_indices": [0, 1, 2],
    },
}


def _enrich(katas: list[dict]) -> list[dict]:
    """Layer CLASSICS_META on top of each kata. Idempotent."""
    out = []
    for k in katas:
        meta = CLASSICS_META.get(k["id"], {})
        merged = dict(k)
        for field in ("tags", "examples", "constraints",
                      "acceptance_rate", "sample_test_indices"):
            if field in meta:
                merged[field] = meta[field]
        out.append(merged)
    return out


# Apply metadata enrichment to both variants. The kata's tests[] stays as
# the FULL (sample + hidden) set — sample_test_indices flags which are
# visible/runnable via the Run button.
CLASSICS_C_LIKE = _enrich(CLASSICS_C_LIKE)
CLASSICS_C_LIKE_RECURSIVE = _enrich(CLASSICS_C_LIKE_RECURSIVE)


# ---------------------------------------------------------------------------
# Stack-based / concatenative classics. Curated specifically for Forth-
# flavored languages because the c_like classics lean heavily on lists +
# dicts + loops over indexed collections, all awkward in pure stack form.
# Per families.md item 2.2: "Pair this family with a curated kata pack
# tuned to it."
#
# Two themes:
#   1. Number theory + iteration: factorial, fib, gcd, sum_to_n,
#      is_prime, count_digits, reverse_digits, power_of_two.
#   2. Data structures via dict cells: ll_length, ll_sum, ll_reverse,
#      tree_max_depth, tree_sum. Helpers (ll-node, vals->ll, t-node,
#      leaf) are pre-defined per kata so the user only writes the algo.
#
# VALIDATION GUARANTEE: every reference solution in this pack is run
# against every test by `forge.orchestrator.validate_kata_pack` (and
# `tests/test_kata_pack_pipeline.py` in CI). Any regression in the
# parser, codegen, runtime, or a kata's reference text fails the
# pipeline with a per-kata-per-test breakdown. To re-validate ad-hoc:
#
#     python -m forge.orchestrator.validate_kata_pack stack_classics
# ---------------------------------------------------------------------------

STACK_CLASSICS_FORTH: list[dict] = [
    {
        "id": "factorial",
        "title": "Factorial",
        "difficulty": "easy",
        "problem": (
            "Given a non-negative integer n, return n! (the product 1*2*...*n). "
            "0! and 1! are both 1. Define the word `factorial` that consumes "
            "n from the stack and produces n!."
        ),
        "function_name": "factorial",
        "starter_code": ": factorial ( n -- n! )\n    \\ your code\n;\n",
        "reference_solution": (
            ": factorial ( n -- n! )\n"
            "    dup 1 <= if drop 1 else dup 1 - factorial * then ;\n"
        ),
        "tests": [
            {"call": "0 factorial",  "expected": "1"},
            {"call": "1 factorial",  "expected": "1"},
            {"call": "5 factorial",  "expected": "120"},
            {"call": "6 factorial",  "expected": "720"},
            {"call": "10 factorial", "expected": "3628800"},
        ],
    },
    {
        "id": "fib",
        "title": "Fibonacci (iterative)",
        "difficulty": "easy",
        "problem": (
            "Given n, return the nth Fibonacci number where fib(0)=0, fib(1)=1, "
            "fib(n)=fib(n-1)+fib(n-2). Use iteration via `do/loop` for speed; "
            "deep recursion would overflow the call stack on n>30. Define the "
            "word `fib` that consumes n and produces fib(n)."
        ),
        "function_name": "fib",
        "starter_code": ": fib ( n -- fib(n) )\n    \\ your code\n;\n",
        "reference_solution": (
            "variable fib_n\n"
            ": fib ( n -- fib(n) )\n"
            "    fib_n !\n"
            "    fib_n @ 2 < if fib_n @ else\n"
            "        0 1\n"
            "        fib_n @ 1 - 0 do over over + rot drop loop\n"
            "        nip\n"
            "    then ;\n"
        ),
        "tests": [
            {"call": "0 fib",  "expected": "0"},
            {"call": "1 fib",  "expected": "1"},
            {"call": "2 fib",  "expected": "1"},
            {"call": "5 fib",  "expected": "5"},
            {"call": "10 fib", "expected": "55"},
            {"call": "15 fib", "expected": "610"},
        ],
    },
    {
        "id": "gcd",
        "title": "Greatest common divisor (Euclidean)",
        "difficulty": "easy",
        "problem": (
            "Define `gcd ( a b -- gcd )` returning the greatest common divisor "
            "of a and b. The Euclidean algorithm is the cleanest approach: "
            "gcd(a, 0) = a; gcd(a, b) = gcd(b, a mod b)."
        ),
        "function_name": "gcd",
        "starter_code": ": gcd ( a b -- gcd )\n    \\ your code\n;\n",
        "reference_solution": (
            ": gcd ( a b -- gcd )\n"
            "    dup 0 = if drop else swap over mod gcd then ;\n"
        ),
        "tests": [
            {"call": "12 18 gcd",  "expected": "6"},
            {"call": "17 5 gcd",   "expected": "1"},
            {"call": "100 75 gcd", "expected": "25"},
            {"call": "13 13 gcd",  "expected": "13"},
            {"call": "48 18 gcd",  "expected": "6"},
            {"call": "0 5 gcd",    "expected": "5"},
        ],
    },
    {
        "id": "sum_to_n",
        "title": "Sum 1..n",
        "difficulty": "easy",
        "problem": (
            "Define `sum-to-n ( n -- sum )` returning 1 + 2 + ... + n. "
            "n is non-negative; sum-to-n of 0 is 0. Use `do/loop` for "
            "iteration. The result of 100 sum-to-n is the famous 5050."
        ),
        "function_name": "sum-to-n",
        "starter_code": ": sum-to-n ( n -- sum )\n    \\ your code\n;\n",
        "reference_solution": (
            ": sum-to-n ( n -- sum )\n"
            "    0 swap 1 + 1 do i + loop ;\n"
        ),
        "tests": [
            {"call": "1 sum-to-n",   "expected": "1"},
            {"call": "5 sum-to-n",   "expected": "15"},
            {"call": "10 sum-to-n",  "expected": "55"},
            {"call": "100 sum-to-n", "expected": "5050"},
        ],
    },
    {
        "id": "is_prime",
        "title": "Primality check",
        "difficulty": "medium",
        "problem": (
            "Define `is-prime ( n -- bool )` returning true if n is prime, "
            "false otherwise. Numbers less than 2 are not prime. Trial-divide "
            "from 2 up to sqrt(n); use a `begin/until` loop with a sentinel "
            "variable to exit early when a divisor is found."
        ),
        "function_name": "is-prime",
        "starter_code": ": is-prime ( n -- bool )\n    \\ your code\n;\n",
        "reference_solution": (
            "variable is_prime_n\n"
            "variable is_prime_d\n"
            "variable is_prime_result\n"
            ": is-prime ( n -- bool )\n"
            "    is_prime_n !\n"
            "    is_prime_n @ 2 < if false else\n"
            "        2 is_prime_d !\n"
            "        true is_prime_result !\n"
            "        begin\n"
            "            is_prime_d @ dup * is_prime_n @ >\n"
            "            if true else\n"
            "                is_prime_n @ is_prime_d @ mod 0 = if\n"
            "                    false is_prime_result !\n"
            "                    true\n"
            "                else\n"
            "                    is_prime_d @ 1 + is_prime_d !\n"
            "                    false\n"
            "                then\n"
            "            then\n"
            "        until\n"
            "        is_prime_result @\n"
            "    then ;\n"
        ),
        "tests": [
            {"call": "0 is-prime",   "expected": "false"},
            {"call": "1 is-prime",   "expected": "false"},
            {"call": "2 is-prime",   "expected": "true"},
            {"call": "3 is-prime",   "expected": "true"},
            {"call": "4 is-prime",   "expected": "false"},
            {"call": "9 is-prime",   "expected": "false"},
            {"call": "17 is-prime",  "expected": "true"},
            {"call": "25 is-prime",  "expected": "false"},
            {"call": "97 is-prime",  "expected": "true"},
        ],
    },
    {
        "id": "count_digits",
        "title": "Count digits",
        "difficulty": "easy",
        "problem": (
            "Define `count-digits ( n -- count )` returning the number of "
            "decimal digits in n. Convention: count-digits of 0 is 0 (not 1). "
            "n is non-negative. Repeatedly divide by 10 until you hit zero, "
            "counting iterations."
        ),
        "function_name": "count-digits",
        "starter_code": ": count-digits ( n -- count )\n    \\ your code\n;\n",
        "reference_solution": (
            ": count-digits ( n -- count )\n"
            "    0 swap\n"
            "    begin\n"
            "        dup 0 >\n"
            "        if 10 / swap 1 + swap false\n"
            "        else drop true then\n"
            "    until ;\n"
        ),
        "tests": [
            {"call": "0 count-digits",       "expected": "0"},
            {"call": "5 count-digits",       "expected": "1"},
            {"call": "10 count-digits",      "expected": "2"},
            {"call": "123 count-digits",     "expected": "3"},
            {"call": "9999 count-digits",    "expected": "4"},
            {"call": "1000000 count-digits", "expected": "7"},
        ],
    },
    {
        "id": "reverse_digits",
        "title": "Reverse digits",
        "difficulty": "medium",
        "problem": (
            "Define `reverse-digits ( n -- reversed )` that returns n with "
            "its decimal digits reversed. 123 -> 321. Trailing zeros become "
            "leading zeros (which are dropped): 1000 -> 1. n is non-negative; "
            "reverse-digits of 0 is 0."
        ),
        "function_name": "reverse-digits",
        "starter_code": ": reverse-digits ( n -- reversed )\n    \\ your code\n;\n",
        "reference_solution": (
            ": reverse-digits ( n -- reversed )\n"
            "    0 swap\n"
            "    begin\n"
            "        dup 0 >\n"
            "        if dup 10 mod\n"
            "            rot 10 * + swap\n"
            "            10 / false\n"
            "        else drop true then\n"
            "    until ;\n"
        ),
        "tests": [
            {"call": "0 reverse-digits",      "expected": "0"},
            {"call": "5 reverse-digits",      "expected": "5"},
            {"call": "10 reverse-digits",     "expected": "1"},
            {"call": "123 reverse-digits",    "expected": "321"},
            {"call": "1000 reverse-digits",   "expected": "1"},
            {"call": "987654 reverse-digits", "expected": "456789"},
        ],
    },
    {
        "id": "power_of_two",
        "title": "Power of two?",
        "difficulty": "medium",
        "problem": (
            "Define `power-of-two? ( n -- bool )` returning true if n is "
            "a power of 2 (1, 2, 4, 8, 16, ...). Numbers less than 1 are "
            "not powers of 2. Repeatedly halve n; if you ever hit a non-"
            "even-non-1 value, it isn't a power of 2."
        ),
        "function_name": "power-of-two?",
        "starter_code": ": power-of-two? ( n -- bool )\n    \\ your code\n;\n",
        "reference_solution": (
            "variable pow2_n\n"
            ": power-of-two? ( n -- bool )\n"
            "    pow2_n !\n"
            "    pow2_n @ 1 < if false else\n"
            "        true\n"
            "        begin\n"
            "            pow2_n @ 1 = if true\n"
            "            else\n"
            "                pow2_n @ 2 mod 0 <> if\n"
            "                    drop false true\n"
            "                else\n"
            "                    pow2_n @ 2 / pow2_n !\n"
            "                    false\n"
            "                then\n"
            "            then\n"
            "        until\n"
            "    then ;\n"
        ),
        "tests": [
            {"call": "0 power-of-two?",     "expected": "false"},
            {"call": "1 power-of-two?",     "expected": "true"},
            {"call": "2 power-of-two?",     "expected": "true"},
            {"call": "3 power-of-two?",     "expected": "false"},
            {"call": "4 power-of-two?",     "expected": "true"},
            {"call": "8 power-of-two?",     "expected": "true"},
            {"call": "15 power-of-two?",    "expected": "false"},
            {"call": "1024 power-of-two?",  "expected": "true"},
            {"call": "1023 power-of-two?",  "expected": "false"},
        ],
    },

    # -------------------------------------------------------------------
    # Data-structure katas. Forth doesn't have native linked lists or
    # trees, but with `dict` cells (added to forthlang's runtime) we can
    # model nodes as `{ "val" -> v, "next" -> n }` for linked lists and
    # `{ "val" -> v, "left" -> l, "right" -> r }` for binary trees.
    #
    # Helpers (`ll-node`, `vals->ll`, `ll->vals`, `t-node`, `leaf`) are
    # provided as the kata's `helpers` field. They get auto-prepended to
    # the user's submission at test time, so the user only writes the
    # core algorithm.
    # -------------------------------------------------------------------

    # Shared helper blocks. Pull them into local strings to avoid copy/
    # paste between the linked-list and tree katas.
    {
        "id": "ll_length",
        "title": "Linked list length",
        "difficulty": "easy",
        "problem": (
            "Define `ll-length ( head -- n )` that returns the number of "
            "nodes in a linked list. Empty list (`nil`) has length 0. "
            "The list nodes are dicts: each has a `val` and a `next` "
            "pointing to the next node or `nil`. Helpers `ll-node`, "
            "`vals->ll`, `ll->vals` are pre-defined for you."
        ),
        "function_name": "ll-length",
        "starter_code": ": ll-length ( head -- n )\n    \\ your code\n;\n",
        "helpers": (
            ": ll-node ( val next -- node )\n"
            "    dict swap s\" next\" swap dset\n"
            "    swap s\" val\" swap dset ;\n"
            ": vals->ll ( v1 ... vN n -- head )\n"
            "    nil swap 0 do ll-node loop ;\n"
            ": ll->vals ( head -- list )\n"
            "    list swap\n"
            "    begin\n"
            "        dup nil =\n"
            "        if drop true\n"
            "        else dup s\" val\" get rot swap push swap\n"
            "             s\" next\" get false\n"
            "        then\n"
            "    until ;\n"
        ),
        "reference_solution": (
            ": ll-length ( head -- n )\n"
            "    0 swap\n"
            "    begin\n"
            "        dup nil =\n"
            "        if drop true\n"
            "        else s\" next\" get swap 1 + swap false\n"
            "        then\n"
            "    until ;\n"
        ),
        "tests": [
            {"call": "nil ll-length",                       "expected": "0"},
            {"call": "42 nil ll-node ll-length",            "expected": "1"},
            {"call": "1 2 3 3 vals->ll ll-length",          "expected": "3"},
            {"call": "10 20 30 40 50 5 vals->ll ll-length", "expected": "5"},
            {"call": "0 0 0 0 0 0 0 7 vals->ll ll-length",  "expected": "7"},
        ],
    },
    {
        "id": "ll_sum",
        "title": "Linked list sum",
        "difficulty": "easy",
        "problem": (
            "Define `ll-sum ( head -- sum )` that returns the sum of all "
            "values in a linked list. Empty list sums to 0. Helpers "
            "`ll-node`, `vals->ll`, `ll->vals` are pre-defined."
        ),
        "function_name": "ll-sum",
        "starter_code": ": ll-sum ( head -- sum )\n    \\ your code\n;\n",
        "helpers": (
            ": ll-node ( val next -- node )\n"
            "    dict swap s\" next\" swap dset\n"
            "    swap s\" val\" swap dset ;\n"
            ": vals->ll ( v1 ... vN n -- head )\n"
            "    nil swap 0 do ll-node loop ;\n"
            ": ll->vals ( head -- list )\n"
            "    list swap\n"
            "    begin\n"
            "        dup nil =\n"
            "        if drop true\n"
            "        else dup s\" val\" get rot swap push swap\n"
            "             s\" next\" get false\n"
            "        then\n"
            "    until ;\n"
        ),
        "reference_solution": (
            ": ll-sum ( head -- sum )\n"
            "    0 swap\n"
            "    begin\n"
            "        dup nil =\n"
            "        if drop true\n"
            "        else dup s\" val\" get rot + swap s\" next\" get false\n"
            "        then\n"
            "    until ;\n"
        ),
        "tests": [
            {"call": "nil ll-sum",                          "expected": "0"},
            {"call": "42 nil ll-node ll-sum",               "expected": "42"},
            {"call": "1 2 3 3 vals->ll ll-sum",             "expected": "6"},
            {"call": "10 20 30 40 4 vals->ll ll-sum",       "expected": "100"},
            {"call": "5 5 5 5 5 5 5 5 5 5 10 vals->ll ll-sum", "expected": "50"},
        ],
    },
    {
        "id": "ll_reverse",
        "title": "Reverse a linked list",
        "difficulty": "medium",
        "problem": (
            "Define `ll-reverse ( head -- new-head )` that reverses a "
            "linked list in place. The result is a list with the same "
            "values in reverse order. Hint: walk the list with three "
            "pointer-variables (`prev`, `curr`, `tmp`) and re-link as "
            "you go. Test calls use `ll->vals` to print the result."
        ),
        "function_name": "ll-reverse",
        "starter_code": (
            "variable ll_prev\n"
            "variable ll_curr\n"
            "variable ll_tmp\n"
            ": ll-reverse ( head -- new-head )\n"
            "    \\ your code\n"
            ";\n"
        ),
        "helpers": (
            ": ll-node ( val next -- node )\n"
            "    dict swap s\" next\" swap dset\n"
            "    swap s\" val\" swap dset ;\n"
            ": vals->ll ( v1 ... vN n -- head )\n"
            "    nil swap 0 do ll-node loop ;\n"
            ": ll->vals ( head -- list )\n"
            "    list swap\n"
            "    begin\n"
            "        dup nil =\n"
            "        if drop true\n"
            "        else dup s\" val\" get rot swap push swap\n"
            "             s\" next\" get false\n"
            "        then\n"
            "    until ;\n"
        ),
        "reference_solution": (
            "variable ll_prev\n"
            "variable ll_curr\n"
            "variable ll_tmp\n"
            ": ll-reverse ( head -- new-head )\n"
            "    nil ll_prev !\n"
            "    ll_curr !\n"
            "    begin\n"
            "        ll_curr @ nil =\n"
            "        if true\n"
            "        else\n"
            "            ll_curr @ s\" next\" get ll_tmp !\n"
            "            ll_curr @ s\" next\" ll_prev @ dset drop\n"
            "            ll_curr @ ll_prev !\n"
            "            ll_tmp @ ll_curr !\n"
            "            false\n"
            "        then\n"
            "    until\n"
            "    ll_prev @ ;\n"
        ),
        "tests": [
            {"call": "nil ll-reverse ll->vals",                   "expected": "[]"},
            {"call": "42 nil ll-node ll-reverse ll->vals",        "expected": "[42]"},
            {"call": "1 2 3 3 vals->ll ll-reverse ll->vals",      "expected": "[3, 2, 1]"},
            {"call": "1 2 3 4 5 5 vals->ll ll-reverse ll->vals",  "expected": "[5, 4, 3, 2, 1]"},
            {"call": "7 1 vals->ll ll-reverse ll->vals",          "expected": "[7]"},
        ],
    },
    {
        "id": "tree_max_depth",
        "title": "Binary tree max depth",
        "difficulty": "medium",
        "problem": (
            "Define `tree-max-depth ( tree -- depth )` returning the "
            "maximum depth of a binary tree (longest path from root to "
            "any leaf, counted in nodes). An empty tree (`nil`) has "
            "depth 0; a single leaf has depth 1. Helpers `t-node` "
            "( val left right -- node ) and `leaf` ( v -- node ) "
            "are pre-defined."
        ),
        "function_name": "tree-max-depth",
        "starter_code": ": tree-max-depth ( tree -- depth )\n    \\ your code\n;\n",
        "helpers": (
            ": t-node ( val left right -- node )\n"
            "    dict swap s\" right\" swap dset\n"
            "    swap s\" left\" swap dset\n"
            "    swap s\" val\" swap dset ;\n"
            ": leaf ( v -- node )\n"
            "    nil nil t-node ;\n"
        ),
        "reference_solution": (
            ": tree-max-depth ( tree -- depth )\n"
            "    dup nil =\n"
            "    if drop 0\n"
            "    else\n"
            "        dup s\" left\" get tree-max-depth\n"
            "        swap s\" right\" get tree-max-depth\n"
            "        over over <\n"
            "        if nip\n"
            "        else drop\n"
            "        then\n"
            "        1 +\n"
            "    then ;\n"
        ),
        "tests": [
            {"call": "nil tree-max-depth",                                          "expected": "0"},
            {"call": "5 leaf tree-max-depth",                                        "expected": "1"},
            {"call": "1 2 leaf 3 leaf t-node tree-max-depth",                        "expected": "2"},
            {"call": "1 2 3 leaf 4 leaf t-node 5 leaf t-node tree-max-depth",        "expected": "3"},
            {"call": "1 2 3 4 leaf 5 leaf t-node nil t-node 6 leaf t-node tree-max-depth", "expected": "4"},
        ],
    },
    {
        "id": "tree_sum",
        "title": "Binary tree sum",
        "difficulty": "easy",
        "problem": (
            "Define `tree-sum ( tree -- sum )` returning the sum of all "
            "values in a binary tree. Empty tree (`nil`) sums to 0. "
            "Helpers `t-node` and `leaf` pre-defined."
        ),
        "function_name": "tree-sum",
        "starter_code": ": tree-sum ( tree -- sum )\n    \\ your code\n;\n",
        "helpers": (
            ": t-node ( val left right -- node )\n"
            "    dict swap s\" right\" swap dset\n"
            "    swap s\" left\" swap dset\n"
            "    swap s\" val\" swap dset ;\n"
            ": leaf ( v -- node )\n"
            "    nil nil t-node ;\n"
        ),
        "reference_solution": (
            ": tree-sum ( tree -- sum )\n"
            "    dup nil =\n"
            "    if drop 0\n"
            "    else\n"
            "        dup s\" left\" get tree-sum\n"
            "        over s\" right\" get tree-sum\n"
            "        rot s\" val\" get + +\n"
            "    then ;\n"
        ),
        "tests": [
            {"call": "nil tree-sum",                                       "expected": "0"},
            {"call": "5 leaf tree-sum",                                     "expected": "5"},
            {"call": "1 2 leaf 3 leaf t-node tree-sum",                     "expected": "6"},
            {"call": "10 20 leaf 30 leaf t-node tree-sum",                  "expected": "60"},
            {"call": "1 2 3 leaf 4 leaf t-node 5 leaf t-node tree-sum",     "expected": "15"},
        ],
    },
]


def _enrich_stack(katas: list[dict]) -> list[dict]:
    """Add metadata + sample_test_indices to stack-classics. Stack katas
    don't reuse the c_like CLASSICS_META (different problem set), so we
    add a small set of defaults inline."""
    out = []
    for k in katas:
        k = dict(k)
        # Sample tests: first 2 are visible (Run mode); rest are hidden (Submit mode).
        n = len(k.get("tests", []))
        k["sample_test_indices"] = list(range(min(2, n)))
        k.setdefault("tags", ["stack", "math"])
        k.setdefault("examples", [])
        k.setdefault("constraints", [])
        k.setdefault("acceptance_rate", 0.6)
        out.append(k)
    return out


STACK_CLASSICS_FORTH = _enrich_stack(STACK_CLASSICS_FORTH)


# ---------------------------------------------------------------------------
# ml_like kata pack (added by the ml-family experiment).
#
# Curated for ML idiom: pattern matching on `[]` / `h :: t`, recursive
# accumulators, no mutation, no while loops. Stage E v1 ships a smaller
# pack than CLASSICS_C_LIKE_RECURSIVE (6 vs 12) — see
# MLLANG_EXPERIMENT_CLOSEOUT.md (Stage H) for cost accounting + which
# c_like classics didn't translate cleanly (dict-heavy ones like anagram
# would need module-system features mllang v1 doesn't have).
#
# Each kata's `tests[]` calls are already in mllang syntax (juxtaposition,
# no parens, lists as `[1; 2; 3]`). The kata wrapper in
# `katas._wrap_with_test_prints` prepends `print_any (...) ;;` per test.
# ---------------------------------------------------------------------------
CLASSICS_ML_LIKE: list[dict] = [
    {
        "id": "fibonacci",
        "title": "Nth Fibonacci",
        "difficulty": "easy",
        "problem": (
            "Return the n-th Fibonacci number (0-indexed: fib 0 = 0, "
            "fib 1 = 1, fib 2 = 1, fib 3 = 2, ...). Classic recursion "
            "exercise in ML."
        ),
        "function_name": "fib",
        "starter_code": "let rec fib n =\n  (* your code *)\n;;\n",
        "reference_solution": (
            "let rec fib n =\n"
            "  if n < 2 then n\n"
            "  else fib (n - 1) + fib (n - 2)\n"
            ";;\n"
        ),
        "tests": [
            {"call": "fib 0",  "expected": "0"},
            {"call": "fib 1",  "expected": "1"},
            {"call": "fib 5",  "expected": "5"},
            {"call": "fib 10", "expected": "55"},
        ],
    },
    {
        "id": "factorial",
        "title": "Factorial",
        "difficulty": "easy",
        "problem": "Return n! (n factorial). fact 0 = 1, fact 5 = 120.",
        "function_name": "fact",
        "starter_code": "let rec fact n =\n  (* your code *)\n;;\n",
        "reference_solution": (
            "let rec fact n =\n"
            "  if n <= 1 then 1\n"
            "  else n * fact (n - 1)\n"
            ";;\n"
        ),
        "tests": [
            {"call": "fact 0", "expected": "1"},
            {"call": "fact 1", "expected": "1"},
            {"call": "fact 5", "expected": "120"},
            {"call": "fact 7", "expected": "5040"},
        ],
    },
    {
        "id": "sum_list",
        "title": "Sum a list",
        "difficulty": "easy",
        "problem": (
            "Return the sum of all integers in a list. Empty list -> 0. "
            "Natural ML idiom: pattern match on `[] -> 0 | h :: t -> h + sum t`."
        ),
        "function_name": "sum_list",
        "starter_code": "let rec sum_list lst =\n  (* your code *)\n;;\n",
        "reference_solution": (
            "let rec sum_list lst = match lst with\n"
            "  | [] -> 0\n"
            "  | h :: t -> h + sum_list t\n"
            ";;\n"
        ),
        "tests": [
            {"call": "sum_list []",            "expected": "0"},
            {"call": "sum_list [1; 2; 3]",     "expected": "6"},
            {"call": "sum_list [10; -3; 7]",   "expected": "14"},
            {"call": "sum_list [1; 2; 3; 4; 5; 6; 7; 8; 9; 10]", "expected": "55"},
        ],
    },
    {
        "id": "list_length",
        "title": "Length of a list",
        "difficulty": "easy",
        "problem": (
            "Return the number of elements in a list, computed by "
            "structural recursion (don't call the built-in list_length)."
        ),
        "function_name": "my_length",
        "starter_code": "let rec my_length lst =\n  (* your code *)\n;;\n",
        "reference_solution": (
            "let rec my_length lst = match lst with\n"
            "  | [] -> 0\n"
            "  | h :: t -> 1 + my_length t\n"
            ";;\n"
        ),
        "tests": [
            {"call": "my_length []",                "expected": "0"},
            {"call": "my_length [42]",              "expected": "1"},
            {"call": "my_length [1; 2; 3; 4; 5]",   "expected": "5"},
            {"call": "my_length [\"a\"; \"b\"; \"c\"]", "expected": "3"},
        ],
    },
    {
        "id": "reverse_list",
        "title": "Reverse a list",
        "difficulty": "easy",
        "problem": (
            "Return a new list with the elements in reverse order. "
            "Classic ML idiom: tail-recursive with an accumulator that "
            "gets prepended to."
        ),
        "function_name": "rev",
        "starter_code": "let rec rev lst =\n  (* your code *)\n;;\n",
        "reference_solution": (
            "let rec rev_helper lst acc = match lst with\n"
            "  | [] -> acc\n"
            "  | h :: t -> rev_helper t (h :: acc)\n"
            ";;\n"
            "\n"
            "let rev lst = rev_helper lst [] ;;\n"
        ),
        "tests": [
            {"call": "rev []",            "expected": "[]"},
            {"call": "rev [1; 2; 3]",     "expected": "[3, 2, 1]"},
            {"call": "rev [42]",          "expected": "[42]"},
            {"call": "rev [1; 1; 2; 3]",  "expected": "[3, 2, 1, 1]"},
        ],
    },
    {
        "id": "count_occurrences",
        "title": "Count occurrences in a list",
        "difficulty": "easy",
        "problem": (
            "Return how many times `target` appears in `lst`. "
            "Recursive accumulator over the list."
        ),
        "function_name": "count_occ",
        "starter_code": "let rec count_occ target lst =\n  (* your code *)\n;;\n",
        "reference_solution": (
            "let rec count_occ target lst = match lst with\n"
            "  | [] -> 0\n"
            "  | h :: t ->\n"
            "      let rest = count_occ target t in\n"
            "      if h = target then 1 + rest else rest\n"
            ";;\n"
        ),
        "tests": [
            {"call": "count_occ 1 []",              "expected": "0"},
            {"call": "count_occ 2 [1; 2; 3; 2; 1]", "expected": "2"},
            {"call": "count_occ 7 [1; 2; 3]",       "expected": "0"},
            {"call": "count_occ 1 [1; 1; 1; 1]",    "expected": "4"},
        ],
    },
]


# Enrich with a minimal sample_test_indices tag — the GUI uses this to
# show which tests are visible (vs hidden). For ml_like we expose the
# first 2 of 4 as samples, hidden 2-3 are the validation set.
def _enrich_ml(katas: list[dict]) -> list[dict]:
    out = []
    for k in katas:
        merged = dict(k)
        if "sample_test_indices" not in merged:
            merged["sample_test_indices"] = [0, 1]
        out.append(merged)
    return out


CLASSICS_ML_LIKE = _enrich_ml(CLASSICS_ML_LIKE)


# ---------------------------------------------------------------------------
# logic_like kata pack — pragmatic Prolog problems.
#
# Added by the logic-family experiment. Per LOGICLANG_DESIGN.md §8: 7
# katas curated for the logic-programming idiom. The katas are NOT
# c_like problems with renamed syntax — they're logic-programming-shaped
# problems where the predicate's last argument is the "result" (the
# standard Prolog convention: `factorial(N, F)`, `length(L, N)`, etc.).
#
# Each kata's `tests[]` calls are in Prolog source syntax with a free
# variable as the last argument. The kata wrapper in
# `katas._wrap_with_test_prints` (logic_like branch) emits each test
# as a directive: `:- factorial(5, R), write(R), nl.`
#
# Boolean predicates (like `is_member/2`) use a free-var-less test call;
# the wrapper falls back to the if-then-else boolean form:
# `:- (is_member(2, [1,2,3]) -> write(true) ; write(false)), nl.`
#
# Naming caveat: `is_member` not `member` because the runtime ships
# `member/2` as a built-in. Using `member` as a kata predicate name
# would shadow the builtin and make the reference solution trivially
# delegable to "call the builtin" — defeats the kata's pedagogical
# point. Same for `list_length` (vs builtin `length/2`),
# `append_lists` (vs builtin `append/3`), `reverse_list` (vs builtin
# `reverse/2`).
# ---------------------------------------------------------------------------
CLASSICS_LOGIC_LIKE: list[dict] = [
    {
        "id": "factorial",
        "title": "Factorial",
        "difficulty": "easy",
        "problem": (
            "Define `factorial(N, F)` such that F is N! (N factorial). "
            "factorial(0, F) should bind F to 1. Classic recursive predicate "
            "with a base case + recursive case."
        ),
        "function_name": "factorial",
        "starter_code": "factorial(N, F) :-\n    % your code.\n",
        "reference_solution": (
            "factorial(0, 1).\n"
            "factorial(N, F) :-\n"
            "    N > 0,\n"
            "    N1 is N - 1,\n"
            "    factorial(N1, F1),\n"
            "    F is N * F1.\n"
        ),
        "tests": [
            {"call": "factorial(0, R)", "expected": "1"},
            {"call": "factorial(1, R)", "expected": "1"},
            {"call": "factorial(5, R)", "expected": "120"},
            {"call": "factorial(7, R)", "expected": "5040"},
        ],
    },
    {
        "id": "list_length",
        "title": "Length of a list",
        "difficulty": "easy",
        "problem": (
            "Define `list_length(L, N)` such that N is the number of "
            "elements in list L. Use head/tail recursion: empty list has "
            "length 0; [H|T] has length 1 + list_length(T)."
        ),
        "function_name": "list_length",
        "starter_code": "list_length(L, N) :-\n    % your code.\n",
        "reference_solution": (
            "list_length([], 0).\n"
            "list_length([_ | T], N) :-\n"
            "    list_length(T, N1),\n"
            "    N is N1 + 1.\n"
        ),
        "tests": [
            {"call": "list_length([], R)",              "expected": "0"},
            {"call": "list_length([a], R)",             "expected": "1"},
            {"call": "list_length([a, b, c], R)",       "expected": "3"},
            {"call": "list_length([1, 2, 3, 4, 5], R)", "expected": "5"},
        ],
    },
    {
        "id": "is_member",
        "title": "List membership",
        "difficulty": "easy",
        "problem": (
            "Define `is_member(X, L)` that succeeds if X appears anywhere in "
            "list L. Pattern-match head/tail; recurse on tail. (Named "
            "is_member to not shadow the builtin member/2.)"
        ),
        "function_name": "is_member",
        "starter_code": "is_member(X, L) :-\n    % your code.\n",
        "reference_solution": (
            "is_member(X, [X | _]).\n"
            "is_member(X, [_ | T]) :- is_member(X, T).\n"
        ),
        "tests": [
            # Boolean-shaped tests: no free var in the call. The kata
            # wrapper detects this and emits the if-then-else boolean form.
            {"call": "is_member(2, [1, 2, 3])",   "expected": "true"},
            {"call": "is_member(5, [1, 2, 3])",   "expected": "false"},
            {"call": "is_member(a, [a, b, c])",   "expected": "true"},
            {"call": "is_member(x, [])",          "expected": "false"},
        ],
    },
    {
        "id": "reverse_list",
        "title": "Reverse a list",
        "difficulty": "medium",
        "problem": (
            "Define `reverse_list(L, R)` such that R is L with its elements "
            "in reverse order. The idiomatic Prolog approach uses an "
            "accumulator: reverse_list(L, R) :- reverse_acc(L, [], R). "
            "(Named reverse_list to not shadow the builtin reverse/2.)"
        ),
        "function_name": "reverse_list",
        "starter_code": "reverse_list(L, R) :-\n    % your code.\n",
        "reference_solution": (
            "reverse_list(L, R) :- reverse_acc(L, [], R).\n"
            "reverse_acc([], Acc, Acc).\n"
            "reverse_acc([H | T], Acc, R) :- reverse_acc(T, [H | Acc], R).\n"
        ),
        "tests": [
            {"call": "reverse_list([], R)",         "expected": "[]"},
            {"call": "reverse_list([1], R)",        "expected": "[1]"},
            {"call": "reverse_list([1, 2, 3], R)",  "expected": "[3, 2, 1]"},
            {"call": "reverse_list([a, b, c, d], R)", "expected": "[d, c, b, a]"},
        ],
    },
    {
        "id": "append_lists",
        "title": "Append two lists",
        "difficulty": "medium",
        "problem": (
            "Define `append_lists(L1, L2, R)` such that R is L1 followed by L2. "
            "The classic recursive append: empty + L = L; [H|T] + L = "
            "[H | T + L]. (Named append_lists to not shadow the builtin "
            "append/3.)"
        ),
        "function_name": "append_lists",
        "starter_code": "append_lists(L1, L2, R) :-\n    % your code.\n",
        "reference_solution": (
            "append_lists([], L, L).\n"
            "append_lists([H | T], L, [H | R]) :- append_lists(T, L, R).\n"
        ),
        "tests": [
            {"call": "append_lists([], [1, 2, 3], R)",         "expected": "[1, 2, 3]"},
            {"call": "append_lists([1, 2], [], R)",            "expected": "[1, 2]"},
            {"call": "append_lists([1, 2], [3, 4], R)",        "expected": "[1, 2, 3, 4]"},
            {"call": "append_lists([a, b], [c, d, e], R)",     "expected": "[a, b, c, d, e]"},
        ],
    },
    {
        "id": "max_list",
        "title": "Maximum of a list",
        "difficulty": "medium",
        "problem": (
            "Define `max_list(L, M)` such that M is the largest element in "
            "the non-empty list L. Recurse on the tail; compare head against "
            "the recursive result."
        ),
        "function_name": "max_list",
        "starter_code": "max_list(L, M) :-\n    % your code.\n",
        "reference_solution": (
            "max_list([X], X).\n"
            "max_list([H | T], M) :-\n"
            "    max_list(T, MT),\n"
            "    (H >= MT -> M = H ; M = MT).\n"
        ),
        "tests": [
            {"call": "max_list([5], R)",            "expected": "5"},
            {"call": "max_list([1, 2, 3], R)",      "expected": "3"},
            {"call": "max_list([3, 1, 4, 1, 5, 9, 2, 6], R)", "expected": "9"},
            {"call": "max_list([-1, -5, -2], R)",   "expected": "-1"},
        ],
    },
    {
        "id": "ancestor",
        "title": "Ancestor relations",
        "difficulty": "medium",
        "problem": (
            "Given facts about parent/2 relationships, define `ancestor(X, Y)` "
            "that succeeds if X is an ancestor of Y (parent, grandparent, "
            "great-grandparent, ...). Two clauses: parent IS an ancestor; "
            "and any parent's ancestor is also an ancestor."
        ),
        "function_name": "ancestor",
        "starter_code": "ancestor(X, Y) :-\n    % your code.\n",
        # The kata's reference depends on parent/2 facts. The kata's
        # `helpers` field carries them so the test runner has the
        # background facts available before the user's clauses run.
        "helpers": (
            "parent(tom, bob).\n"
            "parent(bob, ann).\n"
            "parent(ann, sue).\n"
            "parent(tom, liz).\n"
        ),
        "reference_solution": (
            "ancestor(X, Y) :- parent(X, Y).\n"
            "ancestor(X, Y) :- parent(X, Z), ancestor(Z, Y).\n"
        ),
        "tests": [
            {"call": "ancestor(tom, bob)",   "expected": "true"},
            {"call": "ancestor(tom, sue)",   "expected": "true"},
            {"call": "ancestor(bob, tom)",   "expected": "false"},
            {"call": "ancestor(liz, sue)",   "expected": "false"},
        ],
    },
]


# Enrich with sample_test_indices, same shape as ml_like.
def _enrich_logic(katas: list[dict]) -> list[dict]:
    out = []
    for k in katas:
        merged = dict(k)
        if "sample_test_indices" not in merged:
            merged["sample_test_indices"] = [0, 1]
        out.append(merged)
    return out


CLASSICS_LOGIC_LIKE = _enrich_logic(CLASSICS_LOGIC_LIKE)


PACKS: dict[str, dict] = {
    "classics": {
        "title": "LeetCode classics",
        "description": "Two sum, valid parens, sliding window, Kadane, climbing stairs, "
                       "linked-list reverse, binary tree max depth, plus more.",
        "katas": CLASSICS_C_LIKE,
        "syntax_family": "c_like",
    },
    "ml_classics": {
        "title": "ML classics",
        "description": "6 recursion-and-pattern-matching problems curated for "
                       "ml_like languages: fib, factorial, sum_list, list_length, "
                       "reverse_list, count_occurrences. ML-idiomatic — pattern "
                       "matching on `[]` / `h :: t`, tail recursion with "
                       "accumulators, no mutation. Smaller pack than the c_like "
                       "classics because several pointer-heavy LeetCode problems "
                       "(two_sum-with-dict, anagram) need module-system features "
                       "mllang v1 doesn't ship.",
        "katas": CLASSICS_ML_LIKE,
        "syntax_family": "ml_like",
    },
    "stack_classics": {
        "title": "Stack-based classics",
        "description": "8 stack-friendly problems: factorial, fib, gcd, sum-to-n, "
                       "is-prime, count-digits, reverse-digits, power-of-two. "
                       "Postfix-natural; written in Forth syntax. Curated for "
                       "stack_based languages where pointer-heavy LeetCode "
                       "classics would feel awkward.",
        "katas": STACK_CLASSICS_FORTH,
        "syntax_family": "stack_based",
    },
    "logic_classics": {
        "title": "Logic-programming classics",
        "description": "7 Prolog-idiomatic problems: factorial, list_length, "
                       "is_member, reverse_list, append_lists, max_list, "
                       "ancestor (family-relations). Last-arg-is-output "
                       "convention; multi-clause predicates with base + "
                       "recursive cases; pattern matching on [H|T]. Curated "
                       "for logic_like languages where c_like classics would "
                       "be category errors (no mutation, no loops, queries "
                       "instead of function calls).",
        "katas": CLASSICS_LOGIC_LIKE,
        "syntax_family": "logic_like",
    },
}


def get_classics_for(spec: dict) -> list[dict]:
    """Return the classics variant best suited to a language's constraints.

    Family routing:
      - logic_like      -> CLASSICS_LOGIC_LIKE (predicates + backtracking)
      - ml_like         -> CLASSICS_ML_LIKE (recursion + pattern matching)
      - stack_based     -> handled separately via stack_classics pack
      - any c_like-ish with no_mutation/no_loops bans -> RECURSIVE variant
      - otherwise        -> CLASSICS_C_LIKE (mutating loops permitted)

    Returns a deep copy."""
    import copy
    syntax = (spec.get("options") or {}).get("syntax")
    if syntax == "logic_like":
        return copy.deepcopy(CLASSICS_LOGIC_LIKE)
    if syntax == "ml_like":
        return copy.deepcopy(CLASSICS_ML_LIKE)
    bans = (spec.get("customization") or {}).get("feature_bans") or []
    if "no_mutation" in bans or "no_loops" in bans:
        return copy.deepcopy(CLASSICS_C_LIKE_RECURSIVE)
    return copy.deepcopy(CLASSICS_C_LIKE)


def list_packs() -> list[dict]:
    """Compact listing for the GUI."""
    return [
        {"key": k, "title": v["title"], "description": v["description"],
         "syntax_family": v["syntax_family"], "kata_count": len(v["katas"])}
        for k, v in PACKS.items()
    ]


def get_pack(key: str) -> dict | None:
    """Return a deep-ish copy of the pack so callers can mutate freely."""
    pack = PACKS.get(key)
    if pack is None:
        return None
    import copy
    return copy.deepcopy(pack)
