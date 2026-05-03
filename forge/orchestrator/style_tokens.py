"""Per-language visual themes.

Roadmap §3.1 — Themed mini-IDE per language.

Each persona, era, theme, and phrasebook can contribute a `style_tokens`
dict with palette overrides. Spec builder merges them in priority order
(theme > era > persona > phrasebook > default) and emits the result as
`spec.theme.tokens`. The generator writes them out to
`<lang>/theme.css` as a `:root` block; the GUI loads that stylesheet
when the language is active.

This is the single most visually-impactful change: same engine, but every
generated language has a memorable visual identity instead of being
"shadcn dark with a different name." The roadmap's framing is exactly
right — Forge stops being a config tool and becomes a museum of
programming aesthetics.

Token schema (all optional, all hex/CSS strings):
    bg            primary background
    bg_2          slightly elevated surface (cards, code blocks)
    card          card surface (defaults to bg)
    line          subtle border
    line_2        emphasized border
    text          primary foreground
    text_2        secondary foreground
    muted         tertiary foreground (labels, subtitles)
    accent        primary brand color
    accent_2      hover/lighter variant
    font_family   body font stack (CSS font-family value)
    mono_font     code/mono font stack
    radius        base border radius (CSS length)
    decoration    one of "scanlines" | "parchment" | "grain" | None
                  (renders an extra full-bleed overlay element)
    name_treatment "uppercase-tracked" | "title" | "calligraphic" | None
                  (how the language's name renders in headers)

When a token isn't set, the GUI's default shadcn-dark value is used.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Default palette (matches the GUI's shadcn-dark base; languages that don't
# pick any theming inherit this)
# ---------------------------------------------------------------------------

DEFAULT_TOKENS: dict[str, str] = {
    "bg": "#0a0e16",
    "bg_2": "#0d1220",
    "card": "#0a0e16",
    "card_2": "#131a2a",
    "line": "#1e293b",
    "line_2": "#2a3a55",
    "text": "#f8fafc",
    "text_2": "#cbd5e1",
    "muted": "#94a3b8",
    "accent": "#3b82f6",
    "accent_2": "#60a5fa",
    "font_family": "'Inter', system-ui, sans-serif",
    "mono_font": "'JetBrains Mono', ui-monospace, monospace",
    "radius": "8px",
    "decoration": "",
    "name_treatment": "title",
}


# ---------------------------------------------------------------------------
# Era tokens — the boldest visual differentiation. Each era's UI literally
# looks like a screenshot from that decade.
# ---------------------------------------------------------------------------

ERA_TOKENS: dict[str, dict[str, str]] = {
    "1960s": {
        # CRT phosphor green-on-black, scanline overlay, monospaced bitmap-ish font.
        "bg": "#0a0a0a",
        "bg_2": "#101010",
        "card": "#0a0a0a",
        "card_2": "#141414",
        "line": "#1f2e1f",
        "line_2": "#2a4030",
        "text": "#33ff33",
        "text_2": "#22cc22",
        "muted": "#168816",
        "accent": "#00ff00",
        "accent_2": "#66ff66",
        "font_family": "'Courier New', 'JetBrains Mono', monospace",
        "mono_font": "'Courier New', 'JetBrains Mono', monospace",
        "radius": "0px",
        "decoration": "scanlines",
        "name_treatment": "uppercase-tracked",
    },
    "1970s": {
        # Amber phosphor — VT100/VT220 vibe.
        "bg": "#0c0a06",
        "bg_2": "#15110a",
        "card": "#0c0a06",
        "card_2": "#1a1610",
        "line": "#3a2a14",
        "line_2": "#4a3520",
        "text": "#ffb000",
        "text_2": "#cc8800",
        "muted": "#886000",
        "accent": "#ffaa00",
        "accent_2": "#ffd060",
        "font_family": "'Courier New', monospace",
        "mono_font": "'Courier New', monospace",
        "radius": "0px",
        "decoration": "scanlines",
        "name_treatment": "uppercase-tracked",
    },
    "1980s": {
        # IBM PC / Borland Turbo: white/cyan on blue, double-line ASCII borders.
        "bg": "#000080",
        "bg_2": "#000060",
        "card": "#0000a0",
        "card_2": "#1414b0",
        "line": "#5050ff",
        "line_2": "#7878ff",
        "text": "#ffff80",
        "text_2": "#c0c0ff",
        "muted": "#9090ff",
        "accent": "#ffff00",
        "accent_2": "#ffffaa",
        "font_family": "'Consolas', 'Courier New', monospace",
        "mono_font": "'Consolas', 'Courier New', monospace",
        "radius": "0px",
        "decoration": "",
        "name_treatment": "uppercase-tracked",
    },
    "2000s": {
        # Web 2.0: glossy gradients, soft shadows, faux-3D.
        "bg": "#1a1a1f",
        "bg_2": "#22222a",
        "card": "#252530",
        "card_2": "#2c2c38",
        "line": "#3a3a48",
        "line_2": "#4f4f65",
        "text": "#f5f5f5",
        "text_2": "#c5c5d0",
        "muted": "#888898",
        "accent": "#39c5ff",
        "accent_2": "#60d6ff",
        "font_family": "'Trebuchet MS', 'Segoe UI', sans-serif",
        "mono_font": "'Consolas', 'Lucida Console', monospace",
        "radius": "10px",
        "decoration": "",
        "name_treatment": "title",
    },
    "2020s": {
        # Modern shadcn dark — the default, named explicitly so it shows up
        # in spec.theme even when era=2020s is picked.
        **DEFAULT_TOKENS,
    },
}


# ---------------------------------------------------------------------------
# Persona tokens — reflect the designer's aesthetic preferences.
# ---------------------------------------------------------------------------

PERSONA_TOKENS: dict[str, dict[str, str]] = {
    "dijkstra": {
        # Academic, almost ascetic: high-contrast, no decoration.
        "bg": "#fafafa", "bg_2": "#f0f0f0", "card": "#ffffff",
        "card_2": "#f6f6f6", "line": "#d4d4d4", "line_2": "#a8a8a8",
        "text": "#1a1a1a", "text_2": "#404040", "muted": "#707070",
        "accent": "#202020", "accent_2": "#404040",
        "font_family": "'EB Garamond', 'Georgia', serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "2px",
        "decoration": "",
        "name_treatment": "title",
    },
    "mccarthy": {
        # Lisp-machine: dark slate + magenta accent. Very 1980s MIT.
        "bg": "#1a1a24",
        "bg_2": "#222230",
        "card": "#1a1a24",
        "card_2": "#262638",
        "line": "#383850",
        "line_2": "#5050a0",
        "text": "#e8e8f0",
        "text_2": "#c0c0d0",
        "muted": "#8080a0",
        "accent": "#ff70d0",
        "accent_2": "#ff9be0",
        "font_family": "'Iosevka', 'JetBrains Mono', monospace",
        "mono_font": "'Iosevka', 'JetBrains Mono', monospace",
        "radius": "4px",
        "decoration": "",
        "name_treatment": "uppercase-tracked",
    },
    "hickey": {
        # Clojure vibe: slate + teal. Calm, considered.
        "bg": "#1c2128",
        "bg_2": "#22282f",
        "card": "#1c2128",
        "card_2": "#2a313a",
        "line": "#34404f",
        "line_2": "#4d5c70",
        "text": "#f0f4f8",
        "text_2": "#c4d0dc",
        "muted": "#8b9aab",
        "accent": "#5fafaf",
        "accent_2": "#8ac4c4",
        "font_family": "'Inter', system-ui, sans-serif",
        "mono_font": "'Fira Code', 'JetBrains Mono', monospace",
        "radius": "10px",
        "decoration": "",
        "name_treatment": "title",
    },
    "stroustrup": {
        # Borland Turbo C++ blue; functional, tradesman-like.
        "bg": "#000060",
        "bg_2": "#0a0a70",
        "card": "#000080",
        "card_2": "#1010a0",
        "line": "#4040d0",
        "line_2": "#7070e0",
        "text": "#ffffff",
        "text_2": "#d0d0ff",
        "muted": "#a0a0e0",
        "accent": "#ffd700",
        "accent_2": "#ffe860",
        "font_family": "'Consolas', monospace",
        "mono_font": "'Consolas', 'Courier New', monospace",
        "radius": "0px",
        "decoration": "",
        "name_treatment": "title",
    },
    "wirth": {
        # Pascal-blue: educational, structured.
        "bg": "#0c1e36",
        "bg_2": "#13294a",
        "card": "#0c1e36",
        "card_2": "#1a3460",
        "line": "#264a7a",
        "line_2": "#3d6098",
        "text": "#f0f4ff",
        "text_2": "#c4cee8",
        "muted": "#8c9bba",
        "accent": "#ffd54a",
        "accent_2": "#ffe580",
        "font_family": "'Helvetica Neue', sans-serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "4px",
        "decoration": "",
        "name_treatment": "title",
    },
    "wadler": {
        # Haskell purple: type-theoretic, formal.
        "bg": "#1a1228",
        "bg_2": "#221830",
        "card": "#1a1228",
        "card_2": "#2a1d3c",
        "line": "#3d2c54",
        "line_2": "#5a4078",
        "text": "#f0e8ff",
        "text_2": "#cabbe4",
        "muted": "#8b7ba6",
        "accent": "#a070ff",
        "accent_2": "#bd95ff",
        "font_family": "'EB Garamond', Georgia, serif",
        "mono_font": "'Iosevka', 'JetBrains Mono', monospace",
        "radius": "6px",
        "decoration": "",
        "name_treatment": "calligraphic",
    },
    "matz": {
        # Ruby red, ergonomic, warm.
        "bg": "#1c0a0a",
        "bg_2": "#2a0e0e",
        "card": "#1c0a0a",
        "card_2": "#341212",
        "line": "#5a1f1f",
        "line_2": "#803030",
        "text": "#fff0eb",
        "text_2": "#e8c8c0",
        "muted": "#b89088",
        "accent": "#e64a4a",
        "accent_2": "#ff7070",
        "font_family": "'Inter', system-ui, sans-serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "12px",
        "decoration": "",
        "name_treatment": "title",
    },
    "ousterhout": {
        # Tcl/Tk gray: practical, terminal-adjacent.
        "bg": "#1e1e1e",
        "bg_2": "#262626",
        "card": "#1e1e1e",
        "card_2": "#2c2c2c",
        "line": "#3c3c3c",
        "line_2": "#525252",
        "text": "#dcdcdc",
        "text_2": "#b0b0b0",
        "muted": "#808080",
        "accent": "#7faaff",
        "accent_2": "#a0c0ff",
        "font_family": "'Lucida Sans', 'Tahoma', sans-serif",
        "mono_font": "'Lucida Console', monospace",
        "radius": "2px",
        "decoration": "",
        "name_treatment": "title",
    },
}


# ---------------------------------------------------------------------------
# Theme tokens — keyword themes get matching visual treatments.
# ---------------------------------------------------------------------------

THEME_TOKENS: dict[str, dict[str, str]] = {
    "pirate": {
        # Parchment + sepia + weathered serif. Imagine an old map.
        "bg": "#3a2a18",
        "bg_2": "#2e1f10",
        "card": "#3a2a18",
        "card_2": "#4a3520",
        "line": "#6b4f30",
        "line_2": "#8c6840",
        "text": "#f4ecd8",
        "text_2": "#d4c8a8",
        "muted": "#a89878",
        "accent": "#d49a3c",
        "accent_2": "#e8b870",
        "font_family": "'IM Fell English', 'Cinzel', Georgia, serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "2px",
        "decoration": "parchment",
        "name_treatment": "calligraphic",
    },
    "shakespearean": {
        # Ink-on-parchment, more refined than pirate.
        "bg": "#f7f0e0",
        "bg_2": "#efe6cf",
        "card": "#fbf6e8",
        "card_2": "#f0e8d0",
        "line": "#c4ad88",
        "line_2": "#9a8460",
        "text": "#2a1f10",
        "text_2": "#4a3a20",
        "muted": "#8a7050",
        "accent": "#702010",
        "accent_2": "#9a3020",
        "font_family": "'IM Fell English', 'EB Garamond', Georgia, serif",
        "mono_font": "'EB Garamond', Georgia, serif",
        "radius": "2px",
        "decoration": "parchment",
        "name_treatment": "calligraphic",
    },
    "corporate": {
        # Helvetica-on-gray: deliberately bland enterprise.
        "bg": "#f4f4f4",
        "bg_2": "#ebebeb",
        "card": "#ffffff",
        "card_2": "#f0f0f0",
        "line": "#d0d0d0",
        "line_2": "#a0a0a0",
        "text": "#202020",
        "text_2": "#505050",
        "muted": "#808080",
        "accent": "#0064a8",
        "accent_2": "#0080d4",
        "font_family": "'Helvetica Neue', Helvetica, Arial, sans-serif",
        "mono_font": "'Consolas', monospace",
        "radius": "4px",
        "decoration": "",
        "name_treatment": "uppercase-tracked",
    },
    "latin": {
        # Roman-inscription parchment: Trajan-flavored serif on cream.
        "bg": "#faf3e3",
        "bg_2": "#f0e6d0",
        "card": "#fdf8eb",
        "card_2": "#f3e9d4",
        "line": "#c8b89a",
        "line_2": "#9a8868",
        "text": "#2a1d10",
        "text_2": "#4a3520",
        "muted": "#806848",
        "accent": "#8b3a2a",
        "accent_2": "#b04830",
        "font_family": "'Cinzel', 'Cormorant Garamond', Georgia, serif",
        "mono_font": "'Cormorant Garamond', Georgia, serif",
        "radius": "2px",
        "decoration": "",
        "name_treatment": "uppercase-tracked",
    },
    "cozy": {
        # Warm cream + terracotta + rounded sans.
        "bg": "#1f1610",
        "bg_2": "#2a1f17",
        "card": "#1f1610",
        "card_2": "#332520",
        "line": "#4a3a30",
        "line_2": "#6a5040",
        "text": "#f8efe2",
        "text_2": "#d8c4a8",
        "muted": "#a89078",
        "accent": "#e08a4a",
        "accent_2": "#f4a570",
        "font_family": "'Quicksand', 'Inter', sans-serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "16px",
        "decoration": "",
        "name_treatment": "title",
    },
}


# ---------------------------------------------------------------------------
# Phrasebook tokens — pair the language's voice with its look.
# ---------------------------------------------------------------------------

PHRASEBOOK_TOKENS: dict[str, dict[str, str]] = {
    "english_storybook": {
        # Soft serif, bookpage-ivory, rounded.
        "bg": "#fbf7ee",
        "bg_2": "#f4ede0",
        "card": "#fefaf2",
        "card_2": "#f6efe2",
        "line": "#d8ccae",
        "line_2": "#a89878",
        "text": "#2a2014",
        "text_2": "#4a3a24",
        "muted": "#806c50",
        "accent": "#8b6a2a",
        "accent_2": "#a8854a",
        "font_family": "'Lora', 'Georgia', serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "12px",
        "decoration": "parchment",
        "name_treatment": "title",
    },
    "shakespeare": {
        # Inherits the Shakespearean theme tokens (ink on parchment).
        **THEME_TOKENS["shakespearean"],
    },
    "child_speak": {
        # Bright, friendly, large rounded shapes.
        "bg": "#fef8ff",
        "bg_2": "#fff0fa",
        "card": "#ffffff",
        "card_2": "#fef0fa",
        "line": "#ffd6f0",
        "line_2": "#ffa8d8",
        "text": "#3a1840",
        "text_2": "#5a2860",
        "muted": "#9060a0",
        "accent": "#ff5fb0",
        "accent_2": "#ff85c8",
        "font_family": "'Quicksand', 'Comic Neue', 'Inter', sans-serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "20px",
        "decoration": "",
        "name_treatment": "title",
    },
    "ritual": {
        # Arcane: deep purple + gold, calligraphic.
        "bg": "#0e0a1c",
        "bg_2": "#150f28",
        "card": "#0e0a1c",
        "card_2": "#1c1438",
        "line": "#352560",
        "line_2": "#5a4090",
        "text": "#f5e8d0",
        "text_2": "#d8c0a0",
        "muted": "#9080a0",
        "accent": "#d4a850",
        "accent_2": "#f0c878",
        "font_family": "'Cinzel', 'EB Garamond', serif",
        "mono_font": "'JetBrains Mono', monospace",
        "radius": "4px",
        "decoration": "",
        "name_treatment": "calligraphic",
    },
}


# ---------------------------------------------------------------------------
# Public API: combine a spec's choices into one token dict
# ---------------------------------------------------------------------------

def style_tokens_for(*, persona: str | None = None,
                     era: str | None = None,
                     theme: str | None = None,
                     phrasebook: str | None = None) -> dict:
    """Merge the chosen presets' style_tokens in priority order.

    Priority (later entries override earlier ones — most specific wins):
        DEFAULT < phrasebook < persona < era < theme

    Theme is highest priority because keyword theme is the most explicitly
    visual choice; era and persona shape the underlying surface; phrasebook
    is mostly textual but also contributes look.
    """
    tokens = dict(DEFAULT_TOKENS)
    if phrasebook and phrasebook in PHRASEBOOK_TOKENS:
        tokens.update(PHRASEBOOK_TOKENS[phrasebook])
    if persona and persona in PERSONA_TOKENS:
        tokens.update(PERSONA_TOKENS[persona])
    if era and era in ERA_TOKENS:
        tokens.update(ERA_TOKENS[era])
    if theme and theme in THEME_TOKENS:
        tokens.update(THEME_TOKENS[theme])
    return tokens


def render_theme_css(tokens: dict, *, scope: str = "body[data-lang-theme]") -> str:
    """Render a tokens dict as a CSS variable block.

    The selector `body[data-lang-theme]` lets the GUI activate the theme
    by setting `<body data-lang-theme="<lang>">` and including the
    language's theme.css stylesheet. Tokens shadow the global ones from
    style.css.
    """
    lines = [f"{scope} {{"]
    # Map our token names to the CSS variable names the GUI uses
    css_var_map = {
        "bg": "--bg", "bg_2": "--bg-2", "card": "--card",
        "card_2": "--card-2", "line": "--line", "line_2": "--line-2",
        "text": "--text", "text_2": "--text-2", "muted": "--muted",
        "accent": "--accent", "accent_2": "--accent-2",
        "font_family": "--font-body", "mono_font": "--font-mono",
        "radius": "--radius-sm",
    }
    for tok_name, css_var in css_var_map.items():
        if tok_name in tokens:
            lines.append(f"  {css_var}: {tokens[tok_name]};")
    # Derived: --accent-soft / --accent-glow from the accent if it's a hex
    accent = tokens.get("accent", "")
    if accent.startswith("#") and len(accent) in (4, 7):
        rgb = _hex_to_rgb(accent)
        if rgb:
            r, g, b = rgb
            lines.append(f"  --accent-soft: rgba({r}, {g}, {b}, 0.12);")
            lines.append(f"  --accent-glow: rgba({r}, {g}, {b}, 0.35);")
    lines.append("}")

    # Decoration overlay (scanlines, parchment grain) — each one a small
    # piece of CSS that targets a `.theme-deco` element the GUI inserts.
    deco = tokens.get("decoration", "")
    if deco == "scanlines":
        lines.append("body[data-lang-theme] .theme-deco {")
        lines.append("  position: fixed; inset: 0; pointer-events: none;")
        lines.append("  background: repeating-linear-gradient(0deg, "
                     "rgba(0,0,0,0.18) 0px, rgba(0,0,0,0.18) 1px, "
                     "transparent 1px, transparent 3px);")
        lines.append("  z-index: 9999;")
        lines.append("}")
    elif deco == "parchment":
        # Subtle paper grain — doubled-up radial gradients give a fibrous look.
        lines.append("body[data-lang-theme] .theme-deco {")
        lines.append("  position: fixed; inset: 0; pointer-events: none;")
        lines.append("  background:")
        lines.append("    radial-gradient(circle at 30% 20%, rgba(120,80,40,0.04) 0%, transparent 40%),")
        lines.append("    radial-gradient(circle at 70% 80%, rgba(80,50,20,0.05) 0%, transparent 50%),")
        lines.append("    radial-gradient(circle at 90% 30%, rgba(140,100,60,0.03) 0%, transparent 30%);")
        lines.append("  mix-blend-mode: overlay;")
        lines.append("  z-index: 9999;")
        lines.append("}")
    return "\n".join(lines) + "\n"


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    """Parse #rgb or #rrggbb into (r, g, b)."""
    s = hex_str.lstrip("#")
    if len(s) == 3:
        return (int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16))
    if len(s) == 6:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    return None
