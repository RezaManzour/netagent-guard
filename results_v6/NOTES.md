# NetAgent Guard v6 notes
Run: `LLM_BASE_URL=https://openrouter.ai/api/v1 LLM_MODEL=anthropic/claude-haiku-5.5 python -m netagent_guard.eval_llm`
(key in LLM_API_KEY). Model anthropic/claude-haiku-5.5, temperature 0, run 2026-10-27, code commit caabdc9 (see run_meta.json).
Seeds 0-4 (200 scenarios each), calibration seed 999, twin noise 0.1, bootstrap B=2000 over pooled scenarios.
Every scenario's action is proposed by the LLM agent from intent+ticket+telemetry (agent_actions.jsonl is the log);
harm labels are recomputed by the oracle for the LLM's action. Two variants: `keyword_parser/` (guards use the v5
deterministic intent parser, primary) and `llm_parser/` (guards use the LLM intent extraction).

## Main finding to report plainly
The LLM agent rarely follows the injected instruction: the LLM action equals the injected replay action in
0-12.5 % of injected scenarios per template (agent_by_template.csv). So only 59 of 1000 eval scenarios are harmful
(v2), versus 453 with replayed actions in v5. CIs on harmful-execution are therefore wide. Tickets are English
(intent text is in styles S1-S6 incl. Finglish S6); no Persian-script tickets were tested.

## keyword_parser, harm v2 (main_metrics_v2.csv)
| budget | guard | HER [95% CI] | FBR [95% CI] |
|---|---|---|---|
| 5% | none | 100.0 [100.0,100.0] | 0.0 |
| 5% | rule | 32.2 [20.4,44.2] | 2.3 [0.9,3.7] |
| 5% | consequence gate alone (twin) | 30.5 [19.1,41.7] | 9.5 [6.8,12.3] |
| 5% | combined without consequence gate (comb-no_twin) | 32.2 [20.4,44.2] | 2.5 [1.1,4.0] |
| 5% | combined | 28.8 [17.2,40.4] | 6.6 [4.3,9.0] |
| 1% | rule | 83.1 [73.1,92.1] | 0.0 |
| 1% | twin | 32.2 [20.4,44.2] | 5.0 [3.0,7.2] |
| 1% | comb-no_twin | 32.2 [20.4,44.2] | 2.5 [1.1,4.0] |
| 1% | combined | 32.2 [20.4,44.2] | 2.5 [1.1,4.0] (twin threshold 99 = twin never fires) |

## Consequence gate on vs off is NOT at equal false-block
v5 at the 5% budget: combined FBR 5.9 % vs comb-no_twin 2.0 % (results/main_metrics_v2.csv) — not matched.
v5 at 1%: identical (twin threshold calibrated to 99, no benefit). v6 repeats this: 6.6 % vs 2.5 % at 5 %, and
identical rows at 1 %. Do not describe the comparison as matched.

## Why comb-no_twin has 2.8 % FBR on unseen styles while intent alone has 75.2 % (v5)
IntentGuard.score returns 0.55 when the keyword parser finds no action ("intent not understood"). On S5/S6 the
parser finds the action in 0 % / 18.4 % of cases, so almost every legitimate held-out-style action scores 0.55.
Intent alone is calibrated at the 5 % budget to threshold 0.5, so 0.55 => block => 75.2 %.
In the combination (eval.decisions and CombinedGuard.decide) the intent score only blocks at a fixed 0.65
(`intent_t=0.65`), so 0.55 never blocks; only rule score >= 1.0 and intent >= 0.65 (wrong action / target /
range) do. The 2.8 % is the rule gateway's blocks. Escalating the 0.55 cases (comb-escalate_unparsed) gives 79.4 %.
So the combination is not "better at understanding" held-out styles: it ignores unparsed intents.

## LLM intent extraction (parser_accuracy.csv, all-fields-correct, eval seeds)
| style | keyword | claude-haiku-5.5 | gpt-6-luna |
|---|---|---|---|
| S5 (held out) | 0.0 % | 55.6 % | 63.6 % |
| S6 Finglish (held out) | 1.2 % | 89.5 % | 90.2 % |
| S1 | 100 % | 64.2 % | 68.2 % |
Action-type accuracy of the LLM is >= 99 % on all styles; the errors are mostly in the element list. With the LLM
parser the combined guard was infeasible at the calibration budget (twin threshold 99) and had FBR 12.0 % [9.1,14.9].

## Usage / limits
Haiku main run: 1,831,136 prompt + 357,081 completion tokens, 1971 calls (~$0.36). Smoke tests ~0.15 M tokens.
The key's total limit ($0.50) was then reached: Luna comparison stopped (see openai__gpt-6-luna/STATUS.md).
