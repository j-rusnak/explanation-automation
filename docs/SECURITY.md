# Security and threat model

Sources, filenames, manifests, and provider output are hostile data. techshort never follows embedded links, executes attachments/code blocks, dynamically imports project data, or treats source instructions as commands. Prompts explicitly delimit excerpts as untrusted quoted data.

| Threat | Mitigation |
|---|---|
| Malformed, encrypted, scanned, huge, or compressed PDFs | pypdf strict mode; encryption rejection; 25 MiB and 250-page input limits; cumulative 32 MiB extracted/raw-output limit; OCR-required failure; hashed and strictly revalidated page/section metadata |
| Prompt injection requesting filesystem/network access | excerpt-only prompt context; explicit injection warning; Codex ephemeral/read-only mode; ignored user rules/config when supported; strict schema validation |
| Hostile filenames and path traversal | basename sanitization, slug allowlist, canonical containment, project-relative path validators |
| SSRF | URL ingestion is absent; any future implementation must reject private/loopback/link-local targets and revalidate every redirect |
| Arbitrary code, shell injection, hostile HTML/SVG | no `eval`, `exec`, or dynamic imports; fixed executables and argument arrays; allowlisted primitives; inert-text checks in both Python and TypeScript; escaped companion HTML |
| Secret leakage | no API key required; no auth-file inspection; sanitized provider environment; no full-document logging |
| Stale or forged approvals | exact content/evidence/audio/transcript hashes, immutable version history, append-only review invalidations, explicit angle selection, configuration/provenance-bound final approval |
| Fabricated numbers, units, citations, or evidence labels | deterministic assertion-token checks during generation, approval, and QA; scene citations/labels and SourceReceipt IDs must resolve through approved claims |
| Rights mistakes and source redistribution | explicit asset rights and embedding status; concrete permissive-license metadata; unknown/restricted/citation-only blockers; short excerpts only |

Subprocesses use argument arrays, `shell=False`, timeouts, and bounded output. Normal tests have no network or live-model calls.

The PDF parser still runs in-process. Byte/page/output limits reduce common resource-exhaustion risks but are not a full memory-isolation boundary for a novel parser exploit; high-risk PDFs should be pre-screened in a disposable environment.
