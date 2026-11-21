import json
from dataclasses import dataclass

from vapas.letters.facts import LetterFacts
from vapas.letters.guardrails import check
from vapas.llm_gateway.gateway import (
    BudgetExceededError,
    Charge,
    LlmGateway,
    LlmUnavailableError,
    SensitiveDataBlockedError,
)

PROMPT = """Improve the wording of this complaint letter so it reads clearly and politely.
Rules: keep every amount, date, number, clause reference, circular reference and every text in square brackets
exactly as written. Do not add facts, amounts, rules or recipients. Keep the language of the letter.
Return only JSON of the form {{"text": "<the improved letter>"}}.
Letter:
{letter}
"""


@dataclass(frozen=True)
class Polished:
    text: str
    polished: bool
    note: str


async def polish(template_text: str, facts: LetterFacts, kind: str, gateway: LlmGateway, charge: Charge) -> Polished:
    try:
        answer = await gateway.complete_json(PROMPT.format(letter=template_text), charge)
        candidate = str(json.loads(answer)["text"])
    except (LlmUnavailableError, BudgetExceededError, SensitiveDataBlockedError) as error:
        return Polished(template_text, False, f"polish skipped: {type(error).__name__}")
    except (json.JSONDecodeError, KeyError, TypeError):
        return Polished(template_text, False, "polish rejected: the model did not return a letter")
    result = check(candidate, facts, kind, final=False)
    if not result.ok:
        return Polished(template_text, False, "polish rejected: " + "; ".join(result.problems))
    return Polished(candidate, True, "polished")
