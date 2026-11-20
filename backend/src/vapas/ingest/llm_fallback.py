import json
from collections.abc import Sequence
from functools import partial
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.ingest.layouts import COMMON_DATE_FORMATS, Layout, is_complete
from vapas.ingest.model import Field as Column
from vapas.llm_gateway.gateway import LlmGateway, consume_budget

FieldName = Literal[
    "date", "value_date", "narration", "ref", "debit", "credit", "amount", "direction", "balance", "ignore"
]

PROMPT = """You map the columns of a bank statement table.
The first line is the table header. The other lines are sample rows where letters were replaced by x.
Return only JSON of the form:
{{"columns": [{{"label": "<header label exactly as written>", "field": "<one of: {fields}>"}}],
 "date_format": "<one of: {formats}>"}}
Lines:
{lines}
"""


class ColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=60)
    field: FieldName


class LayoutMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    columns: list[ColumnMapping] = Field(min_length=3, max_length=16)
    date_format: str

    @field_validator("date_format")
    @classmethod
    def known_format(cls, value: str) -> str:
        if value not in COMMON_DATE_FORMATS:
            raise ValueError("unsupported date format")
        return value


class FallbackRejectedError(Exception):
    code = "llm_layout_rejected"


def build_prompt(sketch: Sequence[str]) -> str:
    fields = ", ".join(get_args(FieldName))
    return PROMPT.format(fields=fields, formats=", ".join(COMMON_DATE_FORMATS), lines="\n".join(sketch))


def layout_from_mapping(mapping: LayoutMapping) -> Layout:
    aliases: dict[Column, tuple[str, ...]] = {}
    for column in mapping.columns:
        if column.field != "ignore":
            name = Column(column.field)
            aliases[name] = (*aliases.get(name, ()), column.label)
    if not is_complete(set(aliases)):
        raise FallbackRejectedError("mapping does not cover the required columns")
    formats = (mapping.date_format, *(f for f in COMMON_DATE_FORMATS if f != mapping.date_format))
    return Layout(code="llm_mapping_v1", bank_code="UNKNOWN", signatures=(), aliases=aliases, date_formats=formats)


async def infer_layout(gateway: LlmGateway, conn: AsyncConnection, user_id: UUID, sketch: Sequence[str]) -> Layout:
    if not sketch:
        raise FallbackRejectedError("nothing that looks like a transaction table")
    charge = partial(consume_budget, conn, user_id, gateway.daily_limit)
    answer = await gateway.complete_json(build_prompt(sketch), charge)
    try:
        mapping = LayoutMapping.model_validate(json.loads(answer))
    except (json.JSONDecodeError, ValidationError) as error:
        raise FallbackRejectedError("model answer is not a valid mapping") from error
    return layout_from_mapping(mapping)
