"""TC-027: Hypothesis property-based tests for substitute, format_draft, and layers.resolve."""

from __future__ import annotations

import copy
import html
import re
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from casper.layers import resolve
from casper.modalities import count_rendered, format_draft
from casper.models import Draft, DraftSection, MarkupKind, Modality, Sentence
from casper.realizer import substitute

_ALPHA_WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=10)
_SAFE_KEY = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12).filter(
    lambda k: k not in {"overlays", "style_guide"} and not k.startswith("$")
)
_SAFE_SCALAR = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 _-", min_size=0, max_size=16),
    st.booleans(),
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _collect_leaf_paths(obj: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, val in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if path == "style_guide" and isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    paths.add(f"style_guide.{item['id']}")
        elif isinstance(val, dict):
            paths.update(_collect_leaf_paths(val, path))
        else:
            paths.add(path)
    return paths


@settings(max_examples=120, deadline=None)
@given(
    key=_ALPHA_WORD,
    replacement=_ALPHA_WORD,
    prefix=_ALPHA_WORD,
    suffix=_ALPHA_WORD,
)
def test_tc027_substitute_case_preservation_and_whole_word(
    key: str,
    replacement: str,
    prefix: str,
    suffix: str,
) -> None:
    """substitute preserves ALL CAPS, Initial Cap, lowercase, and respects word boundaries."""
    mapping = {key: replacement}

    assert substitute(key.upper(), mapping) == replacement.upper()
    assert substitute(key[0].upper() + key[1:], mapping) == (
        replacement[0].upper() + replacement[1:]
    )
    assert substitute(key.lower(), mapping) == replacement

    # Embedded inside a larger word must never be substituted
    embedded = f"{prefix}{key}{suffix}"
    assert substitute(embedded, mapping) == embedded


@settings(max_examples=120, deadline=None)
@given(
    k1=_ALPHA_WORD,
    k2=_ALPHA_WORD,
    k3=_ALPHA_WORD,
    ext=_ALPHA_WORD,
)
def test_tc027_substitute_single_pass_and_longest_key_first(
    k1: str,
    k2: str,
    k3: str,
    ext: str,
) -> None:
    """substitute runs in a single pass and prefers longest matching key."""
    if len({k1, k2, k3}) == 3:
        assert substitute(k1, {k1: k2, k2: k3}) == k2

    longer_key = f"{k1} {ext}"
    if longer_key != k2 and k1 != k3:
        res = substitute(longer_key, {k1: k2, longer_key: k3})
        assert res == k3


@settings(max_examples=120, deadline=None)
@given(
    markup=st.sampled_from(list(MarkupKind)),
    headings=st.sampled_from(["none", "h2", "bold", "slack_bold"]),
    title_flag=st.booleans(),
    bullets_flag=st.booleans(),
    title_words=st.lists(_ALPHA_WORD, min_size=1, max_size=4),
    sections_data=st.lists(
        st.tuples(
            _ALPHA_WORD,
            st.lists(
                st.tuples(
                    st.lists(_ALPHA_WORD, min_size=1, max_size=6),
                    st.booleans(),
                ),
                min_size=1,
                max_size=4,
            ),
        ),
        min_size=1,
        max_size=4,
    ),
)
def test_tc027_format_draft_preserves_every_sentence_token(
    markup: MarkupKind,
    headings: str,
    title_flag: bool,
    bullets_flag: bool,
    title_words: list[str],
    sections_data: list[tuple[str, list[tuple[list[str], bool]]]],
) -> None:
    """format_draft preserves every sentence word across all markups and options."""
    modality = Modality(
        id="prop_mod",
        markup=markup,
        max_words=1000,
        max_chars=10000,
        title=title_flag,
        headings=headings,
        bullets=bullets_flag,
        description="Property test modality",
    )
    draft_sections: list[DraftSection] = []
    expected_sentences: list[str] = []
    for idx, (sec_name, sent_specs) in enumerate(sections_data):
        sents: list[Sentence] = []
        for s_idx, (words, is_frame) in enumerate(sent_specs):
            text = " ".join(words).capitalize() + "."
            expected_sentences.append(text)
            sents.append(
                Sentence(
                    text=text,
                    fact_ids=() if is_frame else (f"f{idx + 1}{s_idx + 1:02d}",),
                    frame=is_frame,
                )
            )
        draft_sections.append(
            DraftSection(
                name=f"{sec_name}_{idx}",
                heading=sec_name.title(),
                sentences=tuple(sents),
            )
        )

    draft = Draft(title=" ".join(title_words), sections=tuple(draft_sections))
    rendered = format_draft(draft, modality)
    comparable = html.unescape(rendered) if markup == MarkupKind.HTML else rendered

    for sent_text in expected_sentences:
        assert sent_text in comparable
        for tok in _TOKEN_RE.findall(sent_text):
            assert tok in comparable

    words_count, chars_count = count_rendered(draft, modality)
    assert chars_count == len(rendered)
    assert words_count >= sum(len(_TOKEN_RE.findall(s)) for s in expected_sentences)


@settings(max_examples=120, deadline=None)
@given(
    gen_scalars=st.dictionaries(_SAFE_KEY, _SAFE_SCALAR, min_size=1, max_size=5),
    gen_nested=st.dictionaries(_SAFE_KEY, _SAFE_SCALAR, min_size=1, max_size=4),
    gen_list=st.lists(_ALPHA_WORD, max_size=4, unique=True),
    cur_scalars=st.dictionaries(_SAFE_KEY, _SAFE_SCALAR, max_size=4),
    loc_scalars=st.dictionaries(_SAFE_KEY, _SAFE_SCALAR, max_size=4),
    ov_cur_scalars=st.dictionaries(_SAFE_KEY, _SAFE_SCALAR, max_size=3),
    ov_loc_scalars=st.dictionaries(_SAFE_KEY, _SAFE_SCALAR, max_size=3),
    add_items=st.lists(_ALPHA_WORD, max_size=3, unique=True),
    remove_items=st.lists(_ALPHA_WORD, max_size=2, unique=True),
    overlay_name=_ALPHA_WORD,
    override_rule=_ALPHA_WORD,
)
def test_tc027_layers_resolve_provenance_precedence_and_immutability(
    gen_scalars: dict[str, Any],
    gen_nested: dict[str, Any],
    gen_list: list[str],
    cur_scalars: dict[str, Any],
    loc_scalars: dict[str, Any],
    ov_cur_scalars: dict[str, Any],
    ov_loc_scalars: dict[str, Any],
    add_items: list[str],
    remove_items: list[str],
    overlay_name: str,
    override_rule: str,
) -> None:
    """layers.resolve covers every leaf in provenance, enforces precedence, strips overlays."""
    generated: dict[str, Any] = {
        "base": dict(gen_scalars),
        "nested": dict(gen_nested),
        "tags": list(gen_list),
        "style_guide": [
            {"id": "sentences", "area": "sentences", "rule": "Keep sentences crisp."},
            {"id": "voice", "area": "voice", "rule": "Prefer active voice."},
        ],
    }
    curated: dict[str, Any] = {
        "base": dict(cur_scalars),
        "tags": {"$remove": list(remove_items), "$add": list(add_items)},
        "style_guide": {"sentences": f"Curated {override_rule}"},
        "overlays": {overlay_name: {"nested": dict(ov_cur_scalars)}},
    }
    local: dict[str, Any] = {
        "base": dict(loc_scalars),
        "overlays": {overlay_name: {"nested": dict(ov_loc_scalars)}},
    }

    gen_snap = copy.deepcopy(generated)
    cur_snap = copy.deepcopy(curated)
    loc_snap = copy.deepcopy(local)

    merged, provenance = resolve(generated, curated, local, overlays=(overlay_name,))

    # Inputs are never mutated
    assert generated == gen_snap
    assert curated == cur_snap
    assert local == loc_snap

    # Overlays container is always stripped
    assert "overlays" not in merged

    # Provenance covers every surviving leaf path
    leaf_paths = _collect_leaf_paths(merged)
    assert leaf_paths <= set(provenance.keys())

    # Exact precedence for base scalars: local > curated > generated
    for key in set(gen_scalars) | set(cur_scalars) | set(loc_scalars):
        path = f"base.{key}"
        if key in loc_scalars:
            assert merged["base"][key] == loc_scalars[key]
            assert provenance[path] == "local"
        elif key in cur_scalars:
            assert merged["base"][key] == cur_scalars[key]
            assert provenance[path] == "curated"
        else:
            assert merged["base"][key] == gen_scalars[key]
            assert provenance[path] == "generated"

    # Exact precedence for overlay nested scalars: local.overlays > curated.overlays > generated
    for key in set(gen_nested) | set(ov_cur_scalars) | set(ov_loc_scalars):
        path = f"nested.{key}"
        if key in ov_loc_scalars:
            assert merged["nested"][key] == ov_loc_scalars[key]
            assert provenance[path] == f"local.overlays.{overlay_name}"
        elif key in ov_cur_scalars:
            assert merged["nested"][key] == ov_cur_scalars[key]
            assert provenance[path] == f"curated.overlays.{overlay_name}"
        else:
            assert merged["nested"][key] == gen_nested[key]
            assert provenance[path] == "generated"

    # Style guide provenance
    assert provenance["style_guide.sentences"] == "curated"
    assert provenance["style_guide.voice"] == "generated"
    assert provenance["tags"] == "curated"
