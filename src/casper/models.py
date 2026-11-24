"""Core enumerations, constants, and dataclasses for Casper (Rank 1)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from typing import Any


class BlockKind(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    QUOTE = "quote"
    CODE = "code"
    SUMMARY = "summary"
    AUDIENCE = "audience"
    RESOURCES = "resources"


EXCLUDED_VOICE_BLOCK_KINDS: frozenset[BlockKind] = frozenset(
    {
        BlockKind.SUMMARY,
        BlockKind.AUDIENCE,
        BlockKind.RESOURCES,
    }
)


class FactKind(StrEnum):
    STATUS = "status"
    PROGRESS = "progress"
    RISK = "risk"
    NEXT_STEP = "next_step"
    DECISION = "decision"
    BACKGROUND = "background"
    DETAIL = "detail"
    METRIC = "metric"
    ASK = "ask"


class PersonaKind(StrEnum):
    SOURCE = "source"
    TARGET = "target"


class DepthLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


DEPTH_CAPS: dict[DepthLevel, int] = {
    DepthLevel.LOW: 1,
    DepthLevel.MEDIUM: 3,
    DepthLevel.HIGH: 6,
}


class JargonLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MarkupKind(StrEnum):
    MARKDOWN = "markdown"
    SLACK = "slack"
    HTML = "html"
    PLAIN = "plain"


class BackendKind(StrEnum):
    RULES = "rules"
    CLAUDE = "claude"
    AGY = "agy"


class FidelityMode(StrEnum):
    STRICT = "strict"
    ASSISTED = "assisted"


class CheckLevel(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class MatchBand(StrEnum):
    STRONG = "strong"
    CLOSE = "close"
    PARTIAL = "partial"
    DIFFERENT = "different"


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def _serialize(val: Any) -> Any:
    if val is None or isinstance(val, (bool, int, float)):
        return val
    if isinstance(val, StrEnum):
        return str(val)
    if isinstance(val, str):
        return val
    if isinstance(val, (frozenset, set)):
        return sorted(_serialize(v) for v in val)
    if isinstance(val, (tuple, list)):
        return [_serialize(v) for v in val]
    if isinstance(val, dict):
        return {
            (str(k) if not isinstance(k, tuple) else ":".join(str(p) for p in k)): _serialize(v)
            for k, v in val.items()
        }
    if is_dataclass(val) and not isinstance(val, type):
        if hasattr(val, "to_dict"):
            return val.to_dict()
        return {f.name: _serialize(getattr(val, f.name)) for f in fields(val)}
    if callable(val):
        return getattr(val, "__name__", repr(val))
    return str(val)


class _DictMixin:
    def to_dict(self) -> dict[str, Any]:
        assert is_dataclass(self)
        out: dict[str, Any] = {}
        for f in fields(self):
            out[f.name] = _serialize(getattr(self, f.name))
        return out


@dataclass(frozen=True)
class Block(_DictMixin):
    kind: BlockKind
    text: str
    level: int = 0
    links: int = 0
    emphasis_lead: bool = False


@dataclass(frozen=True)
class Document(_DictMixin):
    source: str
    format: str
    title: str | None = None
    authors: tuple[str, ...] = ()
    published: str | None = None
    modified: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    blocks: tuple[Block, ...] = ()
    sha256: str = ""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fact(_DictMixin):
    id: str
    kind: FactKind
    text: str
    source: str
    order: int
    entities: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    salience: float = 1.0
    classification_source: str = "default"


@dataclass
class FactModel:
    facts: tuple[Fact, ...]
    graph: Any
    input_hashes: dict[str, str]
    digest: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [f.to_dict() for f in self.facts],
            "input_hashes": dict(sorted(self.input_hashes.items())),
            "digest": self.digest,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class Persona(_DictMixin):
    id: str
    kind: PersonaKind
    priorities: tuple[str, ...]
    vocabulary_include: tuple[str, ...]
    vocabulary_avoid: tuple[str, ...]
    detail_depth: DepthLevel
    jargon_level: JargonLevel
    framing_patterns: tuple[str, ...]
    typical_concerns: tuple[str, ...]
    cta_styles: tuple[str, ...]
    section_priority: tuple[str, ...]


@dataclass(frozen=True)
class Section(_DictMixin):
    name: str
    purpose: str
    fact_kinds: tuple[FactKind, ...]
    required: bool
    min_words: int
    max_words: int
    heading: str


@dataclass(frozen=True)
class Structure(_DictMixin):
    id: str
    goal: str
    sections: tuple[Section, ...]
    compatible_modalities: tuple[str, ...]
    default_target_personas: tuple[str, ...]


@dataclass(frozen=True)
class Modality(_DictMixin):
    id: str
    markup: MarkupKind
    max_words: int | None
    max_chars: int | None
    title: bool
    headings: str
    bullets: bool
    description: str


@dataclass(frozen=True)
class Glossary(_DictMixin):
    plain: dict[str, str]
    preferred: dict[str, str]
    banned: tuple[str, ...]


@dataclass(frozen=True)
class Libraries(_DictMixin):
    personas: dict[tuple[PersonaKind, str], Persona]
    structures: dict[str, Structure]
    modalities: dict[str, Modality]
    glossary: Glossary
    phrasebank: dict[str, tuple[str, ...]]
    lexicons: dict[str, tuple[str, ...]]
    digest: str


@dataclass(frozen=True)
class PlanSection(_DictMixin):
    section: Section
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class Plan(_DictMixin):
    structure: Structure
    sections: tuple[PlanSection, ...]
    unused_facts: tuple[Fact, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdaptedPlan(_DictMixin):
    structure: Structure
    source: Persona
    target: Persona
    sections: tuple[PlanSection, ...]
    substitutions: dict[str, str]
    cta_style: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RewriteRule(_DictMixin):
    id: str
    description: str
    added_tokens: frozenset[str]
    apply: Callable[[str], list[str]]


@dataclass(frozen=True)
class Sentence(_DictMixin):
    text: str
    fact_ids: tuple[str, ...] = ()
    frame: bool = False


@dataclass(frozen=True)
class DraftSection(_DictMixin):
    name: str
    heading: str
    sentences: tuple[Sentence, ...]


@dataclass(frozen=True)
class Draft(_DictMixin):
    sections: tuple[DraftSection, ...]
    title: str | None = None
    warnings: tuple[str, ...] = ()
    candidates_considered: int = 1
    backend: BackendKind = BackendKind.RULES
    declared_additions: frozenset[str] = frozenset()
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Constraints(_DictMixin):
    max_words: int | None = None
    max_chars: int | None = None
    banned: tuple[str, ...] = ()
    candidates: int = 8
    seed: int = 0
    min_voice: float | None = None


@dataclass(frozen=True)
class CheckFinding(_DictMixin):
    code: str
    level: CheckLevel
    message: str
    section: str | None = None
    sentence_index: int | None = None


@dataclass(frozen=True)
class FeatureScore(_DictMixin):
    name: str
    dimension: str
    author_value: float
    candidate_value: float
    sigma: float
    z: float
    score: float
    pinned: bool = False


@dataclass(frozen=True)
class GapItem(_DictMixin):
    feature: str
    dimension: str
    score: float
    author_value: float
    candidate_value: float
    sigma: float
    explanation: str


@dataclass(frozen=True)
class ConformanceReport(_DictMixin):
    overall: float
    band: MatchBand
    confidence: ConfidenceBand
    word_count: int
    dimensions: dict[str, float]
    features: tuple[FeatureScore, ...]
    largest_gaps: tuple[GapItem, ...]
    signature_matches: tuple[str, ...]
    frame_matches: tuple[str, ...]


@dataclass(frozen=True)
class Validation(_DictMixin):
    ok: bool
    findings: tuple[CheckFinding, ...]
    persona_score: float
    voice_report: ConformanceReport | None
    fidelity_mode: FidelityMode


@dataclass(frozen=True)
class FactTraceEntry(_DictMixin):
    section: str
    text: str
    frame: bool
    facts: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class BackendRecord(_DictMixin):
    requested: BackendKind
    used: BackendKind
    deterministic: bool
    model: str | None = None
    prompt_sha256: str | None = None
    response_sha256: str | None = None


@dataclass(frozen=True)
class ReproducibilityRecord(_DictMixin):
    tool_version: str
    seed: int
    candidates: int
    selectors: dict[str, str | None]
    input_hashes: dict[str, str]
    facts_digest: str
    config_digest: str
    author_corpus_sha256: str | None
    output_sha256: str
    backend: BackendRecord
    record_sha256: str


@dataclass(frozen=True)
class Brief(_DictMixin):
    structure: str
    modality: str
    source: str
    target: str
    author: str | None = None
    inputs: tuple[str, ...] = ()
    notes: str | None = None
    topic: str | None = None
    seed: int = 0
    candidates: int = 8
    min_voice: float | None = None
    banned: tuple[str, ...] = ()
    fact_overrides: dict[str, FactKind] = field(default_factory=dict)
    project_dir: str | None = None
    authors_dir: str = "authors"
    backend: BackendKind | str = BackendKind.RULES
    fallback: bool = True
    timeout: int = 90
    model: str | None = None


@dataclass(frozen=True)
class Result(_DictMixin):
    text: str
    draft: Draft
    validation: Validation
    fact_trace: tuple[FactTraceEntry, ...]
    record: ReproducibilityRecord
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class DriftIssue(_DictMixin):
    kind: str
    path: str
    message: str


@dataclass(frozen=True)
class DriftReport(_DictMixin):
    author_id: str
    issues: tuple[DriftIssue, ...]


@dataclass(frozen=True)
class AuthorSummary(_DictMixin):
    id: str
    display_name: str
    source_count: int
    total_words: int
    has_curated: bool
    has_local: bool
    schema_version: int


@dataclass(frozen=True)
class AuthorDiff(_DictMixin):
    author_a: str
    author_b: str
    feature_deltas: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class BackendAvailability(_DictMixin):
    backend: BackendKind
    available: bool
    executable: str | None
    version: str | None
    reason: str | None


@dataclass(frozen=True)
class BackendStatusReport(_DictMixin):
    backends: dict[str, BackendAvailability]
