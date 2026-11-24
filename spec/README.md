# Casper — Contract-First Specification

> **Product:** **Casper**, the friendly ghostwriter  
> **Status:** Refined & Adversarially Reviewed (Contract-First)  
> **Supersedes:** [build-specification.md](build-specification.md) (preserved as historical draft from `raw_inputs/`)

This directory is the single source of truth for building **Casper** from an empty repository without ambiguity. Every interface, data schema, shipped catalog, uniform surface mapping, brand asset contract, pre-build test case, threat mitigation, and dependency-ordered implementation task is defined before code is written.

`SPEC.md` at the repository root is deterministically assembled from the numbered files `00-*.md` through `05-*.md` by `scripts/build_spec.py` (ADR 0003).

## Specification Map

| File | Scope (`planning-with-contracts` Sections) |
|---|---|
| [00-overview.md](00-overview.md) | **1. Goal · 2. Motivation (Measured) · 3. Architecture & Strict Module Rank DAG · 5. Global Constraints · ADR Register · Draft §12 Resolutions · Repo Layout** |
| [01-data-model.md](01-data-model.md) | **4a. Core Data Types, Typed Error Hierarchy, Complete Author Profile YAML Schema (all 11 feature groups), 32-Feature Scoring & Structure Formulas, Layer Merge Algebra, Full Shipped YAML Catalogs & Closed Stop-Word List** |
| [02-contracts.md](02-contracts.md) | **4b. Stage Contracts (`loaders`, `rewrites`, `facts`, `planner`, `realizer`, `llm`, `validator`, `modalities`, `pipeline`), Uniform Core Dispatcher (`commands.py`, 10 operations), CLI/HTTP JSON Schemas & Security Gates, `scripts/verify.sh` & `start.sh`/`stop.sh` Contracts** |
| [03-test-matrix.md](03-test-matrix.md) | **6. Pre-Build Exhaustive Test Matrix (`TC-001`–`TC-050`, 6 Dimensions × 8 Tiers) · 8. Threat & Failure Model** |
| [04-implementation-plan.md](04-implementation-plan.md) | **7. Dependency-Ordered Build Tasks (Tasks 1–15, RED→GREEN, zero forward deps) · 9. Verification Plan** |
| [05-brand-assets.md](05-brand-assets.md) | **Super-Cute Casper Ghost Mascot Brand Kit Contract: Logos, Multi-Size Icons/Favicons, Subsystem Icons, Die-Cut Stickers with Border Cutouts, & Screen Backgrounds up to `3480x1440`** |

## Historical Input

- [build-specification.md](build-specification.md) — Original draft transcribed and adapted from the 11 screenshots in `raw_inputs/`. Kept intact for provenance; all open design questions from its Section 12 are resolved in [00-overview.md](00-overview.md#6-resolutions-of-draft-architecture-review-items).
