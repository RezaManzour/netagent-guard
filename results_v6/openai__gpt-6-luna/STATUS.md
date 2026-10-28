# INCOMPLETE — do not use for guard metrics
The run stopped with HTTP 403 "Key limit exceeded (total limit) $0.50 of $0.50 used" from the endpoint.
Complete: intent extraction for all 771 unique intent texts (llm_intents.jsonl) -> parser_accuracy.csv
(computed offline by `python -m netagent_guard.parser_offline results_v6/openai__gpt-6-luna`).
Incomplete: agent_actions.jsonl has 366 of 1200 scenarios; no guard evaluation was run for this model.
