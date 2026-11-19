from __future__ import annotations

import sys
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

ALLOWED_HOSTS = {"rbi.org.in", "www.rbi.org.in", "rbidocs.rbi.org.in", "npci.org.in", "www.npci.org.in", "cms.rbi.org.in"}

RuleId = Annotated[str, Field(pattern=r"^[a-z0-9]+(\.[a-z0-9_]+)+$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Issuer(StrEnum):
    RBI = "RBI"
    NPCI = "NPCI"


class LegalStatus(StrEnum):
    IN_FORCE = "in_force"
    IN_FORCE_UNCONFIRMED = "in_force_unconfirmed"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class Verification(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class DayType(StrEnum):
    CALENDAR = "calendar"
    WORKING = "working"


class Party(StrEnum):
    ISSUER_BANK = "issuer_bank"
    BENEFICIARY_BANK = "beneficiary_bank"
    ACQUIRER = "acquirer"
    CUSTOMER_BANK = "customer_bank"
    NOT_STATED = "not_stated"
    UNDERLYING_SYSTEM = "underlying_system"


class FindingPolicy(StrEnum):
    LATE_REVERSAL_CLAIM = "late_reversal_claim"
    NEEDS_USER_INPUT = "needs_user_input"
    WORTH_CHECKING = "worth_checking"
    NOT_DETECTABLE_V1 = "not_detectable_v1"
    DELEGATES = "delegates"


class LetterScope(StrEnum):
    CLAIM = "claim"
    REVERSAL_ONLY = "reversal_only"


class OmbudsmanKind(StrEnum):
    DIRECT_TO_OMBUDSMAN = "direct_to_ombudsman"
    WHO_MAY_FILE = "who_may_file"
    NO_DUPLICATE_GRIEVANCE = "no_duplicate_grievance"
    NON_MAINTAINABLE_REJECTED = "non_maintainable_rejected"
    PRIOR_COMPLAINT_REQUIRED = "prior_complaint_required"
    WAIT_BEFORE_ESCALATION = "wait_before_escalation"
    ESCALATION_DEADLINE = "escalation_deadline"
    LIMITATION = "limitation"
    FILING_CHANNEL = "filing_channel"


class Source(Strict):
    url: HttpUrl
    fetched_on: date
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def official_host(self) -> Self:
        if self.url.host not in ALLOWED_HOSTS:
            raise ValueError(f"source host not allowed: {self.url.host}")
        return self


class Review(Strict):
    status: Verification = Verification.UNVERIFIED
    verified_by: str | None = None
    verified_on: date | None = None

    @model_validator(mode="after")
    def verified_needs_who_and_when(self) -> Self:
        if self.status is Verification.VERIFIED and not (self.verified_by and self.verified_on):
            raise ValueError("verified rules need verified_by and verified_on")
        return self


class Window(Strict):
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to before effective_from")
        return self


class Instrument(Window):
    id: RuleId
    issuer: Issuer
    title: str
    ref_no: str | None
    dept_ref: str | None
    issued_on: date
    legal_status: LegalStatus
    page: Source
    pdf: Source | None = None
    amended_by: list[RuleId] = []
    notes: str | None = None


class Compensation(Strict):
    per_day_inr: int = Field(gt=0)
    beyond_days: int = Field(ge=0)
    payee_text: str | None = None


class TatRule(Window):
    id: RuleId
    clause: str
    payment_system: str
    scenario: str
    responsible: Party
    deadline_days: int | None = Field(default=None, ge=0)
    day_type: DayType = DayType.CALENDAR
    compensation: Compensation | None
    finding_policy: FindingPolicy
    delegates_to: list[RuleId] = []
    user_inputs: list[str] = []
    letter_disclosure: str | None = None
    letter_scope: LetterScope = LetterScope.CLAIM
    escalation_wait_days: int | None = Field(default=None, gt=0)
    merged_from: str | None = None
    quote: str
    review: Review = Review()

    @model_validator(mode="after")
    def quote_is_source_text_only(self) -> Self:
        if "(cells merged" in self.quote:
            raise ValueError("quote must contain only source text; use merged_from for merged cells")
        return self

    @model_validator(mode="after")
    def user_input_policy_needs_inputs(self) -> Self:
        if self.user_inputs and self.finding_policy is not FindingPolicy.NEEDS_USER_INPUT:
            raise ValueError("user_inputs only apply to needs_user_input rules")
        if self.user_inputs and not self.letter_disclosure:
            raise ValueError("user-supplied facts need a letter_disclosure")
        return self

    @model_validator(mode="after")
    def worth_checking_never_claims(self) -> Self:
        if self.finding_policy is FindingPolicy.WORTH_CHECKING and self.letter_scope is not LetterScope.REVERSAL_ONLY:
            raise ValueError("worth_checking rules may only request the reversal")
        return self

    @model_validator(mode="after")
    def deadline_matches_compensation(self) -> Self:
        if self.finding_policy is FindingPolicy.DELEGATES:
            if not self.delegates_to or self.compensation or self.deadline_days is not None:
                raise ValueError("delegating rules carry no own deadline or compensation")
            return self
        if self.deadline_days is None:
            raise ValueError("deadline_days required")
        if self.compensation and self.compensation.beyond_days != self.deadline_days:
            raise ValueError("compensation must start after the deadline")
        return self


class DayTypeOverride(Window):
    id: RuleId
    clause: str
    applies_to: RuleId
    day_type: DayType
    quote: str
    ambiguity: str | None = None
    review: Review = Review()


class OmbudsmanRule(Window):
    id: RuleId
    clause: str
    kind: OmbudsmanKind
    days: int | None = Field(default=None, ge=0)
    longer_system_wait_applies: bool = False
    anchor: str | None = None
    text: str
    quote: str
    source: Source | None = None
    review: Review = Review()

    @model_validator(mode="after")
    def system_wait_only_on_wait_rules(self) -> Self:
        if self.longer_system_wait_applies and self.kind is not OmbudsmanKind.WAIT_BEFORE_ESCALATION:
            raise ValueError("longer_system_wait_applies is only valid on wait_before_escalation rules")
        return self


class RuleFile(Strict):
    instrument: Instrument
    tat_rules: list[TatRule] = []
    day_type_overrides: list[DayTypeOverride] = []
    ombudsman_rules: list[OmbudsmanRule] = []

    @model_validator(mode="after")
    def rules_inside_instrument_window(self) -> Self:
        start = self.instrument.effective_from
        for rule in [*self.tat_rules, *self.ombudsman_rules]:
            if rule.effective_from < start:
                raise ValueError(f"{rule.id} starts before its instrument")
        return self


class RuleBook(Strict):
    files: dict[str, RuleFile]

    @model_validator(mode="after")
    def references_resolve(self) -> Self:
        ids = [i for f in self.files.values() for i in _ids(f)]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate ids: {sorted(dupes)}")
        known = set(ids)
        for f in self.files.values():
            refs = [*f.instrument.amended_by, *(o.applies_to for o in f.day_type_overrides)]
            refs += [d for r in f.tat_rules for d in r.delegates_to]
            missing = [r for r in refs if r not in known]
            if missing:
                raise ValueError(f"{f.instrument.id} references unknown ids: {missing}")
        return self


def _ids(f: RuleFile) -> list[str]:
    rules = [*f.tat_rules, *f.day_type_overrides, *f.ombudsman_rules]
    return [f.instrument.id, *(r.id for r in rules)]


def load_rulebook(root: Path) -> RuleBook:
    files = {
        str(p.relative_to(root)): RuleFile.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
        for p in sorted((root / "rbi").glob("*.yaml"))
    }
    return RuleBook(files=files)


def main() -> int:
    book = load_rulebook(Path(__file__).parent)
    for name, f in book.files.items():
        rules = [*f.tat_rules, *f.day_type_overrides, *f.ombudsman_rules]
        verified = sum(r.review.status is Verification.VERIFIED for r in rules)
        print(f"OK  {name}: {len(rules)} rules, {verified} verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
