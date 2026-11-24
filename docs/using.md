# Using Casper

Practical guide for running Casper from the CLI, managing the localhost Web UI, maintaining three-layer author voice profiles, and reproducing the worked examples.

## Generating Drafts (`casper write`)

`casper write` extracts facts from inputs/notes, selects and adapts a plan for the target persona and modality, realizes candidates, and validates fact traceability.

```bash
casper write \
  --structure status_update \
  --modality email \
  --source developer \
  --target management \
  --author bill \
  --input examples/edge-migration-status.md \
  --out output/status-email.md
```

### Common Flags & Workflows

- **Inspect available options and backends:**
  ```bash
  casper write --list-options
  casper write --backend-status
  ```
- **Dry-run fact extraction (`--dry-run`):** Extract and classify facts with IDs and salience without realizing a draft:
  ```bash
  casper write --dry-run --input examples/edge-migration-status.md --json
  ```
- **Override fact classification (`--fact-override`):** Reassign one or more extracted fact IDs using `FID=KIND`:
  ```bash
  casper write --dry-run --input notes.md --fact-override f001=risk --fact-override f004=ask
  ```
- **Load settings from a brief file (`--brief`):** Provide any `Brief` fields in YAML; explicit CLI flags override values from `--brief`:
  ```bash
  casper write --brief brief.yaml --modality slack
  ```
- **Save draft and full provenance trace (`--out`):** Writes the rendered draft to `<path>` and a complete JSON record (`text`, `validation`, `fact_trace`, `record`, `facts`, `backend`) to `<path>.trace.json`.
- **Optional CLI writer backends (`--backend claude|agy`):** Deterministic `rules` is the default. To opt into an external CLI writer:
  ```bash
  casper write \
    --structure decision_memo \
    --modality memo \
    --source tech_lead \
    --target executive \
    --input examples/edge-migration-status.md \
    --backend claude \
    --model claude-sonnet-4-5 \
    --timeout 90
  ```
  Pass `--no-fallback` to fail rather than fall back to `rules` if the external CLI backend errors or fails validation.

## Author Voice Profiles (`casper author`)

Author profiles live in `authors/` (default `--authors-dir authors`).

```bash
# Build a profile from sample writings (files, directories, or URLs)
casper author build --id alex --name "Alex Rivera" --alias "A. Rivera" samples/

# Build with private email (stored ONLY in gitignored authors/alex.local.yaml with mode 0600)
casper author build --id alex --name "Alex Rivera" --email "alex@example.com" samples/

# List, inspect metadata & drift, or display raw/resolved YAML
casper author list
casper author inspect alex
casper author show alex --resolved --overlay slack

# Score an existing draft against an author's voice profile
casper author score alex draft.md
casper author score alex draft.md --raw
casper author score alex draft.md --overlay memo

# Compare two authors across all 32 stability features
casper author diff alex jordan
```

Add `--json` to `inspect`, `show`, `score`, `list`, or `diff` for machine-readable output.

### Three-Layer Author Profiles

Casper keeps generated statistics, curated editorial overrides, and private personal details cleanly separated:

1. **`authors/<id>.yaml` (generated layer):** Created by `casper author build` with a `generated.body_sha256` integrity digest. Hand-editing triggers `ProfileTamperedError` (exit code `3`) on rebuild unless `--force` is passed (which writes a `.bak` backup).
2. **`authors/<id>.curated.yaml` (curated layer):** Optional, version-controlled overrides for style guide rules, vocabulary preferences, or pinned feature targets. List mutations must use `$add`, `$remove`, or `$replace` directives rather than plain list replacement.
3. **`authors/<id>.local.yaml` (local private layer):** Gitignored companion file written with POSIX permissions `0600` for private metadata (such as `--email` or `consent`) and local-only overrides. Never sent to external CLI prompts (`claude`/`agy`).

Both `.curated.yaml` and `.local.yaml` may also define `overlays.<modality>` mappings (applied via `--overlay <name>`).

## Localhost Web UI (`casper serve` & Operational Scripts)

Start the Web UI directly via the CLI (bound strictly to `127.0.0.1`):

```bash
casper serve --host 127.0.0.1 --port 8731 --authors-dir authors
```

Or use the repository helper scripts:

- **`scripts/start.sh [--background] [--open] [--port N] [--no-install]`** — Ensures `.venv` and editable `casper` install exist (unless `--no-install`), verifies `127.0.0.1:<port>` is free, checks for stale PID files (`target/casper.pid`), and starts the server (logging to `target/casper-server.log` when `--background` is set).
- **`scripts/stop.sh`** — Verifies the PID in `target/casper.pid` belongs to `casper serve`, sends `SIGTERM`, waits for clean shutdown, and removes the PID file.

## Reproducing Worked Examples

`examples/edge-migration-status.md` is the canonical input for five checked-in outputs in `examples/outputs/`:

- `status-slack.txt` (`status_update` × `slack`)
- `status-email.md` (`status_update` × `email`)
- `decision-memo.md` (`decision_memo` × `memo`)
- `technical-article.html` (`technical_article` × `article`)
- `status-plain.txt` (`status_update` × `plain`)

Verify zero drift against the current deterministic pipeline or regenerate them:

```bash
.venv/bin/python scripts/build_examples.py --check
.venv/bin/python scripts/build_examples.py
```

See also: [Data Model & Libraries](data-model.md) · [API Reference](api-reference.md) · [Testing & Verification](testing.md)
