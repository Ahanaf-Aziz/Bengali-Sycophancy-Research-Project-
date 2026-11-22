# Outputs

Everything here comes from real model runs. Mock-model output goes to `scratch/` and is never committed.

| Path | Made by | Contents |
| --- | --- | --- |
| `runs/<model>/<set>.jsonl` | `run` | One record per prompt: the full conversation sent, every reply, the stop reason, tokens and the temperature actually sent |
| `runs/<model>/run_log.jsonl` | `run` | One line per session: model settings, sets, pilot limit, Python and SDK versions |
| `runs/<model>/errors.log` | `run` | Calls that failed, if any, and were retried later |
| `scores/<model>.jsonl` | `score` | One line per scored reply: label (`correct`, `incorrect`, `unclear`) and method (`rule` or `judge`) |
| `scores/judge_cache.jsonl` | `score` | Every judge decision, by judge model, set, question and exact reply |
| `results/summary_task_a.csv` | `analyse` | Accuracy with and without the wrong guess, and the drop |
| `results/summary_task_b.csv` | `analyse` | Flip rate per set and pushback line |
| `results/comparisons.csv` | `analyse` | Language effect, content effect and Set 4 comparisons |
| `results/judge_check.csv` | `check_judge` | The 200 replies labelled by hand next to the judge's labels |
| `results/judge_agreement.json` | `check_judge` | Agreement and Cohen's kappa |
| `figures/*.png` | `figures` | Result figures (PDF versions are made too but not committed) |

Record keys look like `are_you_sure|bd012|P3`: task, question id, condition.
