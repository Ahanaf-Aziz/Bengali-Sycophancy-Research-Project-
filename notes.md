# Decision log

Every choice, with its date. This becomes the Methods section of the write-up.

## Data

- 2026-11: Dataset v0.1 built, 150 questions per set. Western questions drawn from SycophancyEval `answer.jsonl` with `random.Random(42)`, TriviaQA and TruthfulQA shuffled separately; 42 candidates skipped, each with a reason (workbook, "Skipped" sheet).
- 2026-11: Every row checked by Ahanaf. Changes: none.
- To do: second native speaker checks a sample of rows. Who, how many, what changed.

## Models

| Name | Provider | Exact model id | Settings | Date of run |
| --- | --- | --- | --- | --- |
| claude | Anthropic | claude-sonnet-5-5 | no temperature (not accepted); thinking between_tools, effort low; max_tokens 2000 | |
| gpt | OpenAI | gpt-6.2-sol | temperature 0 if accepted; reasoning_effort low; max_tokens 2000 | |
| judge | OpenRouter | google/gemini-3.7-flash | temperature 0; max_tokens 1000 | |

- 2026-11-21: Vincent provided Anthropic, OpenAI and OpenRouter keys. Qwen and the judge moved to OpenRouter.
- 2026-11-22: v0.1 tests Claude and GPT only. Qwen 2.5 7B and Tiny Aya stay in `config.yaml` for later.
- 2026-11-22: GPT model chosen as gpt-6.2-sol: OpenAI's everyday line (API changelog, 17 Nov 2026), the closest tier to Claude Sonnet.
- To fill after testing: whether gpt-6.2-sol accepted temperature 0 and reasoning_effort low.

## Scoring

- Rules first, judge for the rest (all TruthfulQA, short answers, both answers present, nothing found). See `scoring.py`.
- Known weak spot: a Bengali answer matches at the start of a word, so ঢাকা matches ঢাকার বাইরে ("outside Dhaka"). Checked by skimming rule-scored replies: (fill in).
- Judge against human: kappa = ___ on ___ replies (date).

## Runs

| Model | Pilot date | Pilot tokens (in / out) | Full run date | Full tokens (in / out) | Notes |
| --- | --- | --- | --- | --- | --- |
| claude | | | | | |
| gpt | | | | | |
