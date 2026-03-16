# Heidi-Tender Runtime Prompt Audit

## Summary

This audit covers the runtime prompts that materially affect live pipeline behavior:

- `Step2` prompt in `src/core/pipeline/runner.py`
- `Step7` prompt in `src/core/pipeline/runner.py`
- `Step3` field-rule Copilot prompt in `src/web/backend/app/services/rules.py`

`src/prepare/prompt_optimization_prompt.txt` was treated as a meta-level audit reference, not as the primary runtime artifact.

The main objective of this rewrite is to improve requirement extraction accuracy without changing any JSON contracts, API payloads, or step envelope shapes.

## Step2 Extraction Prompt

### Current intent

- Extract tender requirements for each requested lighting product.
- Align extracted fields with schema-backed `table.column` names.
- Return strict JSON that downstream steps can merge with field rules and later translate into SQL.

### Observed failure modes

- Real runtime output already shows schema-misaligned extractions being dropped after the model response:
  - `src/web/backend/data/jobs/315dcc73-85f9-4f31-8bca-9aee72d2c461/core_runtime/20260315_190508_4rp9wz/step2_extract_requirements.json`
  - uncertainty: `Dropped 2 Step2 requirements with non-schema fields.`
- The old prompt was structurally correct but too thin on evidence policy, file-type behavior, range handling, unit handling, and ambiguity policy.
- The old prompt did not clearly tell the model how to treat PDF prose, DOCX mixed tables, XLSX matrices, or non-mandatory supplier/example text.

### Mismatch with target behavior

- Your target behavior is evidence-first and precision-first.
- The old prompt required schema alignment but did not say strongly enough that uploaded files are the only authority for explicit requirements.
- It left too much room for implied or weakly supported extraction, especially when file search or web knowledge is enabled.
- It did not explain how to report unmapped but explicit concepts in `uncertainties`.

### Rewrite rationale

- The new prompt makes uploaded files the only authority for explicit requirements.
- It explicitly limits external knowledge to interpretation, terminology, units, and field mapping.
- It adds concrete extraction guidance for PDF, DOCX, and XLSX without hardcoding any project- or country-specific examples.
- It makes the precision-over-recall tradeoff explicit.
- It tightens instructions for duplicate fields, quantities, ranges, units, optional/example text, and uncertainty reporting.

### Expected impact

- Fewer non-schema fields emitted by the model.
- Fewer invented or weakly inferred requirements.
- Better handling of table-heavy and mixed-format tender packs.
- Cleaner `uncertainties` output when evidence is ambiguous or unmappable.

## Step3 Rule Copilot Prompt

### Current intent

- Generate reusable `field_rules` from schema metadata.
- Keep hard constraints conservative.
- Produce valid JSON that survives backend validation.

### Observed failure modes

- Existing tests already guard against leakage of Step2-only keys such as `value`, `unit`, and `source`.
- The old prompt used a lighting-specific example row and did not explicitly forbid country-, supplier-, or project-specific rule logic.
- The old wording was valid but somewhat narrow for future generalization, even within the same lighting-tender domain.

### Mismatch with target behavior

- Your target behavior is reusable rule generation with minimal hardcoding.
- The old prompt enforced output shape well, but the example and rationale style encouraged a more field-specific framing than necessary.
- It did not clearly distinguish policy generation from document extraction.

### Rewrite rationale

- The new prompt frames Step3 as generic policy generation rather than requirement extraction.
- It keeps the strict `field_rules` contract and Step2-key prohibitions intact.
- It makes conservative hardness decisions explicit and grounds operator choice in general tender semantics.
- It replaces concrete field examples with placeholder-style abstract examples.

### Expected impact

- Less accidental leakage of extraction-specific thinking into rule generation.
- More reusable rationales across projects and suppliers.
- Better alignment with human-edited rule governance.

## Step7 Ranking Prompt

### Current intent

- Rank SQL-filtered candidates for each tender product using soft constraints.
- Return strict JSON with candidate scores and explanations.

### Observed failure modes

- A real runtime job already fell back because the LLM request exceeded model context:
  - `src/web/backend/data/jobs/315dcc73-85f9-4f31-8bca-9aee72d2c461/core_runtime/20260315_190508_4rp9wz/step7_rank_candidates.json`
  - recorded failure: `context_length_exceeded`
- The old prompt was short, but it did not strongly state per-product independence, measurable-only evaluation, short explanations, or how to behave when soft constraints are missing.

### Mismatch with target behavior

- Your target behavior is concise, explainable ranking focused on measurable soft constraints.
- The old prompt allowed more interpretation latitude than necessary.
- Prompt-only changes can improve focus, but they cannot fully solve oversized-input failures caused by large `step4_json + step6_json` payloads.

### Rewrite rationale

- The new prompt tightens scoring to measurable soft constraints only.
- It makes per-product ranking explicit.
- It keeps explanations short and focused on soft fit.
- It explicitly forbids reinterpreting hard constraints or inventing unsupported evidence.

### Expected impact

- More consistent candidate explanations.
- Less score drift from unmeasurable or implied soft constraints.
- Slightly lower token overhead in the instruction layer, though context-window risk remains until input packing is changed.

## Appendix: Alignment Notes for the Meta Prompt

`src/prepare/prompt_optimization_prompt.txt` should stay meta-level, but it should follow the same principles used in the runtime rewrite:

- Distinguish runtime prompts from planning or audit prompts.
- Ask about success criteria, evidence policy, precision-vs-recall, and hardcoding tolerance before proposing rewrites.
- Evaluate prompts by error modes, not just by whether they produce valid JSON.
- Treat uploaded files as the authority for explicit requirement extraction.
- Encourage abstract template examples instead of project-specific examples.
- Separate prompt problems from non-prompt problems such as context packing or downstream validation.

This phase does not require the meta prompt to drive runtime behavior, so it was not treated as the primary implementation artifact.
