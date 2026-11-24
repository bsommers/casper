"""Author profile builder, deterministic style guide, tamper check, and atomic YAML I/O (Rank 2)."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from casper.documents import prose_word_count
from casper.errors import (
    InputError,
    ProfileError,
    ProfileNotFoundError,
    ProfileTamperedError,
)
from casper.features import analyze
from casper.loaders import collect_input_paths, load_document
from casper.models import Document
from casper.parsing import MODEL_NAME

STYLE_GUIDE_AREAS: tuple[str, ...] = (
    "sentences",
    "paragraphs",
    "lexical",
    "voice",
    "punctuation",
    "rhetoric",
    "headings",
    "structure",
)


def _tool_version() -> str:
    try:
        return importlib.metadata.version("casper")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _normalize_for_hash(obj: Any) -> Any:
    if isinstance(obj, dt.datetime):
        return obj.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _normalize_for_hash(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_for_hash(v) for v in obj]
    return obj


def compute_body_sha256(profile: dict[str, Any]) -> str:
    """Compute canonical SHA-256 of profile dict excluding `generated.body_sha256`."""
    cloned = copy.deepcopy(profile)
    generated = cloned.get("generated")
    if isinstance(generated, dict):
        generated.pop("body_sha256", None)
    normalized = _normalize_for_hash(cloned)
    payload = json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def render_style_guide(features: dict[str, Any]) -> list[dict[str, str]]:
    """Emit exactly 8 deterministic style guide rules (1 per area, id == area)."""
    sents = features["sentences"]
    lens = sents["length_words"]
    paras = features["paragraphs"]
    lex = features["lexical"]
    voice = features["voice"]
    pov = voice["person_per_1k"]
    punct = voice["punctuation_per_1k"]
    lexicon = voice["lexicon_per_1k"]
    rhet = voice["rhetoric"]
    heads = features["headings"]
    struct = features["structure"]

    rules: dict[str, str] = {
        "sentences": (
            f"Target mean sentence length of {lens['mean']:.1f} words "
            f"(median {lens['median']:.1f}, p10–p90 {lens['p10']:.0f}–{lens['p90']:.0f}); "
            f"keep short (<=8w) rate near {sents['short_rate_le8']:.0%} and "
            f"passive rate near {sents['passive_rate']:.0%}."
        ),
        "paragraphs": (
            f"Average {paras['sentences_per_paragraph']['mean']:.2f} sentences and "
            f"{paras['words_per_paragraph']['mean']:.1f} words per paragraph; "
            f"single-sentence paragraph rate {paras['single_sentence_rate']:.0%}, "
            f"long (>=120w) rate {paras['long_paragraph_rate_ge120w']:.0%}."
        ),
        "lexical": (
            f"Maintain Flesch-Kincaid grade {lex['flesch_kincaid_grade']:.1f} "
            f"(reading ease {lex['flesch_reading_ease']:.1f}), mean word length "
            f"{lex['mean_word_length']:.2f} chars, and {lex['acronyms_per_1k']:.1f} acronyms/1k."
        ),
        "voice": (
            f"Use POV rates/1k of 1st-singular {pov['first_singular']:.1f}, "
            f"1st-plural {pov['first_plural_inclusive']:.1f}, 2nd-person {pov['second']:.1f}; "
            f"contractions {voice['contractions_per_1k']:.1f}/1k and "
            f"negations {voice['negations_per_1k']:.1f}/1k."
        ),
        "punctuation": (
            f"Use {voice['commas_per_1k']:.1f} commas/1k "
            f"(Oxford comma rate {voice['oxford_comma_rate']:.0%}), "
            f"em dashes {punct['em_dash']:.1f}/1k, colons {punct['colon']:.1f}/1k, "
            f"semicolons {punct['semicolon']:.1f}/1k, parentheticals {punct['parenthetical']:.1f}/1k."
        ),
        "rhetoric": (
            f"Pace transitions at {lexicon['transitions']:.1f}/1k, intensifiers at "
            f"{lexicon['intensifiers']:.1f}/1k, hedges at {lexicon['hedges']:.1f}/1k, "
            f"and contrast frames at {rhet['contrast_frames_per_1k']:.1f}/1k."
        ),
        "headings": (
            f"Use {heads['case_style']} case headings averaging {heads['mean_words']:.1f} words "
            f"at {heads['density_per_1k']:.2f} headings/1k words."
        ),
        "structure": (
            f"Target ~{struct['mean_doc_words']:.0f} words across ~{struct['mean_sections']:.1f} "
            f"sections with summary presence rate {struct['has_summary_rate']:.0%}."
        ),
    }

    return [{"id": area, "area": area, "rule": rules[area]} for area in STYLE_GUIDE_AREAS]


def _byline_matches(doc: Document, name_set: frozenset[str]) -> bool:
    for author in doc.authors:
        cleaned = author.strip().lower()
        if cleaned and cleaned in name_set:
            return True
    return False


def build_profile(
    author_id: str,
    display_name: str,
    inputs: Sequence[str | Path],
    *,
    aliases: Sequence[str] = (),
    strict_authors: bool = False,
    min_words: int = 150,
    nlp: Any | None = None,
) -> dict[str, Any]:
    """Build a schema v1 author profile dict from input files/directories/URLs."""
    if not author_id or not author_id.strip():
        raise InputError("author_id must be non-empty")
    if not display_name or not display_name.strip():
        raise InputError("display_name must be non-empty")

    paths = collect_input_paths(inputs)
    if not paths:
        raise InputError("No input documents found for author profile build")

    name_set = frozenset(
        n.strip().lower() for n in (display_name, *aliases) if n and n.strip()
    )

    kept_docs: list[Document] = []
    kept_words: list[int] = []
    for p in paths:
        doc = load_document(p)
        pw = prose_word_count(doc)
        if pw < min_words:
            continue
        if strict_authors and not _byline_matches(doc, name_set):
            continue
        kept_docs.append(doc)
        kept_words.append(pw)

    if not kept_docs:
        raise InputError(
            f"No eligible documents remained after filtering (min_words={min_words}, "
            f"strict_authors={strict_authors})"
        )

    feats = analyze(kept_docs, nlp=nlp)
    total_words = sum(kept_words)
    avg_doc_words = round(total_words / len(kept_docs), 2)
    corpus_sha256 = hashlib.sha256(
        "\n".join(sorted(d.sha256 for d in kept_docs)).encode("utf-8")
    ).hexdigest()

    sources = [
        {
            "title": doc.title or Path(doc.source).stem,
            "source": doc.source,
            "byline": ", ".join(doc.authors),
            "byline_matches_author": _byline_matches(doc, name_set),
            "prose_words": pw,
            "sha256": doc.sha256,
        }
        for doc, pw in zip(kept_docs, kept_words, strict=True)
    ]

    profile: dict[str, Any] = {
        "schema_version": 1,
        "author": {
            "id": author_id,
            "display_name": display_name,
            "aliases": list(aliases),
        },
        "generated": {
            "tool": "casper",
            "tool_version": _tool_version(),
            "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "spacy_model": MODEL_NAME,
            "corpus_sha256": corpus_sha256,
            "body_sha256": "",
        },
        "corpus": {
            "document_count": len(kept_docs),
            "total_words": total_words,
            "avg_doc_words": avg_doc_words,
        },
        "style_guide": render_style_guide(feats),
        "sentences": feats["sentences"],
        "paragraphs": feats["paragraphs"],
        "lexical": feats["lexical"],
        "voice": feats["voice"],
        "typography": feats["typography"],
        "headings": feats["headings"],
        "lists": feats["lists"],
        "structure": feats["structure"],
        "function_word_per_1k": feats["function_word_per_1k"],
        "signature": feats["signature"],
        "exemplars": feats["exemplars"],
        "stability": feats["stability"],
        "sources": sources,
    }
    profile["generated"]["body_sha256"] = compute_body_sha256(profile)
    return profile


def load_profile(path: Path) -> dict[str, Any]:
    """Load an author profile YAML mapping from disk."""
    profile_path = Path(path)
    if not profile_path.is_file():
        raise ProfileNotFoundError(f"Profile not found: {profile_path}")
    try:
        raw = profile_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProfileError(f"Failed loading profile YAML {profile_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"Profile YAML {profile_path} must be a mapping")
    return data


def _is_tampered(existing: dict[str, Any]) -> bool:
    generated = existing.get("generated")
    if not isinstance(generated, dict):
        return False
    recorded = generated.get("body_sha256")
    if not recorded or not isinstance(recorded, str):
        return False
    return recorded != compute_body_sha256(existing)


def check_profile_writable(path: Path, *, force: bool = False) -> None:
    """Verify existing profile has not been hand-edited unless `force=True`."""
    profile_path = Path(path)
    if not profile_path.exists():
        return
    existing = load_profile(profile_path)
    if _is_tampered(existing) and not force:
        raise ProfileTamperedError(
            f"Profile {profile_path} has been manually edited (body_sha256 mismatch). "
            f"Move edits to {profile_path.stem}.curated.yaml or pass --force to overwrite."
        )


def save_profile(path: Path, profile: dict[str, Any], *, force: bool = False) -> Path:
    """Atomically write a profile YAML to disk with tamper check and optional .bak backup."""
    profile_path = Path(path)
    check_profile_writable(profile_path, force=force)

    if profile_path.exists() and force:
        existing = load_profile(profile_path)
        if _is_tampered(existing):
            bak_path = Path(f"{profile_path}.bak")
            shutil.copy2(profile_path, bak_path)

    to_save = copy.deepcopy(profile)
    generated = to_save.get("generated")
    if isinstance(generated, dict) and not generated.get("body_sha256"):
        generated["body_sha256"] = compute_body_sha256(to_save)

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = profile_path.with_name(f"{profile_path.name}.tmp.{os.getpid()}")
    serialized = yaml.safe_dump(
        to_save,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )

    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, profile_path)
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise

    return profile_path
