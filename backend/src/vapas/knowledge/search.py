import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DEFAULT_LIMIT = 5
MAX_QUERY_CHARS = 300
WORD = re.compile(r"[a-z0-9]+")

THESAURUS: dict[str, tuple[str, ...]] = {
    "refund": ("reversal",),
    "refunded": ("reversal",),
    "return": ("reversal",),
    "returned": ("reversal",),
    "back": ("reversal",),
    "deducted": ("debited",),
    "cut": ("debited",),
    "charged": ("debited",),
    "taken": ("debited",),
    "late": ("delay", "beyond"),
    "delayed": ("delay",),
    "penalty": ("compensation",),
    "fine": ("compensation",),
    "money": ("amount",),
    "cash": ("cash", "dispensed"),
    "swipe": ("pos", "card"),
    "swiped": ("pos", "card"),
    "shop": ("merchant",),
    "store": ("merchant",),
    "online": ("e-commerce", "card", "present"),
    "website": ("e-commerce",),
    "transfer": ("beneficiary", "credited"),
    "sent": ("beneficiary", "credited"),
    "friend": ("beneficiary",),
    "person": ("beneficiary",),
    "autopay": ("mandate", "nach"),
    "emi": ("mandate", "nach"),
    "cancel": ("revocation",),
    "cancelled": ("revocation",),
    "stopped": ("revocation",),
    "aadhaar": ("aeps",),
    "wallet": ("ppi",),
    "complain": ("complaint",),
    "escalate": ("ombudsman", "complaint"),
    "bank": ("regulated", "entity"),
    "reply": ("reply", "resolution"),
    "lawyer": ("advocate",),
    "court": ("court", "tribunal", "forum"),
    "deadline": ("within", "days"),
    "limit": ("within", "days"),
    "cc": ("copy", "endorsed", "marked"),
    "copy": ("endorsed", "marked"),
    "covid": ("working", "days"),
    "holidays": ("working", "days"),
}

SEARCH = text(
    """
    WITH terms AS (
        SELECT DISTINCT lexeme FROM unnest(to_tsvector('english', :words))
    ), total AS (
        SELECT greatest(count(*), 1)::float AS n FROM circular_clauses
    ), frequency AS (
        SELECT t.lexeme, to_tsquery('simple', quote_literal(t.lexeme)) AS tsq,
               (SELECT count(*) FROM circular_clauses c WHERE c.search @@ to_tsquery('simple', quote_literal(t.lexeme)))
                   AS df
        FROM terms t
    ), scored AS (
        SELECT c.id, sum(ln(1 + total.n / f.df)) AS idf
        FROM circular_clauses c, frequency f, total
        WHERE f.df > 0 AND c.search @@ f.tsq
        GROUP BY c.id
    ), combined AS (
        SELECT string_agg(quote_literal(lexeme), ' | ') AS q FROM frequency WHERE df > 0
    )
    SELECT c.instrument_id, c.instrument_title, c.instrument_ref, c.clause, c.rule_id, c.body, c.url, c.page,
           c.legal_status, c.verified, c.source,
           (s.idf + 5 * ts_rank_cd(c.search, to_tsquery('simple', combined.q)))
               * CASE WHEN c.legal_status = 'in_force' THEN 1.0 ELSE 0.6 END AS rank
    FROM scored s JOIN circular_clauses c ON c.id = s.id, combined
    ORDER BY rank DESC, c.verified DESC, c.id
    LIMIT :limit
    """
)


@dataclass(frozen=True)
class ClauseHit:
    instrument_id: str
    instrument_title: str
    instrument_ref: str
    clause: str
    rule_id: str | None
    body: str
    url: str
    page: int | None
    legal_status: str
    verified: bool
    source: str
    rank: float

    @property
    def citation(self) -> str:
        return f"{self.clause}, {self.instrument_title} ({self.instrument_ref})"


def expand(question: str) -> str:
    words = WORD.findall(question.lower()[:MAX_QUERY_CHARS])
    extra = [synonym for word in words for synonym in THESAURUS.get(word, ())]
    return " ".join([*words, *extra])


async def search(conn: AsyncConnection, question: str, limit: int = DEFAULT_LIMIT) -> list[ClauseHit]:
    words = expand(question)
    if not words:
        return []
    rows = await conn.execute(SEARCH, {"words": words, "limit": limit})
    return [ClauseHit(**dict(row._mapping)) for row in rows]
