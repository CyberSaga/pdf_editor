# Fusion Evaluation

Do not infer quality improvement from the number of model calls. Compare direct Codex and
forced Fusion on the same frozen tasks, context, and deterministic rubric.

For each task record:

- required fact or decision coverage;
- forbidden unsafe or unsupported claims;
- valid and de-duplicated links when citations are required;
- test and lint results for code tasks;
- total latency and subscription call count;
- provider degradation and transcript-extraction failures.

Blind human review is preferred for usefulness and clarity. Automated scores are guardrails,
not a substitute for domain review. Publish a performance claim only when the fixed suite shows
repeatable improvement over direct Codex.
