"""Flask GUI for Forge.

Three views (single-page app):
  - Create: pick syntax/typing/memory/name + provider → POST /api/create
  - Progress: streams generation log via SSE → /api/stream/<job_id>
  - Playground: write a program in the new language, compile + run via
    POST /api/run

Designed to feel like a clean modern dev tool: dark theme, big readable
type, calm spacing, live-updating progress.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Optional

from flask import Flask, Response, jsonify, request, send_from_directory


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]


# ---------------------------------------------------------------------------
# Job registry: a job is one in-flight `forge create` run
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, opts: dict, name: str, provider: Optional[str],
                 customization: Optional[dict] = None,
                 persona: Optional[str] = None,
                 era: Optional[str] = None,
                 keyword_theme: Optional[str] = None,
                 feature_bans: Optional[list[str]] = None,
                 hostile_constraints: Optional[str] = None,
                 phrasebook: Optional[str] = None,
                 natural_language: Optional[dict] = None,
                 lineage: Optional[dict] = None):
        self.id = uuid.uuid4().hex[:8]
        self.opts = opts
        self.name = name
        self.provider = provider
        self.customization = customization or {}
        self.persona = persona
        self.era = era
        self.keyword_theme = keyword_theme
        self.feature_bans = feature_bans or []
        self.hostile_constraints = hostile_constraints
        self.phrasebook = phrasebook
        self.natural_language = natural_language
        self.lineage = lineage
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.done = False
        self.success = False
        self.lang_dir: Optional[Path] = None
        self.error: Optional[str] = None

    def emit(self, kind: str, **payload) -> None:
        self.queue.put({"kind": kind, **payload})


# Module-level job registry. Multiple Flask threads call register_job /
# get_job concurrently; the lock keeps reads + writes consistent. Without
# it, two near-simultaneous /api/create + /api/stream/<id> calls could
# observe a partially-initialized Job (`done`/`error`/`success` unset).
JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def register_job(job: "Job") -> None:
    with _JOBS_LOCK:
        JOBS[job.id] = job


def get_job(job_id: str) -> Optional["Job"]:
    with _JOBS_LOCK:
        return JOBS.get(job_id)


# ---------------------------------------------------------------------------
# Background generation worker
# ---------------------------------------------------------------------------

def _run_job(job: Job) -> None:
    try:
        from forge.orchestrator.spec_builder import build_spec
        from forge.orchestrator.providers import make_client
        from forge.orchestrator.resolver import resolve
        from forge.orchestrator.generator import generate_all
        from forge.orchestrator.repair import repair_run
        from forge.orchestrator.verifier import verify

        lang_dir = WORKSPACE / "generated" / job.name
        log_dir = lang_dir / ".forge_log"
        client = make_client(job.provider, log_dir=log_dir)
        job.emit("step", label=f"Provider: {type(client).__name__}", status="info")

        job.emit("step", label="Building base spec", status="running")
        base = build_spec(
            job.opts, job.name,
            customization=job.customization or None,
            persona=job.persona,
            era=job.era,
            keyword_theme=job.keyword_theme,
            feature_bans=job.feature_bans or None,
            hostile_constraints=job.hostile_constraints,
            phrasebook=job.phrasebook,
            natural_language=job.natural_language,
            lineage=job.lineage,
        )
        job.emit("step", label="Building base spec", status="done")

        job.emit("step", label="Resolving spec via LLM", status="running")
        resolved = resolve(base, client=client)
        job.emit("step", label="Resolving spec via LLM", status="done")
        job.emit("spec", spec=resolved)

        # Per-component progress: generate_all calls back as each starts/ends.
        component_labels = {c: f"Generating {c}" for c in _components_for(resolved)}

        def on_progress(component, status):
            label = component_labels.get(component, f"Generating {component}")
            job.emit("step", label=label, status=status)

        lang_dir = generate_all(
            resolved,
            output_root=WORKSPACE / "generated",
            client=client,
            on_progress=on_progress,
        )
        job.lang_dir = lang_dir

        job.emit("step", label="Verifying canonical tests", status="running")
        report = verify(lang_dir)
        job.emit("step", label="Verifying canonical tests",
                 status="done" if report.all_passed else "fail")
        job.emit("report", report=report.to_dict())

        if not report.all_passed:
            job.emit("step", label="Running repair loop", status="running")
            report = repair_run(lang_dir, client=client)
            job.emit("step", label="Running repair loop",
                     status="done" if report.all_passed else "fail")
            job.emit("report", report=report.to_dict())

        # Roadmap §4.6: after the language is verified (or repair runs),
        # have the LLM critique it as a designer would. REVIEW.md is small,
        # one extra LLM call, and gives the language personality + an
        # honest assessment in the Library card. Best-effort; never blocks
        # the job.
        #
        # SKIP for templated languages (s_expression, stack_based) - those
        # share the same hand-written reference compiler so the critique
        # would be near-identical for every language in that family.
        # User can request it on demand via POST /api/review/<lang>.
        from forge.orchestrator.generator import reference_compiler_for
        if reference_compiler_for(resolved) is None:
            try:
                from forge.orchestrator.critic import critique_language
                job.emit("step", label="Critiquing the language", status="running")
                review = critique_language(resolved, lang_dir, client)
                job.emit("step", label="Critiquing the language",
                         status="done" if review else "fail")
            except Exception:
                pass

        job.success = report.all_passed
        job.emit("done", success=job.success, lang_dir=str(lang_dir))
    except Exception as e:
        job.error = f"{type(e).__name__}: {e}"
        job.emit("done", success=False, error=job.error)
    finally:
        job.done = True


def _components_for(spec: dict) -> list[str]:
    base = ["lexer", "parser", "codegen", "runtime", "stdlib", "tests", "readme"]
    if spec["options"]["typing"] == "static":
        base.insert(2, "typechecker")
    return base


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

def create_app(*, catalog_db_path: Optional[Path] = None,
               catalog_generated_root: Optional[Path] = None) -> Flask:
    """Build the Flask app.

    Phase 3 additions:
      catalog_db_path: override the SQLite catalog DB path used by
        the curation routes (defaults to <workspace>/catalog.db).
        Tests pass a temp path so they don't touch the real catalog.
      catalog_generated_root: override the directory the curation UI
        reads `<slot_id>/slot.json` from when the DB row's
        customization fields were normalized away by the resolver.
    """
    app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")

    # Phase 3: mount catalog browse + curation routes onto the same
    # Flask app. Kept in a separate module so app.py doesn't keep
    # growing.
    from forge.gui.catalog_routes import mount_catalog_routes
    mount_catalog_routes(
        app,
        catalog_db_path=catalog_db_path,
        generated_root=catalog_generated_root,
    )

    @app.route("/")
    def root():
        return send_from_directory(str(HERE / "static"), "index.html")

    @app.route("/api/providers")
    def providers():
        from forge.orchestrator.providers import detect_default_provider
        import shutil as _shutil
        return jsonify({
            "default": detect_default_provider(),
            "available": {
                "api": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "claude_cli": bool(_shutil.which("claude") or _shutil.which("claude.cmd")),
            },
        })

    @app.route("/api/languages")
    def languages():
        gen = WORKSPACE / "generated"
        if not gen.exists():
            return jsonify({"languages": []})
        out = []
        for d in sorted(gen.iterdir()):
            if not d.is_dir():
                continue
            spec = d / "resolved_spec.json"
            ext = ".toy"
            opts = {}
            origin_story = ""
            theme_sources = {}
            theme_tokens = {}
            lineage = None
            persona = None
            era = None
            keyword_theme = None
            if spec.exists():
                try:
                    data = json.loads(spec.read_text(encoding="utf-8"))
                    ext = data.get("file_extension", ext)
                    opts = data.get("options", {})
                    origin_story = data.get("origin_story", "") or ""
                    theme_sources = (data.get("theme") or {}).get("sources") or {}
                    lineage = data.get("lineage")
                    cust = data.get("customization") or {}
                    persona = cust.get("persona")
                    era = cust.get("era")
                    keyword_theme = cust.get("keyword_theme")
                    # Send a tiny token subset for Library card swatches —
                    # bg/text/accent are enough to render a 1-line preview.
                    full_tokens = (data.get("theme") or {}).get("tokens") or {}
                    theme_tokens = {
                        k: full_tokens[k] for k in ("bg", "text", "accent",
                                                     "font_family", "mono_font")
                        if k in full_tokens
                    }
                except Exception:
                    pass
            # Truth-source: canonical tests + curated examples actually on disk.
            shipped = []
            for sub in ("tests", "examples"):
                d_sub = d / sub
                if d_sub.exists():
                    for f in sorted(d_sub.glob(f"*{ext}")):
                        shipped.append(f.stem)
            out.append({
                "name": d.name,
                "ext": ext,
                "options": opts,
                "shipped": sorted(set(shipped)),
                "origin_story": origin_story,
                "theme_sources": theme_sources,
                "theme_tokens": theme_tokens,
                "lineage": lineage,
                "persona": persona,
                "era": era,
                "keyword_theme": keyword_theme,
            })
        return jsonify({"languages": out})

    @app.route("/api/create", methods=["POST"])
    def create():
        data = request.get_json(force=True)
        opts = {
            "syntax": data["syntax"],
            "typing": data["typing"],
            "memory": data["memory"],
        }
        # Extended options from forge-extended-options.md +
        # language-generation-design-decisions.md (naming_convention, null_model).
        for k in ("comment_style", "string_literals", "numeric_literals",
                  "default_mutability", "error_handling", "multiple_returns",
                  "boolean_evaluation",
                  "naming_convention", "null_model"):
            v = data.get(k)
            if v is not None and v != "":
                opts[k] = v
        if isinstance(data.get("loop_forms"), list) and data["loop_forms"]:
            opts["loop_forms"] = data["loop_forms"]
        name = data["name"].strip()
        if not name.isidentifier():
            return jsonify({"error": "name must be a valid Python identifier"}), 400
        provider = data.get("provider") or None
        # Customization is optional. The frontend builds it from the Advanced
        # section (keyword overrides, operator overrides, extra notes, etc.).
        customization = data.get("customization") or {}
        if customization:
            try:
                _validate_customization(customization)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

        # Coherence pre-check. Blocks impossible combos before we even
        # spawn the worker thread. Warnings still propagate via design_notes.
        from forge.orchestrator.coherence import check, errors as _coherence_errors
        opts_for_check = dict(opts)
        opts_for_check["feature_bans"] = data.get("feature_bans") or []
        coherence_issues = _coherence_errors(check(opts_for_check))
        if coherence_issues:
            return jsonify({
                "error": "These option choices contradict each other.",
                "coherence_errors": [
                    {"code": i.code, "message": i.message, "suggestion": i.suggestion}
                    for i in coherence_issues
                ],
            }), 400

        # Speculative-features metadata
        persona = data.get("persona") or None
        era = data.get("era") or None
        keyword_theme = data.get("keyword_theme") or None
        feature_bans = data.get("feature_bans") or []
        hostile_constraints = data.get("hostile_constraints") or None
        # docs_persona lives inside customization (it only affects one prompt)
        docs_persona = data.get("docs_persona") or None
        if docs_persona:
            customization = customization or {}
            customization["docs_persona"] = docs_persona

        # Natural-language phrasebook (from preset key + optional overrides)
        phrasebook = data.get("phrasebook") or None
        natural_language = data.get("natural_language") or None

        job = Job(
            opts=opts, name=name, provider=provider,
            customization=customization,
            persona=persona, era=era,
            keyword_theme=keyword_theme,
            feature_bans=feature_bans if isinstance(feature_bans, list) else [],
            hostile_constraints=hostile_constraints,
            phrasebook=phrasebook,
            natural_language=natural_language,
        )
        register_job(job)
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return jsonify({"job_id": job.id})

    @app.route("/api/personas")
    def personas_list():
        from forge.orchestrator.personas import list_personas
        return jsonify({"personas": list_personas()})

    @app.route("/api/eras")
    def eras_list():
        from forge.orchestrator.presets import list_eras
        return jsonify({"eras": list_eras()})

    @app.route("/api/themes")
    def themes_list():
        from forge.orchestrator.themes import list_themes
        return jsonify({"themes": list_themes()})

    @app.route("/api/bans")
    def bans_list():
        from forge.orchestrator.bans import list_bans
        return jsonify({"bans": list_bans()})

    # ------------------- Kata system + AI pair programmer -------------------

    @app.route("/api/katas/<lang>", methods=["GET"])
    def get_katas(lang):
        """Return the saved kata pack for a language, or 404 if none yet."""
        from forge.orchestrator.katas import load_pack
        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        pack = load_pack(lang_dir)
        if pack is None:
            return jsonify({"error": "no katas generated yet for this language"}), 404
        return jsonify(pack)

    @app.route("/api/katas/<lang>/generate", methods=["POST"])
    def generate_katas_endpoint(lang):
        """Fire a fresh kata-generation pass. Self-validates each kata
        against the language's compiler. Drops failures."""
        from forge.orchestrator.katas import generate_katas, AllKatasDroppedError
        from forge.orchestrator.providers import make_client
        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        spec_path = lang_dir / "resolved_spec.json"
        if not spec_path.exists():
            return jsonify({"error": "language has no resolved_spec.json"}), 400
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        provider = (request.get_json(silent=True) or {}).get("provider")
        try:
            client = make_client(provider, log_dir=lang_dir / ".forge_log")
            pack = generate_katas(spec, lang_dir, client)
            return jsonify(pack)
        except AllKatasDroppedError as e:
            # Return the pack (with empty katas + drop list) so the GUI can
            # render the diagnostic in the kata pane instead of just a toast.
            return jsonify({
                "error": str(e),
                "pack": getattr(e, "pack", None),
            }), 422
        except Exception as e:
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    @app.route("/api/kata-packs", methods=["GET"])
    def list_kata_packs():
        """List the curated, hand-written kata packs (LeetCode classics, etc.).
        These don't require an LLM call — they ship with the app and are
        self-validated against the target language at load time."""
        from forge.orchestrator.kata_packs import list_packs
        return jsonify({"packs": list_packs()})

    @app.route("/api/katas/<lang>/load-pack/<pack_key>", methods=["POST"])
    def load_kata_pack(lang, pack_key):
        """Load a curated pack into <lang>/katas.json.

        Each kata's reference solution is run through the language's actual
        compiler. Failures are dropped (with their reason recorded), survivors
        are saved. If every kata is dropped we return 422 + the diagnostic
        pack so the GUI can render which katas failed and why — same contract
        as /api/katas/<lang>/generate."""
        from forge.orchestrator.kata_packs import get_pack
        from forge.orchestrator.katas import _self_validate

        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        spec_path = lang_dir / "resolved_spec.json"
        if not spec_path.exists():
            return jsonify({"error": "language has no resolved_spec.json"}), 400
        spec = json.loads(spec_path.read_text(encoding="utf-8"))

        # Stack-based families get a curated postfix-friendly pack instead
        # of the c_like classics. `classics` would drop every kata on a
        # Forth-flavored language because `var x = list()` and pointer-
        # heavy collection problems just don't translate to stack form.
        # Auto-redirect to `stack_classics` so the user gets a working
        # pack with one click rather than wading through 12 drops.
        if pack_key == "classics" and spec.get("options", {}).get("syntax") == "stack_based":
            pack_key = "stack_classics"

        pack_template = get_pack(pack_key)
        if pack_template is None:
            return jsonify({"error": f"no such pack: {pack_key}"}), 404

        # For the classics pack: pick the variant best suited to this
        # language's constraints. `no_mutation` languages get the recursion-
        # only variant (same problems and tests, recursion-based references)
        # so they can run the full pack mechanically.
        if pack_key == "classics":
            from forge.orchestrator.kata_packs import get_classics_for
            pack_template["katas"] = get_classics_for(spec)

        # `?strict=true` disables LLM-translation fallback — useful for
        # testing the pre-flight rejection logic without firing the LLM.
        # Production callers (GUI Load button) leave it off so the endpoint
        # transparently translates when a language is incompatible.
        strict_mode = request.args.get("strict", "").lower() in ("1", "true", "yes")
        # `?force=true` skips the cache (re-runs validation/translation).
        force = request.args.get("force", "").lower() in ("1", "true", "yes")

        # Cache check FIRST. Compute the content hash of the source pack
        # and compare against the saved katas.json's stamp. On match we
        # return the cached pack without any of the expensive downstream
        # work (runtime patching, validation, subprocess spawns). This
        # is what makes the cached path feel instant in the GUI.
        import hashlib
        pack_hash = hashlib.sha256(
            json.dumps(pack_template, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        if not force:
            existing = lang_dir / "katas.json"
            if existing.exists():
                try:
                    cached = json.loads(existing.read_text(encoding="utf-8"))
                    cached_src = cached.get("source", "")
                    cached_hash = cached.get("pack_hash", "")
                    src_match = (cached_src == f"curated:{pack_key}"
                                 or cached_src == f"translated:{pack_key}")
                    hash_match = cached_hash == pack_hash
                    if src_match and hash_match and cached.get("katas"):
                        cached["cached"] = True
                        return jsonify(cached)
                except Exception:
                    pass  # corrupt cache; fall through and regenerate

        # ON CACHE MISS: patch the language's runtime to support string
        # indexing if it doesn't already (some generated languages raise
        # TypeError on `get(string, int)` while toylang's reference
        # handles it). Idempotent + surgical - string-iteration classics
        # (valid_parens, anagram, longest_unique_substring) need this.
        # Moved here from before the cache check so cached returns
        # don't pay the runtime-scan cost.
        from forge.orchestrator.mechanical_translator import (
            ensure_runtime_string_support, ensure_stack_runtime_support,
        )
        try:
            ensure_runtime_string_support(lang_dir)
        except Exception:
            pass  # best-effort; falls back to LLM/stub if it didn't help
        # For stack_based languages: idempotently inject the canonical
        # forthlang vocabulary (nil/true/false/list/dict/get/dset/etc.)
        # into the runtime + typechecker + codegen so curated
        # stack_classics references compile against any stack_based
        # language's pipeline. Without this patch, the linked-list /
        # tree katas drop on languages whose phrasebook customization
        # renamed these words (e.g. `stacky` only ships `void`/`verum`/
        # `falsum`). The patch is marker-bracketed and idempotent.
        if spec.get("options", {}).get("syntax") == "stack_based":
            try:
                ensure_stack_runtime_support(lang_dir)
            except Exception:
                pass  # best-effort

        # Decide the path: direct (instant) or LLM translation (slow but
        # works on customized languages). We prefer direct whenever the
        # language is plausibly compatible — most c_like languages are.
        pack_family = pack_template.get("syntax_family")
        lang_family = spec.get("options", {}).get("syntax")
        cust = spec.get("customization") or {}
        nl = cust.get("natural_language") or spec.get("natural_language")
        bans = (cust.get("feature_bans") or spec.get("feature_bans") or [])
        # `no_mutation` and `no_loops` are handled by the recursive
        # classics variant we just picked above (when pack_key=="classics").
        # So they don't force LLM translation as long as we're loading
        # classics; for other packs they would. In strict mode (test-only
        # opt-in) we DO treat them as forcing translation so the rejection
        # path can be tested without firing the LLM.
        recursive_handled_bans = pack_key == "classics" and not strict_mode
        bans_force_translation = (
            ("no_mutation" in bans and not recursive_handled_bans)
            or ("no_loops" in bans and not recursive_handled_bans)
        )
        # Templated families (stack_based, s_expression) get their syntax
        # from a hand-written reference compiler, NOT from the spec's
        # natural-language phrasebook. So a `customization.natural_language`
        # on a stacky-flavored language (e.g. "let it be known that x is 0")
        # is irrelevant to the actual Forth-like keywords (`: ;` `dup` `drop`).
        # The bridge pipeline rescues any kata that doesn't match directly,
        # and curated stack_classics references already speak the right
        # dialect. Skipping LLM translation here turns a 10-minute reload
        # (13 katas x ~45s LLM call) into a <3s direct load.
        templated_family = lang_family in ("stack_based", "s_expression")
        nl_forces_translation = bool(nl and isinstance(nl, dict) and nl) and not templated_family
        # Hard incompatibility signals. If any of these are true, direct
        # load is guaranteed to drop everything; skip straight to translation.
        needs_translation = bool(
            (pack_family and lang_family and pack_family != lang_family)
            or nl_forces_translation
            or bans_force_translation
        )
        # Strict mode: if hard-incompatible, refuse with 400 instead of
        # falling through to translation.
        if strict_mode and needs_translation:
            if pack_family and lang_family and pack_family != lang_family:
                msg = (f"`{lang}` is `{lang_family}`, but the pack is "
                       f"`{pack_family}`.")
            elif nl_forces_translation:
                msg = (f"`{lang}` uses a natural-language phrasebook (e.g. "
                       f"`{(nl.get('var_decl') or 'make x equal 0.')[:50]}`).")
            elif "no_mutation" in bans:
                msg = f"`{lang}` bans `no_mutation`."
            else:
                msg = f"`{lang}` bans `no_loops`."
            return jsonify({"error": (
                f"{msg} Without translation this pack would drop every kata. "
                f"Drop `?strict=true` to enable LLM translation."
            )}), 400

        templates = pack_template["katas"]
        results: list[tuple[dict, bool, str]] = []
        used_translation = False

        if not needs_translation:
            # Fast path: ONE batched compile+run for the whole pack.
            from forge.orchestrator.katas import _batch_validate
            from forge.orchestrator.mechanical_translator import _rederive_expected
            from concurrent.futures import ThreadPoolExecutor
            batched = _batch_validate(templates, lang_dir, spec)
            if batched is not None:
                results = batched
            else:
                # Per-kata parallel fallback for drop pinpointing.
                with ThreadPoolExecutor(max_workers=min(8, len(templates) or 1)) as ex:
                    futures = [ex.submit(_self_validate, k, lang_dir, spec) for k in templates]
                    for kata, fut in zip(templates, futures):
                        ok, reason = fut.result()
                        results.append((kata, ok, reason))
            # For any kata that failed direct validation, try re-deriving
            # expected outputs by running the reference. This absorbs print-
            # formatter differences (e.g. democ prints list("a") as ['a']
            # but the curated kata expects [a] from toylang's formatter).
            for i, (kata, ok, reason) in enumerate(results):
                if ok:
                    continue
                rederived = _rederive_expected(kata, spec, lang_dir)
                if rederived is None:
                    continue
                ok2, reason2 = _self_validate(rederived, lang_dir, spec)
                if ok2:
                    results[i] = (rederived, True, "rederived")
            # If direct load lost MORE THAN HALF the pack, fall through to
            # translation. The remaining katas might be salvageable that way
            # AND the user wants the full pack, not a stripped one. Skip this
            # for empty packs (degenerate edge case) — translation can't help.
            #
            # SKIP for stack_based: the bridge pipeline (cascade-of-cases
            # + curated_match) rescues failed katas mechanically, so we
            # never want to drop into a 13-kata x 45s LLM loop here.
            # Without this guard, loading stack_classics on a stack_based
            # language with <50% direct pass-rate (e.g. `stacky` whose
            # pirate phrasebook customization changes some operator
            # spellings) would silently kick off >10 minutes of LLM calls.
            is_stack_based_lang = lang_family == "stack_based"
            if templates and not is_stack_based_lang:
                survival = sum(1 for _, ok, _ in results if ok)
                if survival < max(1, len(templates) // 2):
                    needs_translation = True
                    results = []  # discard direct results; translation will redo

        if needs_translation:
            # LLM-translate each kata into this language's dialect.
            from forge.orchestrator.kata_translator import translate_pack
            from forge.orchestrator.providers import make_client
            try:
                client = make_client(
                    (request.get_json(silent=True) or {}).get("provider"),
                    log_dir=lang_dir / ".forge_log",
                )
                translated = translate_pack(pack_template, spec, lang_dir, client)
                used_translation = True
                # `translate_pack` returns valid + dropped already partitioned;
                # rebuild the (kata, ok, reason) results list to feed the same
                # downstream code.
                for k in translated["katas"]:
                    results.append((k, True, "ok"))
                for d in translated["dropped"]:
                    results.append(({"id": d["id"]}, False, d["reason"]))
            except Exception as e:
                return jsonify({
                    "error": (
                        f"Couldn't translate the `{pack_key}` pack to "
                        f"`{lang}`: {type(e).__name__}: {e}. "
                        f"You can still try ✨ Generate to make a fresh pack."
                    ),
                }), 500

        valid = []
        dropped = []
        # Rescue ladder for any kata whose reference doesn't pass its own
        # tests:
        #   0. (stack_based only) base-solution bridge: cascade-of-cases
        #      OR curated substitute. Guarantees a working reference for
        #      any kata with primitive-arg tests OR a function_name that
        #      matches the curated stack_classics pack. ALWAYS attempted
        #      first on stack_based so users never see "no auto-check".
        #   1. mechanical case-analysis (cascade of if-args-match returns,
        #      always works on Turing-complete c_like targets); auto-check works
        #   2. stub-rescue (empty tests + stub reference; no auto-check)
        # The bridge pipeline replaces #2 for stack_based: dropping over
        # stubbing because we never want a "no auto-check" kata.
        #
        # Also tag validation status from existing rescue evidence to
        # avoid a redundant subprocess pass per kata at load time.
        from forge.orchestrator.kata_translator import _stub_rescue
        from forge.orchestrator.case_analysis import build_case_analysis_kata
        from forge.orchestrator.stack_base_solution import build_base_solution
        toylang_dir = WORKSPACE / "generated" / "toylang"
        is_stack_based = spec.get("options", {}).get("syntax") == "stack_based"

        for kata, ok, reason in results:
            if ok:
                # Already validated upstream (batched or per-kata);
                # tests_passed == tests_run by definition of "ok".
                kata["validation"] = {
                    "status": "verified",
                    "tests_run": len(kata.get("tests", [])),
                    "tests_passed": len(kata.get("tests", [])),
                }
                valid.append(kata)
                continue

            # stack_based: try the bridge pipeline FIRST. Cascade or
            # curated-substitute almost always produces a working
            # reference. This is what eliminates "no auto-check".
            if is_stack_based:
                bridged = build_base_solution(kata, spec, lang_dir)
                if bridged is not None:
                    valid.append(bridged)
                    continue

            try:
                ca = build_case_analysis_kata(kata, spec, lang_dir, toylang_dir)
            except Exception:
                ca = None
            if ca is not None:
                # case_analysis re-derives expected outputs by running
                # the cascade reference and saving its actual stdout,
                # so by construction every test passes.
                ca["validation"] = {
                    "status": "verified",
                    "tests_run": len(ca.get("tests", [])),
                    "tests_passed": len(ca.get("tests", [])),
                    "via": "case_analysis_fallback",
                }
                valid.append(ca)
                continue

            # Last resort: stub-rescue. SKIPPED for stack_based - we'd
            # rather drop than ship a "no auto-check" kata there.
            if not is_stack_based:
                rescued = _stub_rescue(kata, spec)
                if rescued is not None:
                    rescued["validation"] = {
                        "status": "stub",
                        "tests_run": 0,
                        "tests_passed": 0,
                        "reason": "stub-rescued; reference is a starter only",
                    }
                    valid.append(rescued)
                    continue

            dropped.append({"id": kata.get("id"), "reason": reason,
                            "fix_attempts": 0})

        source_tag = f"translated:{pack_key}" if used_translation else f"curated:{pack_key}"
        out_pack = {
            "lang": spec["lang_name"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": source_tag,
            "pack_hash": pack_hash,  # invalidates cache when source pack changes
            "title": pack_template.get("title", pack_key),
            "katas": valid,
            "dropped": dropped,
        }
        from forge.orchestrator.katas import atomic_write_json
        atomic_write_json(lang_dir / "katas.json", out_pack)
        if not valid:
            return jsonify({
                "error": (
                    f"All {len(dropped)} katas in pack `{pack_key}` failed "
                    f"self-validation against `{lang}`. First drop: "
                    f"{dropped[0]['reason'] if dropped else 'unknown'}"
                ),
                "pack": out_pack,
            }), 422
        return jsonify(out_pack)

    @app.route("/api/katas/<lang>/<kata_id>/check", methods=["POST"])
    def check_kata(lang, kata_id):
        """Run the user's solution against the named kata.

        Request JSON:
          code: the user's submission (required)
          mode: 'run' (sample tests, all-or-nothing visibility) or
                'submit' (full hidden suite, first-failure-only).
                Defaults to 'submit' for backwards compat.

        Returns:
          - mode=run: pass/fail per sample test, full results visible
          - mode=submit: passed=True iff all hidden tests pass; on fail,
            shows just the first failing test (no spoilers).
        """
        from forge.orchestrator.katas import load_pack, check_solution
        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        pack = load_pack(lang_dir)
        if pack is None:
            return jsonify({"error": "no kata pack"}), 404
        kata = next((k for k in pack["katas"] if k["id"] == kata_id), None)
        if kata is None:
            return jsonify({"error": f"no kata named {kata_id}"}), 404
        spec = json.loads((lang_dir / "resolved_spec.json").read_text(encoding="utf-8"))
        body = request.get_json(force=True) or {}
        user_code = body.get("code", "")
        mode = (body.get("mode") or "submit").lower()
        if not user_code.strip():
            return jsonify({"passed": False, "stage": "empty",
                           "stderr": "your code is empty"})

        if mode == "run":
            # Pre-flight: catch obvious copy/paste corruption with a
            # human-friendly message before wrapping + compiling.
            from forge.orchestrator.katas import preflight_check
            pre = preflight_check(user_code, spec)
            if pre is not None:
                return jsonify({
                    "mode": "run",
                    "passed": False,
                    "stage": pre["stage"],
                    "stderr": pre["stderr"],
                    "results": [],
                })

            # Run mode: only run the SAMPLE tests (visible to user).
            # Show full per-test results so they can iterate. Fall back to
            # the first test if `sample_test_indices` is missing.
            sample_idxs = kata.get("sample_test_indices") or [0]
            sample_tests = [kata["tests"][i] for i in sample_idxs
                            if 0 <= i < len(kata["tests"])]
            kata_for_run = dict(kata)
            kata_for_run["tests"] = sample_tests
            from forge.orchestrator.katas import _wrap_with_test_prints, _compile_and_run
            helpers = kata.get("helpers", "")
            program = _wrap_with_test_prints(user_code, sample_tests, spec, helpers=helpers)
            res = _compile_and_run(lang_dir, program, spec["file_extension"])
            if not res["ok"]:
                # Include the wrapped program so users can see what was
                # actually compiled (helpers + their code + test prints).
                # This is the single most useful debugging signal: many
                # "compile error" complaints turn out to be the helpers
                # introducing a name conflict or the wrap inserting an
                # unexpected newline. Cap at ~80 lines so the response stays
                # small.
                program_lines = program.splitlines()
                excerpt = "\n".join(program_lines[:80])
                if len(program_lines) > 80:
                    excerpt += f"\n... ({len(program_lines) - 80} more lines)"
                return jsonify({
                    "mode": "run",
                    "passed": False,
                    "stage": res["stage"],
                    "stderr": res.get("stderr", ""),
                    "results": [],
                    "program_excerpt": excerpt,
                })
            actual_lines = res["stdout"].splitlines()
            results = []
            all_passed = True
            for i, t in enumerate(sample_tests):
                actual = actual_lines[i].rstrip() if i < len(actual_lines) else ""
                ok = actual == t["expected"].rstrip()
                if not ok:
                    all_passed = False
                results.append({
                    "call": t["call"],
                    "expected": t["expected"],
                    "actual": actual,
                    "passed": ok,
                })
            return jsonify({
                "mode": "run",
                "passed": all_passed,
                "stage": "ok" if all_passed else "compare",
                "results": results,
                "total": len(sample_tests),
            })

        # Submit mode: existing behavior (first-failure-only over all tests).
        result = check_solution(spec, lang_dir, kata, user_code)
        result["mode"] = "submit"
        return jsonify(result)

    @app.route("/api/chat/<lang>", methods=["POST"])
    def chat_endpoint(lang):
        """One round of chat with the language-aware pair programmer.

        Request body:
          message:        the user's new message (required)
          history:        prior messages [{role: 'user'|'assistant', content: str}]
          provider:       optional, default auto
          kata_id:        optional, makes the pair programmer kata-aware
          current_code:   optional, user's draft solution
          mode:           'hint' (default) | 'solution'
        """
        from forge.orchestrator.pair_programmer import chat
        from forge.orchestrator.providers import make_client
        from forge.orchestrator.katas import load_pack

        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        spec = json.loads((lang_dir / "resolved_spec.json").read_text(encoding="utf-8"))

        data = request.get_json(force=True)
        user_msg = (data.get("message") or "").strip()
        if not user_msg:
            return jsonify({"error": "empty message"}), 400
        history = data.get("history") or []
        provider = data.get("provider")
        mode = data.get("mode") or "hint"
        current_code = data.get("current_code") or ""

        kata = None
        kata_id = data.get("kata_id")
        if kata_id:
            pack = load_pack(lang_dir)
            if pack:
                kata = next((k for k in pack["katas"] if k["id"] == kata_id), None)

        try:
            client = make_client(provider, log_dir=lang_dir / ".forge_log")
            result = chat(spec, lang_dir, user_msg, history, client,
                          kata=kata, current_code=current_code, mode=mode)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    @app.route("/api/phrasebooks")
    def phrasebooks_list():
        from forge.orchestrator.phrasebooks import list_phrasebooks, PHRASEBOOKS
        return jsonify({
            "phrasebooks": list_phrasebooks(),
            "templates": PHRASEBOOKS,    # full data so the GUI can preview
        })

    @app.route("/api/surprise", methods=["POST"])
    def surprise():
        """Surprise-me mode: ask Claude to pick everything from a vibe word."""
        data = request.get_json(force=True)
        vibe = (data.get("vibe") or "").strip()
        name = (data.get("name") or "").strip()
        if not name or not name.isidentifier():
            return jsonify({"error": "name must be a valid identifier"}), 400
        if not vibe:
            return jsonify({"error": "vibe is required"}), 400
        provider = data.get("provider") or None

        # Picker schema: what the LLM must return.
        picker_schema = {
            "type": "object",
            "required": ["options", "name", "design_notes"],
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {
                        "syntax": {"enum": ["c_like", "python_like", "s_expression", "stack_based"]},
                        "typing": {"enum": ["static", "dynamic"]},
                        "memory": {"enum": ["host_gc", "refcount"]},
                        "comment_style": {"enum": ["line", "block", "both", "nestable_block"]},
                        "string_literals": {"enum": ["single", "double", "both", "triple_quoted", "raw_and_normal"]},
                        "numeric_literals": {"enum": ["decimal_only", "c_style", "extended"]},
                        "default_mutability": {"enum": ["mutable", "immutable"]},
                        "error_handling": {"enum": ["panic_only", "exceptions", "result_type"]},
                        "loop_forms": {"type": "array", "items": {"enum": ["while", "c_for", "foreach", "repeat_until", "loop_break"]}},
                        "multiple_returns": {"enum": ["none", "tuple", "named"]},
                        "boolean_evaluation": {"enum": ["short_circuit", "eager"]},
                    },
                    "required": ["syntax", "typing", "memory"],
                },
                "persona": {"enum": ["dijkstra", "mccarthy", "hickey", "stroustrup", "wirth", "wadler", "matz", "ousterhout"]},
                "era": {"enum": ["1960s", "1970s", "1980s", "2000s", "2020s"]},
                "keyword_theme": {"enum": ["pirate", "shakespearean", "corporate", "latin", "cozy", "none"]},
                "feature_bans": {"type": "array", "items": {"type": "string"}},
                "name": {"type": "string"},
                "origin_story": {"type": "string", "description": "1-3 sentences of fictional origin"},
                "design_notes": {"type": "array", "items": {"type": "string"}},
                "docs_persona": {"enum": ["technical", "academic_paper", "tutorial_with_exercises", "historical_fiction", "pirate"]},
            },
        }

        prompt = (
            f"The user wants a programming language with the vibe: \"{vibe}\".\n"
            f"They suggested the name `{name}` (use it as-is).\n\n"
            "Choose every option from the schema. Be opinionated. The "
            "language must be coherent: every choice should reinforce the "
            "vibe. Pick a designer persona whose values match. Optionally "
            "pick an era preset, a keyword theme, and one or two feature "
            "bans that sharpen the language's character.\n\n"
            "Write a 1-3 sentence fictional origin story (origin_story) "
            "as if the language were a real obscure project from the 1990s "
            "or 2000s. Add 3-6 design_notes explaining the vibe-driven "
            "choices.\n\n"
            "## Hard rules (read carefully)\n"
            "- Use ONLY the property names listed in the schema.\n"
            "- For Lisp-style vibes, the syntax value is `s_expression` "
            "  (with an underscore). NOT `s-expression`, `lisp`, or `sexp`.\n"
            "- For garbage-collected memory, the value is `host_gc` (NOT "
            "  `gc`, `garbage_collected`, or `tracing`).\n"
            "- Property names: `syntax`, `typing`, `memory`, `persona`, "
            "  `era`, `keyword_theme`, `feature_bans`. Do NOT use "
            "  `era_preset`, `designer_persona`, `paradigm`, `type_system`, "
            "  `syntax_style`, `evaluation`, `mutability`, or any other "
            "  invented field names.\n"
            "- `feature_bans` values are: `no_loops`, `no_mutation`, "
            "  `no_classes`, `no_exceptions`, `no_global_state`, `no_null`. "
            "  NOT bare `loops` / `mutation` / `null` / `goto`.\n\n"
            "## Example response shape\n"
            "```json\n"
            "{\n"
            '  "name": "myling",\n'
            '  "options": {\n'
            '    "syntax": "s_expression",\n'
            '    "typing": "dynamic",\n'
            '    "memory": "host_gc",\n'
            '    "default_mutability": "immutable",\n'
            '    "boolean_evaluation": "short_circuit"\n'
            "  },\n"
            '  "persona": "mccarthy",\n'
            '  "era": "1960s",\n'
            '  "keyword_theme": "latin",\n'
            '  "feature_bans": ["no_mutation"],\n'
            '  "origin_story": "A 1968 academic dialect from MIT...",\n'
            '  "design_notes": ["Homoiconic.", "Immutable bindings."]\n'
            "}\n"
            "```\n\n"
            "Honesty rule: every value must appear in the schema's enum "
            "lists verbatim. If you can't find a perfect match, pick the "
            "closest legal value rather than inventing one."
        )

        try:
            from forge.orchestrator.providers import make_client
            log_dir = WORKSPACE / "generated" / name / ".forge_log"
            client = make_client(provider, log_dir=log_dir)
            picked = client.call_json(prompt, picker_schema, tag="surprise")
        except Exception as e:
            return jsonify({
                "error": (
                    "Surprise picker couldn't produce a valid spec. The model "
                    "kept returning fields that don't exist in our schema. "
                    f"Internal: {e}. Try again, simplify the vibe word, or "
                    "use the regular Create form."
                ),
            }), 500

        # Post-validation normalization. Even with the tightened prompt, the
        # LLM occasionally writes `s-expression` (hyphenated) or `gc` instead
        # of the schema's exact enum spelling. Map the common mistakes back
        # to canonical values before we trust the dict.
        picked = _normalize_surprise_picks(picked)

        opts = picked["options"]
        # Stash the LLM's origin story + design notes into customization
        customization = {
            "extra_design_notes": [picked.get("origin_story", "")] + (picked.get("design_notes") or []),
        }
        if picked.get("docs_persona"):
            customization["docs_persona"] = picked["docs_persona"]

        kt = picked.get("keyword_theme")
        if kt == "none":
            kt = None

        job = Job(
            opts=opts, name=name, provider=provider,
            customization=customization,
            persona=picked.get("persona"),
            era=picked.get("era"),
            keyword_theme=kt,
            feature_bans=picked.get("feature_bans") or [],
        )
        register_job(job)
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return jsonify({
            "job_id": job.id,
            "name": name,
            "picks": picked,
        })

    @app.route("/api/crossbreed", methods=["POST"])
    def crossbreed_endpoint():
        """Roadmap §3.3: cross two existing languages into a child.

        Request JSON:
          parent_a:    name of an existing language in `generated/`
          parent_b:    name of an existing language in `generated/`
          child_name:  identifier for the new language
          strategy:    'random' | 'dominant' | 'union' (default 'random')
          seed:        optional int, makes the random merge reproducible
          provider:    optional LLM provider override

        Returns: {job_id, name, lineage} once the spawn-and-go thread is
        running, just like /api/create. The streaming endpoint is the same
        (/api/stream/<job_id>).
        """
        from forge.orchestrator.crossbreeding import crossbreed
        data = request.get_json(force=True) or {}
        parent_a = (data.get("parent_a") or "").strip()
        parent_b = (data.get("parent_b") or "").strip()
        child_name = (data.get("child_name") or "").strip()
        strategy = (data.get("strategy") or "random").strip()
        seed = data.get("seed")
        provider = data.get("provider") or None

        if not (parent_a and parent_b and child_name):
            return jsonify({"error": "parent_a, parent_b, child_name required"}), 400
        if not child_name.isidentifier():
            return jsonify({"error": "child_name must be a valid Python identifier"}), 400
        if parent_a == parent_b:
            return jsonify({"error": "parents must be different"}), 400
        if strategy not in {"random", "dominant", "union"}:
            return jsonify({"error": "strategy must be random|dominant|union"}), 400

        existing = WORKSPACE / "generated" / child_name
        if existing.exists():
            return jsonify({"error": f"`{child_name}` already exists. Pick a new name."}), 400

        def _load_parent_meta(name: str) -> Optional[dict]:
            spec_path = WORKSPACE / "generated" / name / "resolved_spec.json"
            if not spec_path.exists():
                return None
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
            except Exception:
                return None
            cust = spec.get("customization") or {}
            return {
                "name": spec.get("lang_name") or name,
                "options": spec.get("options") or {},
                "persona": cust.get("persona"),
                "era": cust.get("era"),
                "keyword_theme": cust.get("keyword_theme"),
                "phrasebook": (cust.get("natural_language") and "custom") or None,
                "feature_bans": cust.get("feature_bans") or [],
                "customization": cust,
                "lineage": spec.get("lineage"),
            }

        meta_a = _load_parent_meta(parent_a)
        meta_b = _load_parent_meta(parent_b)
        if meta_a is None:
            return jsonify({"error": f"no spec for parent_a `{parent_a}`"}), 404
        if meta_b is None:
            return jsonify({"error": f"no spec for parent_b `{parent_b}`"}), 404

        try:
            child = crossbreed(meta_a, meta_b, child_name=child_name,
                               strategy=strategy,
                               seed=int(seed) if seed is not None else None)
        except Exception as e:
            return jsonify({"error": f"crossbreed failed: {e}"}), 500

        # Coherence pre-check on the merged options. If the merge produced
        # a contradictory combo, fall back to dominant (parent_a wins).
        from forge.orchestrator.coherence import check, errors as _coh_errors
        opts_for_check = dict(child["options"])
        opts_for_check["feature_bans"] = child.get("feature_bans") or []
        if _coh_errors(check(opts_for_check)):
            child = crossbreed(meta_a, meta_b, child_name=child_name,
                               strategy="dominant",
                               seed=int(seed) if seed is not None else None)
            if _coh_errors(check({**child["options"],
                                  "feature_bans": child.get("feature_bans") or []})):
                return jsonify({
                    "error": "These two languages can't be coherently crossed. "
                             "Try a different parent pair.",
                }), 422

        # Required MVP fields might still be missing if neither parent had
        # them set; backfill with the defaults the create flow would have used.
        opts = dict(child["options"])
        opts.setdefault("syntax", meta_a["options"].get("syntax") or "c_like")
        opts.setdefault("typing", meta_a["options"].get("typing") or "dynamic")
        opts.setdefault("memory", meta_a["options"].get("memory") or "host_gc")

        # Stash the seed onto the lineage block so the merge is reproducible
        if seed is not None:
            child["lineage"]["seed"] = int(seed)

        job = Job(
            opts=opts, name=child_name, provider=provider,
            customization=child.get("customization") or {},
            persona=child.get("persona"),
            era=child.get("era"),
            keyword_theme=child.get("keyword_theme"),
            feature_bans=child.get("feature_bans") or [],
            phrasebook=child.get("phrasebook"),
            lineage=child["lineage"],
        )
        register_job(job)
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return jsonify({
            "job_id": job.id,
            "name": child_name,
            "lineage": child["lineage"],
        })

    @app.route("/api/family-tree")
    def family_tree():
        """Return the lineage graph across every language in `generated/`.

        Output shape:
          {
            "nodes": [{name, persona, era, keyword_theme, generation,
                       theme_tokens: {bg, text, accent}}, ...],
            "edges": [{parent, child, strategy}, ...],
          }
        Roots (generation 0, no parents) and leaves both included so the
        renderer can lay out a forest. Used by the Library family-tree view.
        """
        gen = WORKSPACE / "generated"
        nodes = []
        edges = []
        if not gen.exists():
            return jsonify({"nodes": nodes, "edges": edges})
        for d in sorted(gen.iterdir()):
            if not d.is_dir():
                continue
            spec_path = d / "resolved_spec.json"
            if not spec_path.exists():
                continue
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            cust = spec.get("customization") or {}
            lineage = spec.get("lineage") or {}
            tokens = (spec.get("theme") or {}).get("tokens") or {}
            nodes.append({
                "name": d.name,
                "persona": cust.get("persona"),
                "era": cust.get("era"),
                "keyword_theme": cust.get("keyword_theme"),
                "generation": int(lineage.get("generation") or 0),
                "theme_tokens": {
                    k: tokens[k] for k in ("bg", "text", "accent")
                    if k in tokens
                },
            })
            for parent in (lineage.get("parents") or []):
                edges.append({
                    "parent": parent,
                    "child": d.name,
                    "strategy": lineage.get("strategy") or "random",
                })
        return jsonify({"nodes": nodes, "edges": edges})

    @app.route("/api/stream/<job_id>")
    def stream(job_id):
        job = get_job(job_id)
        if job is None:
            return jsonify({"error": "no such job"}), 404

        def gen():
            yield "retry: 1000\n\n"
            saw_done = False
            while True:
                try:
                    msg = job.queue.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                    if msg.get("kind") == "done":
                        saw_done = True
                        return
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    if job.done and job.queue.empty():
                        # Defensive: if the worker thread crashed without
                        # emitting `done` (e.g. exception in the `finally`
                        # block, or a memory error during emit), surface
                        # a synthetic done so the frontend stops spinning.
                        # Without this, the GUI would show "running..."
                        # forever after a backend crash.
                        if not saw_done:
                            err = job.error or "worker exited without emitting done"
                            yield f"data: {json.dumps({'kind':'done','success':False,'error':err})}\n\n"
                        return

        resp = Response(gen(), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    @app.route("/api/run", methods=["POST"])
    def run_program():
        data = request.get_json(force=True)
        lang = data["lang"]
        source = data["source"]

        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": f"no such language: {lang}"}), 404

        # Discover extension.
        spec_path = lang_dir / "resolved_spec.json"
        ext = ".toy"
        if spec_path.exists():
            try:
                ext = json.loads(spec_path.read_text(encoding="utf-8")).get("file_extension", ext)
            except Exception:
                pass

        # Stash the source, run compile.py, then run the .out.py.
        scratch = lang_dir / "_playground"
        scratch.mkdir(exist_ok=True)
        src_path = scratch / f"program{ext}"
        src_path.write_text(source, encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(WORKSPACE / "generated") + os.pathsep + env.get("PYTHONPATH", "")

        try:
            compile_proc = subprocess.run(
                [sys.executable, str(lang_dir / "compile.py"), str(src_path)],
                capture_output=True, text=True, timeout=30, env=env, cwd=str(lang_dir),
            )
        except subprocess.TimeoutExpired:
            return jsonify({"stage": "compile", "stdout": "", "stderr": "compile timed out", "ok": False})

        if compile_proc.returncode != 0:
            hint = _explain_compile_error(compile_proc.stderr, lang_dir)
            return jsonify({
                "stage": "compile", "ok": False,
                "stdout": compile_proc.stdout, "stderr": compile_proc.stderr,
                "hint": hint,
            })

        out_py = src_path.with_suffix(src_path.suffix + ".out.py")
        try:
            run_proc = subprocess.run(
                [sys.executable, str(out_py)],
                capture_output=True, text=True, timeout=30, env=env, cwd=str(lang_dir),
            )
        except subprocess.TimeoutExpired:
            return jsonify({"stage": "run", "stdout": "", "stderr": "run timed out", "ok": False})

        return jsonify({
            "stage": "run", "ok": run_proc.returncode == 0,
            "stdout": run_proc.stdout, "stderr": run_proc.stderr,
            "transpiled": out_py.read_text(encoding="utf-8"),
        })

    @app.route("/api/run-all", methods=["POST"])
    def run_all():
        """Compare a sample across every language.

        Two modes:
          - example: each language runs its OWN shipped copy of the named
            example. Side-by-side comparison even when syntaxes differ.
          - source (legacy): same literal source on every language. Useful
            only when the languages share syntax (rare).
        """
        data = request.get_json(force=True)
        example = (data.get("example") or "").strip()
        source = data.get("source", "")
        only = data.get("langs")

        if not example and not source.strip():
            return jsonify({"error": "supply `example` or `source`"}), 400

        gen_root = WORKSPACE / "generated"
        results = {}
        for d in sorted(gen_root.iterdir()):
            if not d.is_dir():
                continue
            if only and d.name not in only:
                continue
            spec_path = d / "resolved_spec.json"
            if not spec_path.exists():
                continue
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                ext = spec.get("file_extension", ".toy")
            except Exception:
                ext = ".toy"

            # Pick the source per language.
            if example:
                src_path = None
                for sub in ("tests", "examples"):
                    candidate = d / sub / f"{example}{ext}"
                    if candidate.exists():
                        src_path = candidate
                        break
                if src_path is None:
                    results[d.name] = {
                        "ok": False, "stage": "skipped",
                        "stderr": f"`{example}` not shipped to {d.name}",
                    }
                    continue
                run_src = src_path.read_text(encoding="utf-8")
            else:
                scratch = d / "_playground"
                scratch.mkdir(exist_ok=True)
                src_path = scratch / f"runall{ext}"
                src_path.write_text(source, encoding="utf-8")
                run_src = source

            env = os.environ.copy()
            env["PYTHONPATH"] = str(WORKSPACE / "generated") + os.pathsep + env.get("PYTHONPATH", "")
            try:
                cp = subprocess.run(
                    [sys.executable, str(d / "compile.py"), str(src_path)],
                    capture_output=True, text=True, timeout=20, env=env, cwd=str(d),
                )
                if cp.returncode != 0:
                    results[d.name] = {
                        "ok": False, "stage": "compile",
                        "stderr": cp.stderr.strip().splitlines()[-1] if cp.stderr.strip() else "compile failed",
                        "source": run_src, "ext": ext,
                    }
                    continue
                out_py = src_path.with_suffix(src_path.suffix + ".out.py")
                rp = subprocess.run(
                    [sys.executable, str(out_py)],
                    capture_output=True, text=True, timeout=20, env=env, cwd=str(d),
                )
                results[d.name] = {
                    "ok": rp.returncode == 0,
                    "stage": "run" if rp.returncode != 0 else "ok",
                    "stdout": rp.stdout,
                    "stderr": rp.stderr.strip().splitlines()[-1] if rp.stderr.strip() else "",
                    "source": run_src, "ext": ext,
                }
            except subprocess.TimeoutExpired:
                results[d.name] = {"ok": False, "stage": "timeout", "stderr": "timed out"}
            except Exception as e:
                results[d.name] = {"ok": False, "stage": "error", "stderr": str(e)}
        return jsonify({"results": results, "example": example or None})

    @app.route("/api/example/<lang>/<example>")
    def example_program(lang, example):
        """Serve an example program for a specific language.

        Order of resolution:
          1. The language's own `tests/<name>.<ext>` (canonical test).
          2. The language's own `examples/<name>.<ext>` (compile-checked sample).
          3. (REMOVED) the global curated SAMPLES library. We used to fall
             back here, but that returned sources the language's parser
             might reject. The truth is what the language has actually
             shipped to disk.
        """
        lang_dir = WORKSPACE / "generated" / lang
        spec_path = lang_dir / "resolved_spec.json"
        ext = ".toy"
        if spec_path.exists():
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                ext = spec.get("file_extension", ext)
            except Exception:
                pass

        for sub in ("tests", "examples"):
            path = lang_dir / sub / f"{example}{ext}"
            if path.exists():
                return jsonify({"source": path.read_text(encoding="utf-8")})

        return jsonify({
            "error": (
                f"'{example}' isn't shipped to {lang}. The language's parser "
                "may not accept it. Try a sample from the language's "
                f"examples/ directory."
            )
        }), 404

    @app.route("/api/translate-comments", methods=["POST"])
    def translate_comments_endpoint():
        """Rewrite a source's comments to match a language's `comment_syntax`.

        Used by the playground's 'Convert comments' button when a user has
        c_like source loaded but the selected language uses `#` or `/* */`.
        """
        data = request.get_json(force=True)
        source = data.get("source", "")
        lang = data.get("lang", "")
        if not source or not lang:
            return jsonify({"error": "source and lang required"}), 400
        spec_path = WORKSPACE / "generated" / lang / "resolved_spec.json"
        if not spec_path.exists():
            return jsonify({"error": "no such language"}), 404
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception:
            return jsonify({"error": "could not read spec"}), 500
        from forge.orchestrator.generator import _translate_comments
        translated = _translate_comments(
            source,
            spec.get("options", {}).get("syntax", "c_like"),
            spec.get("comment_syntax") or {},
        )
        return jsonify({"source": translated})

    @app.route("/api/samples")
    def list_samples_endpoint():
        """Global list of curated sample names. The Playground dropdown
        narrows this per-language via /api/languages -> shipped[]."""
        from .samples import list_samples
        return jsonify({"samples": list_samples()})

    @app.route("/api/spec/<lang>")
    def spec_for(lang):
        path = WORKSPACE / "generated" / lang / "resolved_spec.json"
        if not path.exists():
            return jsonify({"error": "no spec"}), 404
        return jsonify(json.loads(path.read_text(encoding="utf-8")))

    @app.route("/api/review/<lang>")
    def review_for(lang):
        """Return the language's REVIEW.md (roadmap §4.6) if present.
        Library cards expose this behind a 'Review' link."""
        if not lang.isidentifier():
            return jsonify({"error": "invalid lang"}), 400
        path = WORKSPACE / "generated" / lang / "REVIEW.md"
        if not path.exists():
            return jsonify({"error": "no review yet — re-run create or "
                                     "POST /api/review/<lang> to generate"}), 404
        return jsonify({"review": path.read_text(encoding="utf-8")})

    @app.route("/api/review/<lang>", methods=["POST"])
    def review_run(lang):
        """Trigger a fresh critique on demand (for languages generated
        before the critic existed, or to refresh after a repair)."""
        from forge.orchestrator.critic import critique_language
        from forge.orchestrator.providers import make_client
        if not lang.isidentifier():
            return jsonify({"error": "invalid lang"}), 400
        lang_dir = WORKSPACE / "generated" / lang
        spec_path = lang_dir / "resolved_spec.json"
        if not spec_path.exists():
            return jsonify({"error": "no spec for this language"}), 404
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            client = make_client(log_dir=lang_dir / ".forge_log")
            review = critique_language(spec, lang_dir, client)
            if not review:
                return jsonify({"error": "critic produced no usable output"}), 500
            return jsonify({"review": review})
        except Exception as e:
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    @app.route("/api/theme/<lang>.css")
    def theme_for(lang):
        """Per-language CSS theme (roadmap §3.1).

        Backfills `<lang>/theme.css` on demand from the spec if it's missing
        or stale, then serves it as text/css. The GUI <link>'s this when a
        language is selected so the surface picks up the language's identity.
        """
        from flask import Response
        if not lang.isidentifier():
            return Response("/* invalid lang */", mimetype="text/css", status=400)
        lang_dir = (WORKSPACE / "generated" / lang).resolve()
        gen_root = (WORKSPACE / "generated").resolve()
        if not lang_dir.exists() or not lang_dir.is_relative_to(gen_root):
            return Response("/* no such language */", mimetype="text/css", status=404)
        theme_path = lang_dir / "theme.css"
        spec_path = lang_dir / "resolved_spec.json"
        if spec_path.exists():
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                from forge.orchestrator.style_tokens import (
                    style_tokens_for, render_theme_css,
                )
                tokens = (spec.get("theme") or {}).get("tokens")
                if not tokens:
                    # Backfill from sources (or fall through to default tokens)
                    sources = (spec.get("theme") or {}).get("sources") or {}
                    tokens = style_tokens_for(
                        persona=sources.get("persona"),
                        era=sources.get("era"),
                        theme=sources.get("keyword_theme"),
                        phrasebook=sources.get("phrasebook"),
                    )
                css = render_theme_css(tokens)
                theme_path.write_text(css, encoding="utf-8")
            except Exception:
                pass
        if theme_path.exists():
            return Response(theme_path.read_text(encoding="utf-8"),
                            mimetype="text/css",
                            headers={"Cache-Control": "no-store"})
        return Response("/* no theme */", mimetype="text/css", status=404)

    @app.route("/api/log/<lang>")
    def log_listing(lang):
        log_dir = WORKSPACE / "generated" / lang / ".forge_log"
        if not log_dir.exists():
            return jsonify({"entries": []})
        entries = []
        for f in sorted(log_dir.iterdir()):
            entries.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })
        return jsonify({"entries": entries})

    @app.route("/api/standalone/<lang>")
    def standalone_repl(lang):
        """Serve the single-HTML-file Pyodide REPL for a language.

        If `?download=1` is passed, sets a Content-Disposition: attachment
        header so the browser saves it as a file. Otherwise serves it inline
        for "Try in browser" right from the GUI.
        """
        if not lang.isidentifier():
            return jsonify({"error": "invalid language name"}), 400
        lang_dir = (WORKSPACE / "generated" / lang).resolve()
        generated_root = (WORKSPACE / "generated").resolve()
        if not lang_dir.exists() or not lang_dir.is_relative_to(generated_root):
            return jsonify({"error": "no such language"}), 404

        repl_path = lang_dir / "repl.html"
        spec_path = lang_dir / "resolved_spec.json"
        # Re-render only when (a) repl.html doesn't exist or (b) any of
        # the source files (spec, parser, codegen, runtime, stdlib) has
        # changed since repl.html was written. Eliminates the 1-3s
        # render cost on every "Try in browser" click - the typical case
        # is "render is up to date, just stream the file".
        needs_render = not repl_path.exists()
        if not needs_render and spec_path.exists():
            try:
                repl_mtime = repl_path.stat().st_mtime
                for src_name in ("resolved_spec.json", "parser.py", "codegen.py",
                                 "runtime.py", "stdlib.py", "lexer.py"):
                    src_p = lang_dir / src_name
                    if src_p.exists() and src_p.stat().st_mtime > repl_mtime:
                        needs_render = True
                        break
            except OSError:
                needs_render = True
        if needs_render and spec_path.exists():
            try:
                from forge.orchestrator.generator import render_standalone_repl
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                render_standalone_repl(spec, lang_dir)
            except Exception:
                pass
        if not repl_path.exists():
            return jsonify({"error": "REPL not available for this language yet"}), 500

        from flask import Response
        html = repl_path.read_text(encoding="utf-8")
        # Browser caching: the on-disk file is the source of truth and we
        # invalidate by mtime above. Tell the browser it can cache for a
        # minute (long enough that rapid reloads hit the cache; short
        # enough that re-generation propagates within 60s).
        headers = {"Cache-Control": "max-age=60"}
        if request.args.get("download"):
            headers["Content-Disposition"] = f"attachment; filename={lang}.repl.html"
            headers["Cache-Control"] = "no-store"   # downloads shouldn't be cached
        return Response(html, mimetype="text/html", headers=headers)

    @app.route("/api/download/<lang>")
    def download_lang(lang):
        """Stream a clean .zip of the language directory.

        Excludes: .forge_log/, _playground/, *.out.py, __pycache__/.
        Wraps everything in a top-level <lang>/ folder so unzipping is sane.
        """
        from flask import Response, abort
        import io
        import zipfile

        # Validate
        if not lang.isidentifier():
            return jsonify({"error": "invalid language name"}), 400
        lang_dir = (WORKSPACE / "generated" / lang).resolve()
        generated_root = (WORKSPACE / "generated").resolve()
        if not lang_dir.exists() or not lang_dir.is_relative_to(generated_root):
            return jsonify({"error": "no such language"}), 404

        excluded_dirs = {".forge_log", "_playground", "__pycache__"}
        excluded_suffixes = (".pyc", ".out.py")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in lang_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(lang_dir)
                # Skip if any path component is in excluded_dirs
                if any(part in excluded_dirs for part in rel.parts):
                    continue
                if path.name.endswith(excluded_suffixes):
                    continue
                # Wrap in top-level <lang>/ folder for nice unzip ergonomics
                arcname = f"{lang}/{rel.as_posix()}"
                zf.write(path, arcname)
        buf.seek(0)

        return Response(
            buf.getvalue(),
            mimetype="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={lang}-0.1.0.zip",
                "Cache-Control": "no-store",
            },
        )

    @app.route("/api/log/<lang>/<path:filename>")
    def log_file(lang, filename):
        # Refuse path traversal.
        if "/" in filename or "\\" in filename or ".." in filename:
            return jsonify({"error": "invalid filename"}), 400
        log_dir = WORKSPACE / "generated" / lang / ".forge_log"
        path = log_dir / filename
        if not path.exists() or not path.is_file():
            return jsonify({"error": "not found"}), 404
        return jsonify({"name": filename, "content": path.read_text(encoding="utf-8", errors="replace")})

    @app.route("/api/verify/<lang>", methods=["POST"])
    def verify_lang(lang):
        from forge.orchestrator.verifier import verify
        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        report = verify(lang_dir)
        return jsonify(report.to_dict())

    @app.route("/api/repair/<lang>", methods=["POST"])
    def repair_lang(lang):
        from forge.orchestrator.providers import make_client
        from forge.orchestrator.repair import repair_run
        lang_dir = WORKSPACE / "generated" / lang
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        try:
            client = make_client(log_dir=lang_dir / ".forge_log")
            report = repair_run(lang_dir, client=client)
            return jsonify(report.to_dict())
        except Exception as e:
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    @app.route("/api/language/<lang>", methods=["DELETE"])
    def delete_lang(lang):
        # Refuse to delete protected names (the hand-written reference compilers).
        if lang in {"toylang", "lisplang"}:
            return jsonify({"error": f"{lang} is protected (hand-written reference)"}), 400
        # Sanity check: must be a simple identifier (no path traversal).
        if not lang.isidentifier():
            return jsonify({"error": "invalid language name"}), 400

        lang_dir = (WORKSPACE / "generated" / lang).resolve()
        generated_root = (WORKSPACE / "generated").resolve()
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        # Containment check. is_relative_to() resolves symlinks already
        # (since lang_dir was .resolve()'d), but we ALSO refuse to delete
        # the path if the original (non-resolved) path was a symlink.
        # Otherwise an attacker could pre-place a symlink in generated/
        # whose target lives outside the project, and DELETE the link
        # would `rmtree` the target. We want to delete only real
        # directories that live under generated/.
        original = WORKSPACE / "generated" / lang
        if original.is_symlink():
            return jsonify({"error": "refusing to delete a symlink"}), 400
        if not lang_dir.is_relative_to(generated_root):
            return jsonify({"error": "refusing to delete outside generated/"}), 400
        if lang_dir == generated_root:
            return jsonify({"error": "refusing to delete generated/ itself"}), 400

        import shutil as _sh
        import stat as _stat
        # Windows often holds locks on .pyc files briefly after a process
        # exits; retry with a chmod-and-rmtree and a short backoff if needed.
        last_error = None
        for attempt in range(4):
            try:
                _sh.rmtree(lang_dir, onerror=_force_writable)
                if not lang_dir.exists():
                    return jsonify({"ok": True})
            except (PermissionError, OSError) as e:
                last_error = e
                time.sleep(0.4 * (attempt + 1))
        return jsonify({
            "error": f"failed to delete {lang_dir.name}: {type(last_error).__name__}: {last_error}",
            "hint": "Close any editors / terminals open inside this directory and try again.",
        }), 500

    return app


def _auto_validate_one_kata(kata: dict, spec: dict, lang_dir: "Path") -> dict:
    """Run a kata's reference solution against every test. Returns a
    validation block describing the outcome:

      {"status": "verified", "tests_run": N, "tests_passed": N}
      {"status": "stub", "reason": "stub-rescued; no tests"}
      {"status": "failed", "reason": "<short error>"}

    The result is attached to each kata as `kata.validation` so the
    GUI can show a status badge ("verified" / "no auto-check" / etc.)
    and users know up front whether their submissions will get graded.

    The contract: every kata must have an example solution and an
    automated check. This function is the gate that proves it.
    """
    if kata.get("stub_rescued") or not kata.get("tests"):
        return {
            "status": "stub",
            "tests_run": 0,
            "tests_passed": 0,
            "reason": "stub-rescued; reference is a starter only",
        }

    from forge.orchestrator.katas import _wrap_with_test_prints, _compile_and_run

    ref = kata.get("reference_solution", "")
    helpers = kata.get("helpers", "")
    tests = kata.get("tests", [])

    program = _wrap_with_test_prints(ref, tests, spec, helpers=helpers)
    res = _compile_and_run(lang_dir, program, spec.get("file_extension", ""))
    if not res["ok"]:
        return {
            "status": "failed",
            "tests_run": 0,
            "tests_passed": 0,
            "reason": f"{res['stage']}: {(res.get('stderr') or '').strip()[:200]}",
        }

    actual_lines = res["stdout"].splitlines()
    passed = 0
    for i, t in enumerate(tests):
        actual = actual_lines[i].rstrip() if i < len(actual_lines) else ""
        if actual == t["expected"].rstrip():
            passed += 1

    if passed == len(tests):
        return {
            "status": "verified",
            "tests_run": len(tests),
            "tests_passed": passed,
        }
    return {
        "status": "failed",
        "tests_run": len(tests),
        "tests_passed": passed,
        "reason": f"{passed}/{len(tests)} tests pass with the shipped reference",
    }


def _normalize_surprise_picks(picked: dict) -> dict:
    """Map common LLM mistakes back to canonical schema values.

    The Claude CLI path doesn't enforce JSON Schema strictly, so the model
    sometimes emits creative variants like `s-expression` or `gc` that fail
    coherence checks downstream. Lean post-processing fixes the obvious
    ones; harder mistakes still surface as errors so the user sees what
    happened.
    """
    if not isinstance(picked, dict):
        return picked
    opts = picked.get("options")
    if isinstance(opts, dict):
        # Syntax synonyms.
        syntax_map = {
            "s-expression": "s_expression",
            "sexp": "s_expression",
            "lisp": "s_expression",
            "scheme": "s_expression",
            "clojure": "s_expression",
            "python": "python_like",
            "c": "c_like",
            "c-like": "c_like",
            "python-like": "python_like",
            # Stack-based synonyms (the LLM loves saying these).
            "stack-based": "stack_based",
            "stack": "stack_based",
            "concatenative": "stack_based",
            "forth": "stack_based",
            "factor": "stack_based",
            "postscript": "stack_based",
        }
        if opts.get("syntax") in syntax_map:
            opts["syntax"] = syntax_map[opts["syntax"]]
        # Memory synonyms.
        mem_map = {
            "gc": "host_gc",
            "garbage_collected": "host_gc",
            "tracing": "host_gc",
            "manual": "refcount",
            "rc": "refcount",
        }
        if opts.get("memory") in mem_map:
            opts["memory"] = mem_map[opts["memory"]]
        # Drop any unknown keys the LLM made up — schema would have been
        # `additionalProperties: false` if jsonschema enforced it on the
        # CLI path. We keep only schema-recognized keys.
        valid_opt_keys = {
            "syntax", "typing", "memory", "comment_style", "string_literals",
            "numeric_literals", "default_mutability", "error_handling",
            "loop_forms", "multiple_returns", "boolean_evaluation",
            "naming_convention", "null_model",
        }
        for k in list(opts.keys()):
            if k not in valid_opt_keys:
                opts.pop(k, None)

    # Top-level field aliases.
    aliases = {
        "designer_persona": "persona",
        "era_preset": "era",
        "syntax_style": None,    # belongs in options.syntax
        "type_system": None,     # belongs in options.typing
        "paradigm": None,        # no schema slot; drop
        "evaluation": None,      # no schema slot; drop
        "mutability": None,      # belongs in options.default_mutability
    }
    for src_key, dst_key in aliases.items():
        if src_key in picked:
            val = picked.pop(src_key)
            if dst_key:
                picked.setdefault(dst_key, val)

    # feature_bans: prepend `no_` when the model writes the bare feature.
    bans = picked.get("feature_bans")
    if isinstance(bans, list):
        ban_synonyms = {
            "loops": "no_loops",
            "mutation": "no_mutation",
            "classes": "no_classes",
            "exceptions": "no_exceptions",
            "global_state": "no_global_state",
            "null": "no_null",
            "goto": "no_classes",   # no goto ban; drop into closest
        }
        valid_bans = {"no_loops", "no_mutation", "no_classes",
                      "no_exceptions", "no_global_state", "no_null"}
        normalized: list[str] = []
        for b in bans:
            if not isinstance(b, str):
                continue
            if b in valid_bans:
                normalized.append(b)
            elif b in ban_synonyms:
                normalized.append(ban_synonyms[b])
        # Dedupe preserving order
        seen = set()
        picked["feature_bans"] = [b for b in normalized
                                  if not (b in seen or seen.add(b))]

    # Persona: drop unknowns (the schema enum is the truth)
    valid_personas = {"dijkstra", "mccarthy", "hickey", "stroustrup",
                      "wirth", "wadler", "matz", "ousterhout"}
    if picked.get("persona") and picked["persona"] not in valid_personas:
        picked.pop("persona", None)

    valid_eras = {"1960s", "1970s", "1980s", "2000s", "2020s"}
    if picked.get("era") and picked["era"] not in valid_eras:
        # Map common nearby decades to existing presets so the user gets
        # SOMETHING era-flavored rather than no era at all.
        era_alias = {"1990s": "1980s", "2010s": "2000s",
                     "1950s": "1960s", "retro": "1980s"}
        picked["era"] = era_alias.get(picked["era"])
        if not picked["era"]:
            picked.pop("era", None)

    valid_themes = {"pirate", "shakespearean", "corporate", "latin",
                    "cozy", "none"}
    if picked.get("keyword_theme") and picked["keyword_theme"] not in valid_themes:
        picked.pop("keyword_theme", None)

    return picked


def _force_writable(func, path, _exc_info):
    """rmtree onerror: clear read-only bit + retry. Common on Windows."""
    import os as _os, stat as _stat
    try:
        _os.chmod(path, _stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _explain_compile_error(stderr: str, lang_dir: Path) -> Optional[str]:
    """Turn a Lark traceback into a one-line actionable hint.

    The Lark error text contains the rejected character + position. We pair
    that with the language's spec to suggest a concrete fix.
    """
    if not stderr:
        return None
    import re as _re
    spec_path = lang_dir / "resolved_spec.json"
    if not spec_path.exists():
        return None
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    cs = spec.get("comment_syntax") or {}
    syntax = (spec.get("options") or {}).get("syntax")

    m = _re.search(
        r"UnexpectedCharacters: No terminal matches '(.+?)'.*?at line (\d+) col (\d+)",
        stderr,
        _re.DOTALL,
    )
    if m:
        ch, line, col = m.group(1), m.group(2), m.group(3)
        # s_expression-specific hints first (Lisp errors look different).
        if syntax == "s_expression":
            if ch == ")":
                return (f"Line {line}: extra `)` with no matching `(`. Count "
                        f"your parens — every `)` needs a matching `(`. The "
                        f"**↓ Load reference** button on the Solution tab "
                        f"loads byte-for-byte to avoid copy/paste mangling.")
            if ch in (";", "/", "{", "}"):
                return (f"Line {line}: `{ch}` isn't valid in s_expression "
                        f"syntax. Did you paste c_like or python_like code? "
                        f"Lisp uses `(...)` for everything; comments are `;`.")
        # Comment-style mismatch is by far the most common cause.
        if ch == "/" and cs.get("line") != "//":
            line_form = cs.get("line")
            block_open = cs.get("block_open")
            block_close = cs.get("block_close")
            if line_form:
                return (f"Line {line}: this language uses `{line_form}` for line comments, not `//`. "
                        f"Replace `// foo` with `{line_form} foo`.")
            if block_open and block_close:
                return (f"Line {line}: this language uses `{block_open}...{block_close}` block comments only, "
                        f"not `//`. Replace `// foo` with `{block_open} foo {block_close}`.")
            return f"Line {line}: this language doesn't accept `//` line comments."
        if ch == "#" and cs.get("line") != "#":
            return (f"Line {line}: this language uses `{cs.get('line') or '//'}` for line comments, not `#`. "
                    f"Replace `# foo` with `{cs.get('line') or '//'} foo`.")
        if ch == "'" and "'" not in (spec.get("literals", {}).get("string") or ""):
            return (f"Line {line}: this language doesn't accept single-quoted strings. "
                    f"Use double-quoted strings.")
        # Generic fallback.
        return f"Line {line}, column {col}: the lexer rejected `{ch}`."

    m = _re.search(
        r"UnexpectedToken: Unexpected token Token\('(\w+)', '?(.+?)'?\) at line (\d+)",
        stderr,
        _re.DOTALL,
    )
    if m:
        kind, value, line = m.group(1), m.group(2), m.group(3)
        if kind == "EQUAL":
            return (f"Line {line}: this language's parser doesn't accept assignment as a "
                    "statement (`x = expr;`). Click Repair on this language in the Library "
                    "to have the model add `assign_op` to its grammar.")
        # `//` mis-tokenized as `FACTOR_OP /` because the lexer has no line-
        # comment rule. Most-common cause: source has `//` but the language's
        # comment_style is block-only.
        if kind == "FACTOR_OP" and value == "/" and cs.get("line") != "//":
            line_form = cs.get("line")
            block_open, block_close = cs.get("block_open"), cs.get("block_close")
            if line_form:
                return (f"Line {line}: your source uses `//` but this language's line "
                        f"comments are `{line_form}`. Click ✨ Fix comments to convert.")
            if block_open and block_close:
                return (f"Line {line}: your source uses `//` but this language only has "
                        f"`{block_open}…{block_close}` block comments. "
                        "Click ✨ Fix comments to convert.")
            return f"Line {line}: this language doesn't accept `//`."
        return f"Line {line}: parser rejected token `{value}` ({kind})."

    # If the parser was expecting a primary-expression token set
    # (NAME, TRUE, FALSE, INT, etc.) but got something else, the most
    # common root cause on LLM-generated grammars is a missing rule.
    m = _re.search(r"Expected one of:\s*((?:\s*\*\s*\w+\s*)+)", stderr, _re.DOTALL)
    if m:
        expected = set(_re.findall(r"\*\s*(\w+)", m.group(1)))
        if {"NAME", "TRUE", "FALSE", "STRING", "INT"}.issubset(expected):
            return ("This language's parser appears to be missing a rule "
                    "(commonly `assign_op` for `x = expr;` statements, or "
                    "the line you're on isn't a valid statement form). "
                    "Click Repair on this language in the Library to have "
                    "the model fix the grammar.")
    return None


_VALID_KEYWORD_KEYS = {
    "var", "func", "def", "let", "return", "if", "else", "elif", "while", "for",
    "true", "false", "null", "print", "and", "or", "not",
}

_VALID_OPERATOR_KEYS = {"arithmetic", "comparison", "logical", "assignment"}

_VALID_COMPONENTS = {"lexer", "parser", "typechecker", "codegen", "runtime", "stdlib", "tests", "readme"}


def _validate_customization(c: dict) -> None:
    """Sanity-check a user-supplied customization block. Raises ValueError on bad input."""
    if not isinstance(c, dict):
        raise ValueError("customization must be an object")

    ext = c.get("file_extension")
    if ext is not None:
        if not isinstance(ext, str) or len(ext) > 8 or not all(ch.isalnum() or ch == "." for ch in ext):
            raise ValueError("file_extension must be a short alphanumeric string (max 8 chars)")

    kw = c.get("keyword_overrides")
    if kw is not None:
        if not isinstance(kw, dict):
            raise ValueError("keyword_overrides must be an object")
        for k, v in kw.items():
            if k not in _VALID_KEYWORD_KEYS:
                raise ValueError(f"unknown keyword: {k!r}")
            if not isinstance(v, str) or not v.strip() or len(v) > 24:
                raise ValueError(f"invalid override for {k!r}")

    ops = c.get("operator_overrides")
    if ops is not None:
        if not isinstance(ops, dict):
            raise ValueError("operator_overrides must be an object")
        for k, v in ops.items():
            if k not in _VALID_OPERATOR_KEYS:
                raise ValueError(f"unknown operator category: {k!r}")
            if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                raise ValueError(f"operator_overrides.{k} must be a non-empty list of strings")

    notes = c.get("extra_prompt_notes")
    if notes is not None:
        if not isinstance(notes, dict):
            raise ValueError("extra_prompt_notes must be an object")
        for k, v in notes.items():
            if k not in _VALID_COMPONENTS:
                raise ValueError(f"unknown component: {k!r}")
            if not isinstance(v, str):
                raise ValueError(f"extra_prompt_notes.{k} must be a string")

    extras = c.get("extra_design_notes")
    if extras is not None:
        if not isinstance(extras, list) or not all(isinstance(s, str) for s in extras):
            raise ValueError("extra_design_notes must be a list of strings")

    tests = c.get("additional_tests")
    if tests is not None:
        if not isinstance(tests, list):
            raise ValueError("additional_tests must be a list")
        seen = set()
        for t in tests:
            if not isinstance(t, dict):
                raise ValueError("each additional_test must be an object")
            for f in ("name", "source", "expected"):
                if f not in t or not isinstance(t[f], str):
                    raise ValueError(f"additional_test missing string field: {f}")
            if not t["name"].isidentifier() or not t["name"].islower():
                raise ValueError(f"additional_test name must be a lowercase identifier: {t['name']!r}")
            if t["name"] in seen:
                raise ValueError(f"duplicate additional_test name: {t['name']!r}")
            seen.add(t["name"])

    # docs_persona (free-form is fine here: the schema enum is enforced when the
    # spec is validated downstream).
    dp = c.get("docs_persona")
    if dp is not None and (not isinstance(dp, str) or len(dp) > 40):
        raise ValueError("docs_persona must be a short string")


def run_gui(port: int = 5173, open_browser: bool = True) -> None:
    app = create_app()
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Forge GUI listening on {url}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_gui()
