"""Command-line interface (`casper`) routing through `commands.py` (Rank 8)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from casper import commands
from casper.errors import CasperError, InputError, SecurityError
from casper.models import Brief, FactKind


def _json_dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _parse_fact_override_arg(raw: str) -> tuple[str, FactKind]:
    if "=" not in raw:
        raise InputError(f"Invalid --fact-override {raw!r}; expected FID=KIND (e.g. f001=risk)")
    fid, kind_str = raw.split("=", 1)
    fid = fid.strip()
    kind_norm = kind_str.strip().lower()
    if not fid:
        raise InputError(f"Invalid --fact-override {raw!r}; fact ID cannot be empty")
    try:
        kind = FactKind(kind_norm)
    except ValueError as exc:
        valid = ", ".join(str(k) for k in FactKind)
        raise InputError(
            f"Unknown fact kind {kind_str!r} in --fact-override; valid choices: {valid}"
        ) from exc
    return fid, kind


def _load_brief_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise InputError(f"Brief file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise InputError(f"Invalid YAML in brief file {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise InputError(f"Brief file {path} must contain a YAML mapping")
    return loaded


def _coerce_fact_overrides_dict(raw: Any) -> dict[str, FactKind]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InputError("Brief 'fact_overrides' must be a mapping of fact_id -> kind")
    out: dict[str, FactKind] = {}
    for k, v in raw.items():
        if isinstance(v, FactKind):
            out[str(k)] = v
        else:
            try:
                out[str(k)] = FactKind(str(v).strip().lower())
            except ValueError as exc:
                valid = ", ".join(str(fk) for fk in FactKind)
                raise InputError(
                    f"Unknown fact kind {v!r} for {k!r}; valid choices: {valid}"
                ) from exc
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casper",
        description="Casper, the friendly ghostwriter — local-first, deterministic ghostwriting toolkit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # casper write
    p_write = subparsers.add_parser("write", help="Generate a fact-grounded draft.")
    p_write.add_argument("--structure", default=None, help="Structure ID (e.g. status_update)")
    p_write.add_argument("--modality", default=None, help="Modality ID (e.g. slack, email, memo)")
    p_write.add_argument("--source", default=None, help="Source persona ID")
    p_write.add_argument("--target", default=None, help="Target persona ID")
    p_write.add_argument("--author", default=None, help="Author ID or profile YAML path")
    p_write.add_argument(
        "-i",
        "--input",
        dest="inputs",
        action="append",
        default=None,
        help="Input file/URL/directory (repeatable)",
    )
    p_write.add_argument("--notes", default=None, help="Inline source notes text")
    p_write.add_argument("--topic", default=None, help="Optional title/topic")
    p_write.add_argument("--seed", type=int, default=None, help="Deterministic RNG seed")
    p_write.add_argument(
        "--candidates", type=int, default=None, help="Max voice-ranked candidates"
    )
    p_write.add_argument("--min-voice", type=float, default=None, help="Minimum voice score")
    p_write.add_argument(
        "--banned", action="append", default=None, help="Additional banned term (repeatable)"
    )
    p_write.add_argument(
        "--fact-override",
        dest="fact_overrides",
        action="append",
        default=None,
        help="Override fact kind as FID=KIND (repeatable)",
    )
    p_write.add_argument("--project-dir", default=None, help="Optional project YAML override dir")
    p_write.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_write.add_argument(
        "--backend",
        default=None,
        help="Writer backend: rules (default), claude, or agy",
    )
    p_write.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Fail instead of falling back to rules when CLI backend errors",
    )
    p_write.add_argument(
        "--timeout", type=int, default=None, help="External CLI timeout in seconds (default 90)"
    )
    p_write.add_argument("--model", default=None, help="Optional model name for claude/agy CLI")
    p_write.add_argument("--out", default=None, help="Write draft to path and <path>.trace.json")
    p_write.add_argument("--brief", default=None, help="YAML brief file with Brief fields")
    p_write.add_argument(
        "--dry-run", action="store_true", help="Extract facts only without generating a draft"
    )
    p_write.add_argument(
        "--backend-status", action="store_true", help="Check availability of writer backends"
    )
    p_write.add_argument(
        "--list-options", action="store_true", help="List available personas, structures, modalities"
    )
    p_write.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output")

    # casper author
    p_author = subparsers.add_parser("author", help="Build, inspect, score, and diff author voices.")
    p_author.add_argument(
        "--authors-dir", default="authors", help="Author profiles directory (default: authors)"
    )
    author_sub = p_author.add_subparsers(dest="author_cmd", required=True)

    # author build
    p_ab = author_sub.add_parser("build", help="Build an author voice profile from sample writing.")
    p_ab.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_ab.add_argument("--id", dest="author_id", required=True, help="Author ID slug")
    p_ab.add_argument("--name", dest="display_name", required=True, help="Author display name")
    p_ab.add_argument("--alias", dest="aliases", action="append", default=[], help="Author alias")
    p_ab.add_argument("--email", default=None, help="Private email (stored ONLY in 0600 .local.yaml)")
    p_ab.add_argument("--min-words", type=int, default=150, help="Min prose words per document")
    p_ab.add_argument(
        "--strict-authors", action="store_true", help="Drop documents whose byline does not match"
    )
    p_ab.add_argument(
        "--force", action="store_true", help="Overwrite hand-edited profile (creates .bak backup)"
    )
    p_ab.add_argument("inputs", nargs="+", help="Input files, URLs, or directories")

    # author inspect
    p_ai = author_sub.add_parser("inspect", help="Inspect author profile summary and layer drift.")
    p_ai.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_ai.add_argument("author_ref", help="Author ID or profile path")
    p_ai.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output")

    # author show
    p_as = author_sub.add_parser("show", help="Print raw or resolved author profile.")
    p_as.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_as.add_argument("author_ref", help="Author ID or profile path")
    p_as.add_argument("--resolved", action="store_true", help="Merge curated & local layers")
    p_as.add_argument("--overlay", default=None, help="Apply named modality overlay")
    p_as.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output")

    # author score
    p_asc = author_sub.add_parser("score", help="Score a draft file against an author voice.")
    p_asc.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_asc.add_argument("author_ref", help="Author ID or profile path")
    p_asc.add_argument("file", help="Path to draft file")
    p_asc.add_argument("--raw", action="store_true", help="Score against raw generated profile only")
    p_asc.add_argument("--overlay", default=None, help="Apply named modality overlay")
    p_asc.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output")

    # author list
    p_al = author_sub.add_parser("list", help="List available author profiles.")
    p_al.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_al.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output")

    # author diff
    p_ad = author_sub.add_parser("diff", help="Diff two author profiles across 32 features.")
    p_ad.add_argument("--authors-dir", default=None, help="Author profiles directory")
    p_ad.add_argument("author_a", help="First author ID or profile path")
    p_ad.add_argument("author_b", help="Second author ID or profile path")
    p_ad.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output")

    # casper serve
    p_serve = subparsers.add_parser("serve", help="Start the localhost-only Casper web UI server.")
    p_serve.add_argument(
        "--host", default="127.0.0.1", help="Bind host (127.0.0.1 only; non-loopback rejected)"
    )
    p_serve.add_argument("--port", type=int, default=8731, help="Bind port (default: 8731)")
    p_serve.add_argument("--authors-dir", default="authors", help="Author profiles directory")
    p_serve.add_argument("--project-dir", default=None, help="Optional project YAML override dir")

    return parser


def _handle_write(args: argparse.Namespace) -> int:
    authors_dir = Path(args.authors_dir) if args.authors_dir else Path("authors")
    project_dir = Path(args.project_dir) if args.project_dir else None

    if args.list_options:
        opts = commands.list_options(project_dir=project_dir, authors_dir=authors_dir)
        if args.as_json:
            sys.stdout.write(_json_dumps(opts))
        else:
            sys.stdout.write(
                f"Structures: {', '.join(s['id'] for s in opts['structures'])}\n"
                f"Modalities: {', '.join(m['id'] for m in opts['modalities'])}\n"
                f"Source personas: {', '.join(p['id'] for p in opts['personas']['source'])}\n"
                f"Target personas: {', '.join(p['id'] for p in opts['personas']['target'])}\n"
                f"Authors: {', '.join(a['id'] for a in opts['authors']) or '(none)'}\n"
                f"Backends: {', '.join(opts['backends'])}\n"
            )
        return 0

    if args.backend_status:
        rep = commands.backend_status(timeout=float(args.timeout or 20))
        if args.as_json:
            sys.stdout.write(_json_dumps(rep.to_dict()))
        else:
            for name, avail in rep.backends.items():
                state = "ready" if avail.available else f"unavailable ({avail.reason})"
                ver = f" {avail.version}" if avail.version else ""
                sys.stdout.write(f"{name}: {state}{ver}\n")
        return 0

    # Merge optional --brief YAML with explicit CLI flags (CLI overrides brief).
    brief_data: dict[str, Any] = {}
    if args.brief:
        brief_data = _load_brief_yaml(Path(args.brief))

    overrides: dict[str, FactKind] = _coerce_fact_overrides_dict(brief_data.get("fact_overrides"))
    for item in args.fact_overrides or []:
        fid, kind = _parse_fact_override_arg(item)
        overrides[fid] = kind

    raw_inputs = (
        tuple(args.inputs)
        if args.inputs is not None
        else tuple(str(p) for p in (brief_data.get("inputs") or ()))
    )
    notes = args.notes if args.notes is not None else brief_data.get("notes")

    if args.dry_run:
        fm = commands.extract_facts(
            inputs=raw_inputs,
            notes=notes,
            fact_overrides=overrides or None,
        )
        if args.as_json:
            sys.stdout.write(_json_dumps(fm.to_dict()))
        else:
            for fact in fm.facts:
                sys.stdout.write(f"[{fact.id}] ({fact.kind}, salience={fact.salience:.2f}) {fact.text}\n")
        return 0

    structure = args.structure or brief_data.get("structure")
    modality = args.modality or brief_data.get("modality")
    source = args.source or brief_data.get("source")
    target = args.target or brief_data.get("target")
    missing = [
        flag
        for flag, val in (
            ("--structure", structure),
            ("--modality", modality),
            ("--source", source),
            ("--target", target),
        )
        if not val
    ]
    if missing:
        raise InputError(f"Missing required write flag(s): {', '.join(missing)}")

    brief = Brief(
        structure=str(structure),
        modality=str(modality),
        source=str(source),
        target=str(target),
        author=args.author if args.author is not None else brief_data.get("author"),
        inputs=raw_inputs,
        notes=notes,
        topic=args.topic if args.topic is not None else brief_data.get("topic"),
        seed=args.seed if args.seed is not None else int(brief_data.get("seed", 0)),
        candidates=(
            args.candidates
            if args.candidates is not None
            else int(brief_data.get("candidates", 8))
        ),
        min_voice=(
            args.min_voice if args.min_voice is not None else brief_data.get("min_voice")
        ),
        banned=(
            tuple(args.banned)
            if args.banned is not None
            else tuple(str(b) for b in (brief_data.get("banned") or ()))
        ),
        fact_overrides=overrides,
        project_dir=(
            args.project_dir
            if args.project_dir is not None
            else brief_data.get("project_dir")
        ),
        authors_dir=(
            args.authors_dir
            if args.authors_dir is not None
            else str(brief_data.get("authors_dir", "authors"))
        ),
        backend=(
            args.backend if args.backend is not None else brief_data.get("backend", "rules")
        ),
        fallback=(
            False
            if args.no_fallback
            else bool(brief_data.get("fallback", True))
        ),
        timeout=(
            args.timeout if args.timeout is not None else int(brief_data.get("timeout", 90))
        ),
        model=args.model if args.model is not None else brief_data.get("model"),
    )

    result = commands.write_draft(brief, allow_author_path=True)

    trace_payload = {
        "text": result.text,
        "validation": result.validation.to_dict(),
        "fact_trace": [e.to_dict() for e in result.fact_trace],
        "record": result.record.to_dict(),
        "facts": [f.to_dict() for f in result.facts],
        "backend": result.record.backend.to_dict(),
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.text, encoding="utf-8")
        trace_path = Path(f"{out_path}.trace.json")
        trace_path.write_text(_json_dumps(trace_payload), encoding="utf-8")

    # Stdout: clean formatted draft only (or JSON when --json requested).
    if args.as_json:
        sys.stdout.write(_json_dumps(trace_payload))
    else:
        sys.stdout.write(result.text)
        if result.text and not result.text.endswith("\n"):
            sys.stdout.write("\n")

    # Stderr: diagnostics, scores, warnings, and validation findings.
    voice_str = (
        f"{result.validation.voice_report.overall:.1f} ({result.validation.voice_report.band})"
        if result.validation.voice_report is not None
        else "n/a"
    )
    sys.stderr.write(
        f"[casper] backend={result.record.backend.used} "
        f"ok={result.validation.ok} persona={result.validation.persona_score:.0f} "
        f"voice={voice_str} record={result.record.record_sha256}\n"
    )
    for warn in result.draft.warnings:
        sys.stderr.write(f"[casper] warning: {warn}\n")
    for finding in result.validation.findings:
        sys.stderr.write(
            f"[casper] {finding.level}: [{finding.code}] {finding.message}\n"
        )

    return 0 if result.validation.ok else 1


def _handle_author(args: argparse.Namespace) -> int:
    # Subcommand --authors-dir overrides parent --authors-dir if explicitly given.
    parent_dir = getattr(args, "authors_dir", "authors") or "authors"
    authors_dir = Path(parent_dir)

    if args.author_cmd == "build":
        prof = commands.author_build(
            args.author_id,
            args.display_name,
            args.inputs,
            authors_dir=authors_dir,
            aliases=args.aliases,
            email=args.email,
            min_words=args.min_words,
            strict_authors=args.strict_authors,
            force=args.force,
        )
        corpus = prof.get("corpus", {})
        sys.stdout.write(
            f"Built author profile '{args.author_id}' "
            f"({corpus.get('document_count', 0)} docs, {corpus.get('total_words', 0)} words)\n"
        )
        return 0

    if args.author_cmd == "inspect":
        info = commands.author_inspect(args.author_ref, authors_dir=authors_dir)
        if args.as_json:
            sys.stdout.write(_json_dumps(info))
        else:
            drift_issues = info["drift"]["issues"]
            sys.stdout.write(
                f"Author: {info['id']} ({info['display_name']})\n"
                f"Docs: {info['corpus']['document_count']} | Words: {info['corpus']['total_words']}\n"
                f"Curated layer: {info['has_curated']} | Local layer: {info['has_local']}\n"
                f"Drift issues: {len(drift_issues)}\n"
            )
            for issue in drift_issues:
                sys.stdout.write(f"  - [{issue['kind']}] {issue['path']}: {issue['message']}\n")
        return 0

    if args.author_cmd == "show":
        prof = commands.author_show(
            args.author_ref,
            authors_dir=authors_dir,
            resolved=args.resolved,
            overlay=args.overlay,
        )
        if args.as_json:
            sys.stdout.write(_json_dumps(prof))
        else:
            sys.stdout.write(yaml.safe_dump(prof, sort_keys=False, allow_unicode=True))
        return 0

    if args.author_cmd == "score":
        report = commands.score_draft(
            args.author_ref,
            args.file,
            authors_dir=authors_dir,
            is_text=False,
            raw=args.raw,
            overlay=args.overlay,
            allow_author_path=True,
        )
        if args.as_json:
            sys.stdout.write(_json_dumps(report.to_dict()))
        else:
            sys.stdout.write(
                f"Voice score: {report.overall:.1f}/100 ({report.band}, "
                f"confidence={report.confidence}, words={report.word_count})\n"
            )
            for gap in report.largest_gaps:
                sys.stdout.write(f"  - {gap.feature} ({gap.score:.2f}): {gap.explanation}\n")
        return 0

    if args.author_cmd == "list":
        summaries = commands.author_list(authors_dir=authors_dir)
        if args.as_json:
            sys.stdout.write(_json_dumps([s.to_dict() for s in summaries]))
        else:
            if not summaries:
                sys.stdout.write("(no author profiles found)\n")
            for s in summaries:
                sys.stdout.write(
                    f"{s.id}\t{s.display_name}\t{s.source_count} docs\t{s.total_words} words\n"
                )
        return 0

    if args.author_cmd == "diff":
        diff = commands.author_diff(args.author_a, args.author_b, authors_dir=authors_dir)
        if args.as_json:
            sys.stdout.write(_json_dumps(diff.to_dict()))
        else:
            sys.stdout.write(f"Diff {diff.author_a} vs {diff.author_b}:\n")
            for item in diff.feature_deltas[:10]:
                sys.stdout.write(
                    f"  {item['feature']}: {item['value_a']:.3f} -> {item['value_b']:.3f} "
                    f"(norm={item['normalized_delta']:+.2f})\n"
                )
        return 0

    raise InputError(f"Unknown author subcommand: {args.author_cmd}")


def _handle_serve(args: argparse.Namespace) -> int:
    if args.host != "127.0.0.1":
        raise SecurityError(
            f"Refusing non-loopback bind host {args.host!r}; Casper binds exclusively to 127.0.0.1"
        )
    from casper.web.server import make_server

    server = make_server(
        args.host,
        args.port,
        authors_dir=Path(args.authors_dir),
        project_dir=Path(args.project_dir) if args.project_dir else None,
    )
    sys.stderr.write(f"Casper web UI running at http://{args.host}:{server.server_port}/\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point returning POSIX exit code (0/1/2/3)."""
    parser = _build_parser()
    # Extract parent `--authors-dir` when placed before or after subcommand cleanly.
    arg_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(arg_list)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    # Preserve parent `--authors-dir` for `casper author --authors-dir X <subcmd>`.
    if args.command == "author":
        # argparse subparser's --authors-dir defaults to None, which would clobber parent's value.
        # Recover parent's value if subparser did not override it.
        if args.authors_dir is None:
            # Re-check raw argv for `--authors-dir` placed before subcommand.
            resolved_dir = "authors"
            for idx, tok in enumerate(arg_list):
                if tok == "--authors-dir" and idx + 1 < len(arg_list):
                    resolved_dir = arg_list[idx + 1]
                elif tok.startswith("--authors-dir="):
                    resolved_dir = tok.split("=", 1)[1]
            args.authors_dir = resolved_dir

    try:
        if args.command == "write":
            return _handle_write(args)
        if args.command == "author":
            return _handle_author(args)
        if args.command == "serve":
            return _handle_serve(args)
        raise InputError(f"Unknown command: {args.command}")
    except CasperError as exc:
        sys.stderr.write(f"Error [{exc.code}]: {exc.message}\n")
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
