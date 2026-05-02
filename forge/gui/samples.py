"""Sample programs to load in the Playground.

Two flavors are provided per sample: c_like and python_like, since the GUI
auto-picks based on the current language's syntax.
"""
from __future__ import annotations


SAMPLES = {
    "fizzbuzz": {
        "title": "FizzBuzz (1..15)",
        "description": "Print FizzBuzz for numbers 1 to 15.",
        "c_like": """\
// FizzBuzz 1..15
var i = 1;
while (i <= 15) {
    if (i % 15 == 0) {
        print("FizzBuzz");
    } else if (i % 3 == 0) {
        print("Fizz");
    } else if (i % 5 == 0) {
        print("Buzz");
    } else {
        print(i);
    }
    i = i + 1;
}
""",
        "python_like": """\
# FizzBuzz 1..15
let i = 1
while i <= 15:
    if i % 15 == 0:
        print("FizzBuzz")
    elif i % 3 == 0:
        print("Fizz")
    elif i % 5 == 0:
        print("Buzz")
    else:
        print(i)
    i = i + 1
""",
    },
    "fibonacci": {
        "title": "Fibonacci (first 10)",
        "description": "Recursive fib for 0..9.",
        "c_like": """\
// Fibonacci 0..9
func fib(n) {
    if (n <= 1) { return n; }
    return fib(n - 1) + fib(n - 2);
}

var i = 0;
while (i < 10) {
    print(fib(i));
    i = i + 1;
}
""",
        "python_like": """\
# Fibonacci 0..9
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

let i = 0
while i < 10:
    print(fib(i))
    i = i + 1
""",
    },
    "counter_factory": {
        "title": "Counter factory (closures)",
        "description": "Make independent counters that don't share state.",
        "c_like": """\
// Each counter has its own state
func make_counter() {
    var n = 0;
    func step() {
        n = n + 1;
        return n;
    }
    return step;
}

var a = make_counter();
var b = make_counter();
print(a());   // 1
print(a());   // 2
print(b());   // 1
print(a());   // 3
""",
        "python_like": """\
# Each counter has its own state
def make_counter():
    let n = 0
    def step():
        n = n + 1
        return n
    return step

let a = make_counter()
let b = make_counter()
print(a())   # 1
print(a())   # 2
print(b())   # 1
print(a())   # 3
""",
    },
    "string_manipulation": {
        "title": "String concat + length",
        "description": "Join names and report length.",
        "c_like": """\
var first = "Language";
var second = "Forge";
var combined = first + " " + second;
print(combined);
print(len(combined));
""",
        "python_like": """\
let first = "Language"
let second = "Forge"
let combined = first + " " + second
print(combined)
print(len(combined))
""",
    },

    "wordcount": {
        "title": "Word count (text input)",
        "description": "Count words in a string. Demonstrates split + len.",
        "c_like": """\
// Word count over a small piece of text.
var text = "the quick brown fox jumps over the lazy dog";
var words = split(text, " ");
print("words:", len(words));

// Tally word frequencies into a dict.
var counts = dict();
var i = 0;
while (i < len(words)) {
    var w = get(words, i);
    if (has(counts, w)) {
        set(counts, w, get(counts, w) + 1);
    } else {
        set(counts, w, 1);
    }
    i = i + 1;
}
print("'the' appears", get(counts, "the"), "times");
print("unique words:", len(keys(counts)));
""",
        "python_like": """\
# Word count over a small piece of text.
let text = "the quick brown fox jumps over the lazy dog"
let words = split(text, " ")
print("words:", len(words))

# Tally word frequencies into a dict.
let counts = dict()
let i = 0
while i < len(words):
    let w = get(words, i)
    if has(counts, w):
        set(counts, w, get(counts, w) + 1)
    else:
        set(counts, w, 1)
    i = i + 1

print("'the' appears", get(counts, "the"), "times")
print("unique words:", len(keys(counts)))
""",
    },

    "list_operations": {
        "title": "List operations",
        "description": "Build a list, sum it, find the max.",
        "c_like": """\
var nums = list(3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5);
print("count:", len(nums));

// Sum and max with explicit indexing (no foreach syntax in this lang).
var i = 0;
var total = 0;
var biggest = get(nums, 0);
while (i < len(nums)) {
    var x = get(nums, i);
    total = total + x;
    if (x > biggest) { biggest = x; }
    i = i + 1;
}
print("sum:", total);
print("max:", biggest);
print("avg:", total / len(nums));
""",
        "python_like": """\
let nums = list(3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5)
print("count:", len(nums))

let i = 0
let total = 0
let biggest = get(nums, 0)
while i < len(nums):
    let x = get(nums, i)
    total = total + x
    if x > biggest:
        biggest = x
    i = i + 1

print("sum:", total)
print("max:", biggest)
print("avg:", total / len(nums))
""",
    },

    "args_demo": {
        "title": "CLI args demo",
        "description": "Read argv() and echo each argument back.",
        "c_like": """\
// Run the compiled .out.py with extra args to see them here.
//   <lang> args_demo.<ext> && python args_demo.<ext>.out.py hello world 42
var args = argv();
print("got", len(args), "argument(s):");
var i = 0;
while (i < len(args)) {
    print("  [" + str(i) + "]", get(args, i));
    i = i + 1;
}
""",
        "python_like": """\
# Run the compiled .out.py with extra args to see them here.
let args = argv()
print("got", len(args), "argument(s):")
let i = 0
while i < len(args):
    print("  [" + str(i) + "]", get(args, i))
    i = i + 1
""",
    },

    "mandelbrot": {
        "title": "Mandelbrot set (ASCII)",
        "description": "Renders the Mandelbrot set as ASCII art. Visible wow.",
        "c_like": """\
// Mandelbrot set in ASCII. Try it. It is the same fractal in every language.
var width = 60;
var height = 22;
var max_iter = 30;

var y = 0;
while (y < height) {
    var row = "";
    var x = 0;
    while (x < width) {
        var cx = -2.0 + 3.0 * x / width;
        var cy = -1.2 + 2.4 * y / height;
        var zx = 0.0;
        var zy = 0.0;
        var i = 0;
        while (i < max_iter) {
            if (zx * zx + zy * zy >= 4.0) {
                i = max_iter;
            } else {
                var tmp = zx * zx - zy * zy + cx;
                zy = 2.0 * zx * zy + cy;
                zx = tmp;
                i = i + 1;
            }
        }
        if (zx * zx + zy * zy < 4.0) {
            row = row + "#";
        } else {
            row = row + " ";
        }
        x = x + 1;
    }
    print(row);
    y = y + 1;
}
""",
        "python_like": """\
# Mandelbrot set in ASCII.
let width = 60
let height = 22
let max_iter = 30

let y = 0
while y < height:
    let row = ""
    let x = 0
    while x < width:
        let cx = -2.0 + 3.0 * x / width
        let cy = -1.2 + 2.4 * y / height
        let zx = 0.0
        let zy = 0.0
        let i = 0
        while i < max_iter:
            if zx * zx + zy * zy >= 4.0:
                i = max_iter
            else:
                let tmp = zx * zx - zy * zy + cx
                zy = 2.0 * zx * zy + cy
                zx = tmp
                i = i + 1
        if zx * zx + zy * zy < 4.0:
            row = row + "#"
        else:
            row = row + " "
        x = x + 1
    print(row)
    y = y + 1
""",
    },

    "prime_sieve": {
        "title": "Prime sieve (1..100)",
        "description": "Sieve of Eratosthenes. Lists every prime up to 100.",
        "c_like": """\
// Sieve of Eratosthenes. Print every prime from 2 up to N.
var N = 100;

// Build a list of N+1 booleans, all initially true.
var is_prime = list();
var i = 0;
while (i <= N) {
    push(is_prime, true);
    i = i + 1;
}

set(is_prime, 0, false);
set(is_prime, 1, false);

i = 2;
while (i * i <= N) {
    if (get(is_prime, i)) {
        var j = i * i;
        while (j <= N) {
            set(is_prime, j, false);
            j = j + i;
        }
    }
    i = i + 1;
}

var found = list();
i = 2;
while (i <= N) {
    if (get(is_prime, i)) {
        push(found, i);
    }
    i = i + 1;
}

print("primes up to", N);
print(join(", ", found));
print("count:", len(found));
""",
        "python_like": """\
# Sieve of Eratosthenes.
let N = 100

let is_prime = list()
let i = 0
while i <= N:
    push(is_prime, true)
    i = i + 1

set(is_prime, 0, false)
set(is_prime, 1, false)

i = 2
while i * i <= N:
    if get(is_prime, i):
        let j = i * i
        while j <= N:
            set(is_prime, j, false)
            j = j + i
    i = i + 1

let found = list()
i = 2
while i <= N:
    if get(is_prime, i):
        push(found, i)
    i = i + 1

print("primes up to", N)
print(join(", ", found))
print("count:", len(found))
""",
    },

    "palindrome": {
        "title": "Palindrome checker",
        "description": "Tests several strings to see whether they read the same backward.",
        "c_like": """\
// Palindrome checker. Strips spaces and case, then mirror-compares.
func is_palindrome(s) {
    var clean = lower(replace(s, " ", ""));
    var i = 0;
    var j = len(clean) - 1;
    while (i < j) {
        if (get(clean, i) != get(clean, j)) {
            return false;
        }
        i = i + 1;
        j = j - 1;
    }
    return true;
}

var tests = list("racecar", "hello", "A man a plan a canal Panama", "step on no pets", "almost");
var i = 0;
while (i < len(tests)) {
    var s = get(tests, i);
    if (is_palindrome(s)) {
        print(s, "->  palindrome");
    } else {
        print(s, "->  not");
    }
    i = i + 1;
}
""",
        "python_like": """\
# Palindrome checker.
def is_palindrome(s):
    let clean = lower(replace(s, " ", ""))
    let i = 0
    let j = len(clean) - 1
    while i < j:
        if get(clean, i) != get(clean, j):
            return false
        i = i + 1
        j = j - 1
    return true

let tests = list("racecar", "hello", "A man a plan a canal Panama", "step on no pets", "almost")
let i = 0
while i < len(tests):
    let s = get(tests, i)
    if is_palindrome(s):
        print(s, "->  palindrome")
    else:
        print(s, "->  not")
    i = i + 1
""",
    },

    "ascii_tree": {
        "title": "ASCII tree",
        "description": "Tiny terminal-art generator. Holiday vibes.",
        "c_like": """\
// Print a small triangle/tree with a stem.
func line(s, n) {
    var out = "";
    var i = 0;
    while (i < n) {
        out = out + s;
        i = i + 1;
    }
    return out;
}

var height = 8;
var row = 0;
while (row < height) {
    var pad = line(" ", height - row - 1);
    var stars = line("*", 2 * row + 1);
    print(pad + stars);
    row = row + 1;
}

// Trunk
var t = 0;
while (t < 3) {
    print(line(" ", height - 2) + "###");
    t = t + 1;
}
""",
        "python_like": """\
# Print a small triangle/tree with a stem.
def line(s, n):
    let out = ""
    let i = 0
    while i < n:
        out = out + s
        i = i + 1
    return out

let height = 8
let row = 0
while row < height:
    let pad = line(" ", height - row - 1)
    let stars = line("*", 2 * row + 1)
    print(pad + stars)
    row = row + 1

let t = 0
while t < 3:
    print(line(" ", height - 2) + "###")
    t = t + 1
""",
    },
}


def list_samples() -> list[dict]:
    return [
        {"key": k, "title": v["title"], "description": v["description"]}
        for k, v in SAMPLES.items()
    ]


def get_sample(key: str, syntax: str) -> str | None:
    sample = SAMPLES.get(key)
    if sample is None:
        return None
    if syntax == "python_like":
        return sample.get("python_like") or sample.get("c_like")
    return sample.get("c_like")
