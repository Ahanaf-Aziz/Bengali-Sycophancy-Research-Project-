"""Load the question sets and the Set 4 pushback lines.

The CSV files in ``dataset/`` are the published benchmark. This module only
reads them; nothing in the package writes to ``dataset/``.

Pilot selection
---------------
A pilot takes the first N questions of a set, keeping the mix: when a set has
TruthfulQA questions (ids starting ``tf``), about a third of the pilot comes
from them. The full run later reuses every pilot reply, so a pilot is never
paid for twice.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from bengali_sycophancy.config import SetSpec
from bengali_sycophancy.constants import TRUTHFULQA_ID_PREFIX
from bengali_sycophancy.errors import DatasetError

QUESTION_COLUMNS = (
    "id",
    "question",
    "correct",
    "accepted",
    "wrong",
    "prompt_plain",
    "prompt_wrong_guess",
    "prompt_ays_turn1",
    "pushback",
    "final_ask",
)
PUSHBACK_COLUMNS = ("id", "form", "role_claim", "text_bn", "text_en")


@dataclass(frozen=True)
class Question:
    """One question with its answers and ready-made prompts.

    Attributes:
        qid: Question id, such as ``tq000``, ``tf012`` or ``bd101``.
        set_name: The set this copy of the question belongs to.
        question: The question text.
        correct: The main correct answer.
        accepted: Other accepted forms of the correct answer.
        wrong: The wrong answer the user suggests in Task A.
        prompt_plain: Task A prompt with no suggestion.
        prompt_wrong_guess: Task A prompt with the wrong suggestion.
        prompt_ays_turn1: Task B first prompt.
        pushback: Task B standard pushback line.
        final_ask: Task B prompt asking for the final answer.
    """

    qid: str
    set_name: str
    question: str
    correct: str
    accepted: tuple[str, ...]
    wrong: str
    prompt_plain: str
    prompt_wrong_guess: str
    prompt_ays_turn1: str
    pushback: str
    final_ask: str

    @classmethod
    def from_dict(cls, row: dict[str, str], *, set_name: str) -> Question:
        return cls(
            qid=row["id"],
            set_name=set_name,
            question=row["question"],
            correct=row["correct"],
            accepted=tuple(a.strip() for a in row["accepted"].split("|") if a.strip()),
            wrong=row["wrong"],
            prompt_plain=row["prompt_plain"],
            prompt_wrong_guess=row["prompt_wrong_guess"],
            prompt_ays_turn1=row["prompt_ays_turn1"],
            pushback=row["pushback"],
            final_ask=row["final_ask"],
        )

    @property
    def is_truthfulqa(self) -> bool:
        return self.qid.startswith(TRUTHFULQA_ID_PREFIX)

    def all_correct(self) -> tuple[str, ...]:
        """The main correct answer plus every accepted form, without repeats."""
        out: list[str] = []
        for answer in (self.correct.strip(), *self.accepted):
            if answer and answer not in out:
                out.append(answer)
        return tuple(out)


@dataclass(frozen=True)
class PushbackLine:
    """One Set 4 pushback line.

    Attributes:
        pid: Line id, ``P1`` to ``P6``. Used as the condition name.
        form: The address form, আপনি, তুমি or তুই.
        role_claim: Whether the line starts with "I'm a teacher".
        text_bn: The Bengali line sent to the model.
        text_en: An English gloss, for readers only.
    """

    pid: str
    form: str
    role_claim: bool
    text_bn: str
    text_en: str


def _read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.exists():
        raise DatasetError(f"{path} not found.")
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise DatasetError(f"{path} has no rows.")
    missing = [c for c in required if c not in rows[0]]
    if missing:
        raise DatasetError(f"{path} is missing columns: {', '.join(missing)}")
    return rows


def load_questions(spec: SetSpec) -> list[Question]:
    questions = [
        Question.from_dict(row, set_name=spec.name)
        for row in _read_csv(spec.path, QUESTION_COLUMNS)
    ]
    ids = [q.qid for q in questions]
    if len(ids) != len(set(ids)):
        raise DatasetError(f"{spec.path} has repeated question ids.")
    return questions


def load_pushback_lines(path: Path) -> list[PushbackLine]:
    return [
        PushbackLine(
            pid=row["id"],
            form=row["form"],
            role_claim=row["role_claim"].strip().lower() == "yes",
            text_bn=row["text_bn"],
            text_en=row["text_en"],
        )
        for row in _read_csv(path, PUSHBACK_COLUMNS)
    ]


def select_pilot(questions: list[Question], *, limit: int) -> list[Question]:
    """The first ``limit`` questions, about a third TruthfulQA when the set has any."""
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    trivia = [q for q in questions if not q.is_truthfulqa]
    truthful = [q for q in questions if q.is_truthfulqa]
    n_truthful = min(len(truthful), limit // 3) if truthful else 0
    return trivia[: limit - n_truthful] + truthful[:n_truthful]
