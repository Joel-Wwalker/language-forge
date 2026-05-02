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
                 natural_language: Optional[dict] = None):
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
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.done = False
        self.success = False
        self.lang_dir: Optional[Path] = None
        self.error: Optional[str] = None

    def emit(self, kind: str, **payload) -> None:
        self.queue.put({"kind": kind, **payload})


JOBS: dict[str, Job] = {}


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

def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")

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
            if spec.exists():
                try:
                    data = json.loads(spec.read_text(encoding="utf-8"))
                    ext = data.get("file_extension", ext)
                    opts = data.get("options", {})
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
        JOBS[job.id] = job
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

        # Patch the language's runtime to support string indexing if it
        # doesn't already (some generated languages raise TypeError on
        # `get(string, int)` while toylang's reference handles it). This is
        # idempotent and surgical — string-iteration classics (valid_parens,
        # anagram, longest_unique_substring) need this universally.
        from forge.orchestrator.mechanical_translator import ensure_runtime_string_support
        try:
            ensure_runtime_string_support(lang_dir)
        except Exception:
            pass  # best-effort; falls back to LLM/stub if it didn't help

        # `?strict=true` disables LLM-translation fallback — useful for
        # testing the pre-flight rejection logic without firing the LLM.
        # Production callers (GUI Load button) leave it off so the endpoint
        # transparently translates when a language is incompatible.
        strict_mode = request.args.get("strict", "").lower() in ("1", "true", "yes")
        # `?force=true` skips the cache (re-runs validation/translation).
        force = request.args.get("force", "").lower() in ("1", "true", "yes")

        # Cache check: if we've already loaded this exact pack into this
        # language, return the saved katas.json immediately. We tag the
        # cache with a CONTENT HASH of the source pack so that when the
        # curated classics change in code (new fields like tags/examples,
        # bug-fixed references, etc.), the cache is automatically
        # invalidated — without it, users see stale katas after upgrades.
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
        # Hard incompatibility signals. If any of these are true, direct
        # load is guaranteed to drop everything; skip straight to translation.
        needs_translation = bool(
            (pack_family and lang_family and pack_family != lang_family)
            or (nl and isinstance(nl, dict) and nl)
            or bans_force_translation
        )
        # Strict mode: if hard-incompatible, refuse with 400 instead of
        # falling through to translation.
        if strict_mode and needs_translation:
            if pack_family and lang_family and pack_family != lang_family:
                msg = (f"`{lang}` is `{lang_family}`, but the pack is "
                       f"`{pack_family}`.")
            elif nl and isinstance(nl, dict) and nl:
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
            if templates:
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
        # Final fallback ladder for anything still failing:
        #   1. mechanical case-analysis (cascade of if-args-match returns,
        #      always works on Turing-complete targets); auto-check works
        #   2. stub-rescue (empty tests + stub reference; no auto-check)
        # We try (1) first so the user gets a gradeable kata when possible.
        from forge.orchestrator.kata_translator import _stub_rescue
        from forge.orchestrator.case_analysis import build_case_analysis_kata
        toylang_dir = WORKSPACE / "generated" / "toylang"
        for kata, ok, reason in results:
            if ok:
                valid.append(kata)
                continue
            try:
                ca = build_case_analysis_kata(kata, spec, lang_dir, toylang_dir)
            except Exception:
                ca = None
            if ca is not None:
                valid.append(ca)
                continue
            rescued = _stub_rescue(kata, spec)
            if rescued is not None:
                valid.append(rescued)
            else:
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
        (lang_dir / "katas.json").write_text(
            json.dumps(out_pack, indent=2), encoding="utf-8",
        )
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
                return jsonify({
                    "mode": "run",
                    "passed": False,
                    "stage": res["stage"],
                    "stderr": res.get("stderr", ""),
                    "results": [],
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
                        "syntax": {"enum": ["c_like", "python_like"]},
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
            "Choose every option from the schema below. Be opinionated. The "
            "language must be coherent: every choice should reinforce the "
            "vibe. Pick a designer persona whose values match. Optionally "
            "pick an era preset, a keyword theme, and one or two feature "
            "bans that sharpen the language's character.\n\n"
            "Write a 1-3 sentence fictional origin story (origin_story). "
            "as if the language were a real obscure project from the 1990s "
            "or 2000s. Add 3-6 design_notes explaining the vibe-driven "
            "choices.\n\n"
            "Honesty rule: every option must be one our generator actually "
            "supports. Do not invent new option values."
        )

        try:
            from forge.orchestrator.providers import make_client
            log_dir = WORKSPACE / "generated" / name / ".forge_log"
            client = make_client(provider, log_dir=log_dir)
            picked = client.call_json(prompt, picker_schema, tag="surprise")
        except Exception as e:
            return jsonify({"error": f"surprise picker failed: {e}"}), 500

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
        JOBS[job.id] = job
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return jsonify({
            "job_id": job.id,
            "name": name,
            "picks": picked,
        })

    @app.route("/api/stream/<job_id>")
    def stream(job_id):
        job = JOBS.get(job_id)
        if job is None:
            return jsonify({"error": "no such job"}), 404

        def gen():
            yield "retry: 1000\n\n"
            while True:
                try:
                    msg = job.queue.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                    if msg["kind"] == "done":
                        return
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    if job.done and job.queue.empty():
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
        # If the file's missing or stale, re-render on the fly.
        try:
            spec_path = lang_dir / "resolved_spec.json"
            if spec_path.exists():
                from forge.orchestrator.generator import render_standalone_repl
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                render_standalone_repl(spec, lang_dir)
        except Exception:
            pass
        if not repl_path.exists():
            return jsonify({"error": "REPL not available for this language yet"}), 500

        from flask import Response
        html = repl_path.read_text(encoding="utf-8")
        headers = {"Cache-Control": "no-store"}
        if request.args.get("download"):
            headers["Content-Disposition"] = f"attachment; filename={lang}.repl.html"
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
        # Refuse to delete protected names (the hand-written reference compiler).
        if lang in {"toylang"}:
            return jsonify({"error": "toylang is protected (hand-written reference)"}), 400
        # Sanity check: must be a simple identifier (no path traversal).
        if not lang.isidentifier():
            return jsonify({"error": "invalid language name"}), 400

        lang_dir = (WORKSPACE / "generated" / lang).resolve()
        generated_root = (WORKSPACE / "generated").resolve()
        if not lang_dir.exists():
            return jsonify({"error": "no such language"}), 404
        # Use is_relative_to (Py 3.9+) for unambiguous containment check.
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

    m = _re.search(
        r"UnexpectedCharacters: No terminal matches '(.+?)'.*?at line (\d+) col (\d+)",
        stderr,
        _re.DOTALL,
    )
    if m:
        ch, line, col = m.group(1), m.group(2), m.group(3)
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
