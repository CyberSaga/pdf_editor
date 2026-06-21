# Subscription Fusion Report

Status: degraded
Route: fusion

## Warnings
- claude sample 0 failed with status error
- claude sample 1 failed with status error
- claude unavailable; used remaining independent candidates

## Final Answer

No concrete introduced bug survives the strict `>=80` confidence threshold for `89770be^..a7e7734`.

The `PDFView.__new__` double concern does not survive: the trusted audit says the forwarded getter/setter pairs use lazy manager ensure accessors, and normal `__init__` eagerly constructs both managers. That removes the claimed `AttributeError` failure path.

The coordinator state desynchronization concern also does not survive: the AST/body audit found the moved coordinator methods equivalent after the intentional controller-read and facade-name mappings, with runtime state intentionally relocated behind controller facades. No stale controller read or net-new failing path is established.

The other named concerns are likewise below threshold: private helper dispatch loss lacks a discovered subclass or monkeypatch contract, text-selection cleanup was already crash-safe via swallowed `RuntimeError`, pending edit omissions are pre-existing and optimization-only, and generic test-coverage complaints are excluded by the dossier’s runtime-suite evidence.

Reportable introduced bugs: none.
