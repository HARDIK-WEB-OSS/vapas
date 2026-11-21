import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from vapas.classify.channel_rules import Channel, Kind
from vapas.detect.model import Txn

MAX_REVERSAL_DAYS = 120
MIN_SCORE = 50.0
SPLIT_MAX_PARTS = 3
NAME_SIMILARITY_FLOOR = 60
NOISE = re.compile(r"[\d/\\\-_.:@#]+")
MARKERS = re.compile(r"(?i)\b(rev|reversal|reversed|rvsl|rvrsl|revsl|ret|return|returned|failed|fail|txn|cr|dr)\b")


@dataclass(frozen=True)
class Match:
    debit: Txn
    reversals: tuple[Txn, ...]
    ambiguous: bool = False

    @property
    def reversed_paise(self) -> int:
        return sum(r.amount_paise for r in self.reversals)

    @property
    def is_full(self) -> bool:
        return self.reversed_paise == self.debit.amount_paise

    @property
    def reversal_date(self) -> date:
        return max(r.txn_date for r in self.reversals)


def counterparty(narration: str) -> str:
    return " ".join(MARKERS.sub(" ", NOISE.sub(" ", narration)).split()).lower()


def is_reversal_candidate(txn: Txn) -> bool:
    return txn.is_credit and txn.kind is Kind.REVERSAL


def is_matchable_debit(txn: Txn) -> bool:
    return txn.is_debit and txn.kind is Kind.PAYMENT


def score(debit: Txn, credit: Txn) -> float:
    days = (credit.txn_date - debit.txn_date).days
    if days < 0 or days > MAX_REVERSAL_DAYS or credit.amount_paise > debit.amount_paise:
        return 0.0
    shared_reference = bool(debit.references & credit.references)
    same_channel = credit.channel is debit.channel
    if not shared_reference and credit.channel not in (debit.channel, Channel.UNCLASSIFIED):
        return 0.0
    similarity = fuzz.token_set_ratio(counterparty(debit.narration), counterparty(credit.narration))
    if not shared_reference and (credit.amount_paise != debit.amount_paise or similarity < NAME_SIMILARITY_FLOOR):
        return 0.0
    total = 100.0 if shared_reference else 0.0
    total += 30.0 if credit.amount_paise == debit.amount_paise else 0.0
    total += 20.0 if same_channel else 0.0
    total += similarity / 5
    total += max(0.0, 10.0 - days / 3)
    return total


def _assign(debits: Sequence[Txn], credits: Sequence[Txn]) -> list[tuple[Txn, Txn]]:
    if not debits or not credits:
        return []
    scores = np.array([[score(d, c) for c in credits] for d in debits])
    rows, cols = linear_sum_assignment(-scores)
    return [(debits[r], credits[c]) for r, c in zip(rows, cols, strict=True) if scores[r, c] >= MIN_SCORE]


def _ambiguous(debit: Txn, credit: Txn, debits: Sequence[Txn]) -> bool:
    if debit.references & credit.references:
        return False
    return any(other.key != debit.key and score(other, credit) >= MIN_SCORE for other in debits)


def _split_reversal(debit: Txn, credits: Sequence[Txn]) -> tuple[Txn, ...] | None:
    candidates = [c for c in credits if debit.references & c.references and c.txn_date >= debit.txn_date]
    for size in range(2, SPLIT_MAX_PARTS + 1):
        for parts in combinations(candidates, size):
            if sum(p.amount_paise for p in parts) == debit.amount_paise:
                return tuple(sorted(parts, key=lambda p: (p.txn_date, p.row_index)))
    return None


def match_reversals(transactions: Sequence[Txn]) -> list[Match]:
    debits = [t for t in transactions if is_matchable_debit(t)]
    credits = [t for t in transactions if is_reversal_candidate(t)]
    pairs = _assign(debits, credits)
    used = {c.key for _, c in pairs}
    matched_debits = {d.key for d, _ in pairs}
    matches = [Match(d, (c,), _ambiguous(d, c, debits)) for d, c in pairs]
    leftovers = [c for c in credits if c.key not in used]
    for debit in debits:
        if debit.key in matched_debits:
            continue
        parts = _split_reversal(debit, leftovers)
        if parts:
            matches.append(Match(debit, parts))
            taken = {p.key for p in parts}
            leftovers = [c for c in leftovers if c.key not in taken]
    upgraded: list[Match] = []
    for match in matches:
        if not match.is_full and len(match.reversals) == 1:
            parts = _split_reversal(match.debit, [match.reversals[0], *leftovers])
            if parts:
                taken = {p.key for p in parts}
                leftovers = [c for c in leftovers if c.key not in taken]
                upgraded.append(Match(match.debit, parts))
                continue
        upgraded.append(match)
    return upgraded
