# Security and threat model

Sources and provider output are hostile data. techshort never follows embedded links, runs code blocks, imports modules from a project, executes attachments, or treats source instructions as prompts. Model prompts label excerpts as untrusted quoted data.

| Threat | Mitigation |
|---|---|
| Malicious, encrypted, malformed, scanned, huge, or decompression-bomb PDFs | strict parser mode, encryption rejection, 25 MiB/250-page limits, extraction warnings, OCR-required failure |
| Prompt injection requesting filesystem/network access | provider abstraction, excerpt-only temporary input, explicit untrusted-data instruction, schema-only output |
| Hostile filenames and path traversal | basename sanitization, slug allowlist, canonical containment checks, project-relative schema fields |
| SSRF | URL ingestion is absent; a future implementation must reject private/loopback/link-local targets and revalidate redirects |
| Arbitrary code, shell injection, generated HTML/SVG | no eval/exec/dynamic imports; subprocess argument arrays; scene primitive allowlist; escaped HTML; markup token rejection |
| Secret leakage | no API key required, no auth-file inspection, no environment logging, Codex runs in excerpt-only temporary workspace |
| Stale approvals | dependency hashes, approval hashes, append-only invalidation records, hard export gate |
| Rights mistakes and source redistribution | explicit asset rights status, unknown/restricted/citation-only blockers, short excerpts only, full sources excluded from export |

Subprocesses use argument arrays, `shell=False`, timeouts, and fixed executables. Normal tests have no network or model calls. Private source text is not logged by default.

