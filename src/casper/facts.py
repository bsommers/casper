"""Fact ingestion, classification, entity/metric extraction, and NetworkX graph (Rank 3)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import networkx as nx

from casper.errors import InputError
from casper.loaders import collect_input_paths, load_bytes, load_document
from casper.models import BlockKind, Document, Fact, FactKind, FactModel
from casper.parsing import load_nlp

_INLINE_TAG_RE = re.compile(
    r"^\[(status|progress|risk|next_step|decision|background|detail|metric|ask)\]\s*(.*)$",
    re.IGNORECASE,
)

_KEY_VALUE_SPLIT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.\- ]{0,40})\s*:\s*(.+)$")

_KEY_KIND: dict[str, tuple[FactKind, str]] = {
    "status": (FactKind.STATUS, "status"),
    "state": (FactKind.STATUS, "status"),
    "owner": (FactKind.DETAIL, "owner"),
    "risk": (FactKind.RISK, "risk"),
    "risks": (FactKind.RISK, "risk"),
    "blocker": (FactKind.RISK, "blocker"),
    "blockers": (FactKind.RISK, "blocker"),
    "next": (FactKind.NEXT_STEP, "next step"),
    "next step": (FactKind.NEXT_STEP, "next step"),
    "next steps": (FactKind.NEXT_STEP, "next step"),
    "ask": (FactKind.ASK, "request"),
    "asks": (FactKind.ASK, "request"),
    "request": (FactKind.ASK, "request"),
    "requests": (FactKind.ASK, "request"),
    "decision": (FactKind.DECISION, "decision"),
    "decisions": (FactKind.DECISION, "decision"),
    "progress": (FactKind.PROGRESS, "progress"),
    "done": (FactKind.PROGRESS, "progress"),
    "background": (FactKind.BACKGROUND, "background"),
    "context": (FactKind.BACKGROUND, "background"),
    "metric": (FactKind.METRIC, "metric"),
    "metrics": (FactKind.METRIC, "metric"),
}

_HEADING_KIND: tuple[tuple[FactKind, re.Pattern[str]], ...] = (
    (FactKind.STATUS, re.compile(r"\b(status|state|health|summary|overview)\b", re.IGNORECASE)),
    (FactKind.PROGRESS, re.compile(r"\b(progress|done|completed|shipped|highlights)\b", re.IGNORECASE)),
    (FactKind.RISK, re.compile(r"\b(risks?|blockers?|issues?|concerns?|limitations?)\b", re.IGNORECASE)),
    (FactKind.NEXT_STEP, re.compile(r"\b(next\s+steps?|upcoming|plan|actions?|todo)\b", re.IGNORECASE)),
    (FactKind.DECISION, re.compile(r"\b(decisions?|recommendation|options?|trade-?offs?)\b", re.IGNORECASE)),
    (FactKind.METRIC, re.compile(r"\b(metrics?|numbers?|kpis?|measurements?|benchmarks?)\b", re.IGNORECASE)),
    (FactKind.ASK, re.compile(r"\b(asks?|requests?|approvals?|sign-?off|help\s+needed)\b", re.IGNORECASE)),
    (FactKind.BACKGROUND, re.compile(r"\b(background|context|history|motivation)\b", re.IGNORECASE)),
)

# Priority order per spec/02-contracts.md §1.7 ("review" alone intentionally excluded from ask).
_CUES: tuple[tuple[FactKind, re.Pattern[str]], ...] = (
    (
        FactKind.ASK,
        re.compile(
            r"\b(please|could you|can you|would you|need your|approve|approval|"
            r"sign\s+off|action\s+required|let me know)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FactKind.RISK,
        re.compile(
            r"\b(blocked|blocker|risk|at risk|delayed|slipping|outage|incident|"
            r"regression|mitigat\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FactKind.DECISION,
        re.compile(
            r"\b(decided|decision|recommend\w*|chose|chosen|selected|approved)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FactKind.PROGRESS,
        re.compile(
            r"\b(completed|finished|shipped|deployed|merged|landed|migrated|implemented)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FactKind.NEXT_STEP,
        re.compile(
            r"\b(next|will\s+\w+|plan\s+to|scheduled|upcoming|targeting)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FactKind.STATUS,
        re.compile(
            r"\b(on track|off track|green|yellow|red|healthy|degraded|in progress)\b",
            re.IGNORECASE,
        ),
    ),
    (
        FactKind.METRIC,
        re.compile(
            r"(?:[+-]?\d+(?:[.,]\d+)*\s*(?:%|ms|sec|s|kb|mb|gb|tb|rps|qps|x)(?!\w)|[$€£]\s*\d)",
            re.IGNORECASE,
        ),
    ),
)

_ENTITY_LABELS: frozenset[str] = frozenset(
    {"ORG", "PRODUCT", "GPE", "FAC", "EVENT", "WORK_OF_ART", "LAW"}
)
_DATE_LABELS: frozenset[str] = frozenset({"DATE", "TIME"})

_METRIC_EXTRACT_RE = re.compile(
    r"(?:[$€£]\s*[+-]?\d+(?:[.,]\d+)*|"
    r"[+-]?\d+(?:[.,]\d+)*\s*(?:%|ms|sec|s|kb|mb|gb|tb|rps|qps|x)(?!\w))",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

_CONTENT_BLOCK_KINDS: frozenset[BlockKind] = frozenset(
    {
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.QUOTE,
    }
)


def _dedupe_preserve(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = re.sub(r"\s+", " ", item).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            out.append(cleaned)
    return tuple(out)


def _normalize_dedupe_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")


def _ensure_terminal_punctuation(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped[-1] in ".!?":
        return stripped
    return f"{stripped}."


def _match_key_value(text: str, doc_format: str) -> tuple[str, FactKind, str, str] | None:
    m = _KEY_VALUE_SPLIT_RE.match(text)
    if not m:
        return None
    raw_key = m.group(1).strip()
    value = m.group(2).strip()
    if not value:
        return None

    key_norm = re.sub(r"[\s_-]+", " ", raw_key.lower()).strip()
    entry = _KEY_KIND.get(key_norm)
    if entry is None and doc_format == "yaml" and "." in raw_key:
        tail = re.sub(r"[\s_-]+", " ", raw_key.rsplit(".", 1)[-1].lower()).strip()
        entry = _KEY_KIND.get(tail)
        if entry is not None:
            key_norm = tail
    if entry is None:
        return None
    kind, label = entry
    return key_norm, kind, label, value


def _should_preserve_initial_case(val_doc: Any, value: str) -> bool:
    if not value or not value[0].isupper():
        return True
    first_tok = val_doc[0] if len(val_doc) > 0 else None
    if first_tok is None:
        return True
    tok_text: str = first_tok.text
    if tok_text == "I" or tok_text.isupper():
        return True
    if any(ch.isupper() for ch in tok_text[1:]):
        return True
    if first_tok.pos_ == "PROPN":
        return True
    for ent in val_doc.ents:
        if ent.start == 0:
            return True
    return False


def _has_clause_verb(val_doc: Any, *, require_subject_for_participle: bool = False) -> bool:
    verbs = [t for t in val_doc if t.pos_ in {"VERB", "AUX"}]
    if not verbs:
        return False
    if require_subject_for_participle:
        has_finite = any(t.tag_ in {"VBP", "VBZ", "VBD", "MD", "VB"} for t in verbs)
        has_subj = any(t.dep_ in {"nsubj", "nsubjpass", "expl"} for t in val_doc)
        return has_finite or has_subj
    return True


def _restate_key_value(key_norm: str, label: str, value: str, nlp: Any) -> str:
    cleaned_val = re.sub(r"\s+", " ", value).strip()
    val_doc = nlp(cleaned_val)

    if key_norm == "owner":
        if _has_clause_verb(val_doc, require_subject_for_participle=True):
            return _ensure_terminal_punctuation(cleaned_val)
        return _ensure_terminal_punctuation(f"The owner is {cleaned_val.rstrip('.!?')}")

    is_status = key_norm in {"status", "state"}
    if _has_clause_verb(val_doc, require_subject_for_participle=is_status):
        return _ensure_terminal_punctuation(cleaned_val)

    rendered_val = cleaned_val.rstrip(".!?")
    if not _should_preserve_initial_case(val_doc, rendered_val):
        rendered_val = rendered_val[0].lower() + rendered_val[1:]
    return _ensure_terminal_punctuation(f"The {label} is {rendered_val}")


def _classify_heading(heading: str | None) -> FactKind | None:
    if not heading:
        return None
    for kind, pattern in _HEADING_KIND:
        if pattern.search(heading):
            return kind
    return None


def _classify_cues(text: str) -> FactKind | None:
    for kind, pattern in _CUES:
        if pattern.search(text):
            return kind
    return None


def _compute_salience(
    kind: FactKind,
    entities: tuple[str, ...],
    metrics: tuple[str, ...],
    dates: tuple[str, ...],
) -> float:
    return round(
        1.0
        + 0.4 * bool(metrics)
        + 0.2 * min(len(entities), 2)
        + 0.2 * bool(dates)
        + 0.3 * (kind == FactKind.STATUS),
        6,
    )


def _extract_annotations(
    text: str,
    nlp: Any,
    *,
    explicit_owner: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    doc = nlp(text)
    entities = _dedupe_preserve(
        [ent.text for ent in doc.ents if ent.label_ in _ENTITY_LABELS]
    )
    metrics = _dedupe_preserve([m.group(0) for m in _METRIC_EXTRACT_RE.finditer(text)])
    date_candidates = [ent.text for ent in doc.ents if ent.label_ in _DATE_LABELS]
    date_candidates.extend(m.group(0) for m in _ISO_DATE_RE.finditer(text))
    dates = _dedupe_preserve(date_candidates)

    owner_candidates = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
    if explicit_owner:
        owner_candidates.append(explicit_owner.strip().rstrip(".!?"))
    owners = _dedupe_preserve(owner_candidates)
    return entities, metrics, dates, owners


def _split_sentences(text: str, nlp: Any) -> list[str]:
    spacy_doc = nlp(text)
    sents = [re.sub(r"\s+", " ", s.text).strip() for s in spacy_doc.sents]
    return [s for s in sents if s]


def _extract_doc_candidates(
    doc: Document,
    nlp: Any,
) -> list[tuple[str, FactKind, str, str, str | None]]:
    """Return list of (statement_text, kind, classification_source, source, explicit_owner)."""
    candidates: list[tuple[str, FactKind, str, str, str | None]] = []
    current_heading: str | None = None
    prose_block_idx = 0

    for block in doc.blocks:
        if block.kind == BlockKind.TITLE:
            current_heading = None
            continue
        if block.kind == BlockKind.HEADING:
            current_heading = block.text.strip() or None
            continue
        if block.kind == BlockKind.SUMMARY:
            if block.level > 0:
                current_heading = block.text.strip() or None
                continue
        elif block.kind not in _CONTENT_BLOCK_KINDS:
            continue

        raw = re.sub(r"\s+", " ", block.text).strip()
        if not raw:
            continue

        block_idx = prose_block_idx
        prose_block_idx += 1

        # Precedence 1: Inline [kind] tag at block start
        m_tag = _INLINE_TAG_RE.match(raw)
        if m_tag:
            block_tag_kind = FactKind(m_tag.group(1).lower())
            remainder = m_tag.group(2).strip()
            if not remainder:
                continue
            kv_after_tag = _match_key_value(remainder, doc.format)
            if kv_after_tag is not None:
                key_norm, _kv_kind, label, value = kv_after_tag
                text = _restate_key_value(key_norm, label, value, nlp)
                explicit_owner = value if key_norm == "owner" else None
                candidates.append((text, block_tag_kind, "inline_tag", doc.source, explicit_owner))
            else:
                for sent in _split_sentences(remainder, nlp):
                    m_sub = _INLINE_TAG_RE.match(sent)
                    if m_sub:
                        sent_kind = FactKind(m_sub.group(1).lower())
                        sent_text = m_sub.group(2).strip()
                    else:
                        sent_kind = block_tag_kind
                        sent_text = sent
                    if sent_text:
                        candidates.append(
                            (
                                _ensure_terminal_punctuation(sent_text),
                                sent_kind,
                                "inline_tag",
                                doc.source,
                                None,
                            )
                        )
            continue

        # Precedence 2: Explicit "Key: value" block preserved as a single statement
        kv = _match_key_value(raw, doc.format)
        if kv is not None:
            key_norm, kv_kind, label, value = kv
            restated = _restate_key_value(key_norm, label, value, nlp)
            explicit_owner = value if key_norm == "owner" else None
            candidates.append((restated, kv_kind, "key", doc.source, explicit_owner))
            continue

        # General prose block: split into sentences via spaCy
        for sent in _split_sentences(raw, nlp):
            m_sent_tag = _INLINE_TAG_RE.match(sent)
            if m_sent_tag:
                sent_kind = FactKind(m_sent_tag.group(1).lower())
                sent_body = m_sent_tag.group(2).strip()
                if sent_body:
                    candidates.append(
                        (
                            _ensure_terminal_punctuation(sent_body),
                            sent_kind,
                            "inline_tag",
                            doc.source,
                            None,
                        )
                    )
                continue

            statement = _ensure_terminal_punctuation(sent)
            # Precedence 3: Nearest enclosing heading
            heading_kind = _classify_heading(current_heading)
            if heading_kind is not None:
                candidates.append((statement, heading_kind, "heading", doc.source, None))
                continue

            # Precedence 4: Tightened keyword cues
            cue_kind = _classify_cues(statement)
            if cue_kind is not None:
                candidates.append((statement, cue_kind, "cue", doc.source, None))
                continue

            # Precedence 5: Default
            default_kind = (
                FactKind.BACKGROUND
                if (block_idx == 0 and current_heading is None)
                else FactKind.DETAIL
            )
            candidates.append((statement, default_kind, "default", doc.source, None))

    return candidates


def _build_graph(facts: Sequence[Fact]) -> nx.DiGraph:
    graph: nx.DiGraph = nx.DiGraph()
    for fact in facts:
        graph.add_node(
            fact.id,
            type="fact",
            kind=str(fact.kind),
            order=fact.order,
            source=fact.source,
            text=fact.text,
        )
        for entity in fact.entities:
            node_id = f"entity:{entity}"
            graph.add_node(node_id, type="entity", label=entity)
            graph.add_edge(fact.id, node_id, relation="mentions")
        for owner in fact.owners:
            node_id = f"owner:{owner}"
            graph.add_node(node_id, type="owner", label=owner)
            graph.add_edge(fact.id, node_id, relation="mentions")
        for metric in fact.metrics:
            node_id = f"metric:{metric}"
            graph.add_node(node_id, type="metric", label=metric)
            graph.add_edge(fact.id, node_id, relation="mentions")
        for date in fact.dates:
            node_id = f"date:{date}"
            graph.add_node(node_id, type="date", label=date)
            graph.add_edge(fact.id, node_id, relation="mentions")

    for prev_fact, curr_fact in zip(facts, facts[1:], strict=False):
        graph.add_edge(prev_fact.id, curr_fact.id, relation="follows")

    return graph


def ingest(
    inputs: Sequence[str | Path] = (),
    notes: str | None = None,
    *,
    nlp: Any | None = None,
    fact_overrides: Mapping[str, FactKind] | None = None,
) -> FactModel:
    """Ingest documents and/or inline notes into a deterministic, classified FactModel."""
    has_notes = notes is not None and bool(notes.strip())
    if not inputs and not has_notes:
        raise InputError("Nothing to write from")

    paths = collect_input_paths(inputs) if inputs else []
    if not paths and not has_notes:
        raise InputError("Nothing to write from")

    docs: list[Document] = [load_document(p) for p in paths]
    if has_notes and notes is not None:
        docs.append(load_bytes(notes.encode("utf-8"), "<inline>"))

    input_hashes: dict[str, str] = {doc.source: doc.sha256 for doc in docs}
    warnings: list[str] = []
    for doc in docs:
        warnings.extend(doc.notes)

    active_nlp = nlp if nlp is not None else load_nlp(ner=True)

    raw_candidates: list[tuple[str, FactKind, str, str, str | None]] = []
    for doc in docs:
        raw_candidates.extend(_extract_doc_candidates(doc, active_nlp))

    # Deduplicate on normalized text BEFORE assigning sequential IDs f001, f002, ...
    seen_keys: set[str] = set()
    deduped: list[tuple[str, FactKind, str, str, str | None]] = []
    for cand in raw_candidates:
        key = _normalize_dedupe_key(cand[0])
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(cand)

    if not deduped:
        raise InputError("No facts could be extracted")

    facts_list: list[Fact] = []
    for order, (text, kind, cls_source, source, explicit_owner) in enumerate(deduped):
        fid = f"f{order + 1:03d}"
        entities, metrics, dates, owners = _extract_annotations(
            text, active_nlp, explicit_owner=explicit_owner
        )
        salience = _compute_salience(kind, entities, metrics, dates)
        facts_list.append(
            Fact(
                id=fid,
                kind=kind,
                text=text,
                source=source,
                order=order,
                entities=entities,
                metrics=metrics,
                dates=dates,
                owners=owners,
                salience=salience,
                classification_source=cls_source,
            )
        )

    if fact_overrides:
        by_id = {f.id: idx for idx, f in enumerate(facts_list)}
        for fid, raw_kind in fact_overrides.items():
            if fid not in by_id:
                raise InputError(f"Unknown fact id in fact_overrides: {fid}")
            try:
                new_kind = raw_kind if isinstance(raw_kind, FactKind) else FactKind(str(raw_kind))
            except ValueError as exc:
                valid = ", ".join(k.value for k in FactKind)
                raise InputError(
                    f"Unknown FactKind {raw_kind!r} in fact_overrides; expected one of: {valid}"
                ) from exc
            idx = by_id[fid]
            old = facts_list[idx]
            facts_list[idx] = Fact(
                id=old.id,
                kind=new_kind,
                text=old.text,
                source=old.source,
                order=old.order,
                entities=old.entities,
                metrics=old.metrics,
                dates=old.dates,
                owners=old.owners,
                salience=_compute_salience(new_kind, old.entities, old.metrics, old.dates),
                classification_source="override",
            )

    facts_tuple = tuple(facts_list)
    graph = _build_graph(facts_tuple)
    canonical = json.dumps(
        [f.to_dict() for f in facts_tuple],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()

    return FactModel(
        facts=facts_tuple,
        graph=graph,
        input_hashes=input_hashes,
        digest=digest,
        warnings=tuple(warnings),
    )
