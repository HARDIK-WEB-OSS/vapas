from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from vapas.auth.deps import CurrentUserDep
from vapas.knowledge.search import DEFAULT_LIMIT, MAX_QUERY_CHARS, search

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class Citation(BaseModel):
    citation: str
    instrument_id: str
    instrument_title: str
    instrument_ref: str
    clause: str
    rule_id: str | None
    source_text: str
    url: str
    page: int | None
    legal_status: str
    verified: bool


class SearchOut(BaseModel):
    query: str
    result: Literal["found", "not_found"]
    hits: list[Citation]


@router.get("/search")
async def search_clauses(
    user: CurrentUserDep,
    q: Annotated[str, Query(min_length=2, max_length=MAX_QUERY_CHARS)],
    limit: Annotated[int, Query(ge=1, le=10)] = DEFAULT_LIMIT,
) -> SearchOut:
    hits = await search(user.conn, q, limit)
    citations = [
        Citation(
            citation=h.citation,
            instrument_id=h.instrument_id,
            instrument_title=h.instrument_title,
            instrument_ref=h.instrument_ref,
            clause=h.clause,
            rule_id=h.rule_id,
            source_text=h.body,
            url=h.url,
            page=h.page,
            legal_status=h.legal_status,
            verified=h.verified,
        )
        for h in hits
    ]
    return SearchOut(query=q, result="found" if citations else "not_found", hits=citations)
