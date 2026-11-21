import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from vapas.classify.channel_rules import Channel, Kind
from vapas.detect.model import Txn, TxnKey, UserAnswers
from vapas.ingest.model import Direction

MERCHANTS = ("SWIGGY", "AMAZON", "BIGBASKET", "IRCTC", "APOLLO", "ZOMATO", "MYNTRA")
PEOPLE = ("RAVI KUMAR", "PRIYA SHARMA", "ANIL MEHTA", "SUNITA DEVI")
CLAIM_CHANNELS = (Channel.ATM, Channel.POS, Channel.ECOM, Channel.UPI)
D, C = Direction.DEBIT, Direction.CREDIT


@dataclass
class Scenario:
    transactions: list[Txn] = field(default_factory=list)
    answers: UserAnswers = field(default_factory=UserAnswers)
    expected_claims: dict[TxnKey, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)


class Builder:
    def __init__(self, seed: int, start: date) -> None:
        self.rng = random.Random(seed)
        self.start = start
        self.scenario = Scenario()
        self.next_id = seed * 1_000_000

    def day(self, low: int = 0, high: int = 300) -> date:
        return self.start + timedelta(days=self.rng.randint(low, high))

    def ref(self) -> bytes:
        return self.rng.randbytes(16)

    def add(
        self,
        day: date,
        direction: Direction,
        amount: int,
        channel: Channel,
        kind: Kind,
        text: str,
        refs: tuple[bytes, ...] = (),
    ) -> Txn:
        self.next_id += 1
        txn = Txn(
            TxnKey(self.next_id, day),
            "s1",
            self.next_id,
            day,
            None,
            direction,
            amount,
            None,
            channel,
            kind,
            text,
            frozenset(refs),
        )
        self.scenario.transactions.append(txn)
        return txn

    def label(self, name: str) -> None:
        self.scenario.labels[name] = self.scenario.labels.get(name, 0) + 1

    def amount(self) -> int:
        return self.rng.choice((50_000, 100_000, 150_000, 200_000, self.rng.randrange(1_000, 500_000)))

    def noise(self, count: int) -> None:
        for _ in range(count):
            channel = self.rng.choice((Channel.UPI, Channel.POS, Channel.ATM, Channel.NEFT, Channel.ECOM))
            who = self.rng.choice(MERCHANTS + PEOPLE)
            self.add(
                self.day(), D, self.amount(), channel, Kind.PAYMENT, f"{channel.value.upper()} {who}", (self.ref(),)
            )
        for month in range(10):
            self.add(
                self.start + timedelta(days=30 * month + 1),
                C,
                6_000_000,
                Channel.NEFT,
                Kind.RECEIPT,
                "NEFT SALARY ACME",
            )

    def late_claim(self) -> None:
        channel = self.rng.choice(CLAIM_CHANNELS)
        merchant = self.rng.choice(MERCHANTS)
        ref = self.ref()
        when = self.day(0, 250)
        delay = self.rng.randint(1, 30)
        amount = self.amount()
        debit = self.add(when, D, amount, channel, Kind.PAYMENT, f"{channel.value.upper()} {merchant}", (ref,))
        self.add(
            when + timedelta(days=5 + delay),
            C,
            amount,
            channel,
            Kind.REVERSAL,
            f"REV {channel.value.upper()} {merchant}",
            (ref,),
        )
        if channel is Channel.UPI:
            self.scenario.answers.payee_was_merchant[debit.key] = True
        self.scenario.expected_claims[debit.key] = delay * 10_000
        self.label("late_claim")

    def late_claim_without_reference(self) -> None:
        channel = self.rng.choice((Channel.ATM, Channel.POS, Channel.ECOM))
        merchant = self.rng.choice(MERCHANTS)
        when = self.day(0, 250)
        delay = self.rng.randint(1, 30)
        amount = self.amount()
        debit = self.add(when, D, amount, channel, Kind.PAYMENT, f"{channel.value.upper()} {merchant}")
        self.add(
            when + timedelta(days=5 + delay),
            C,
            amount,
            channel,
            Kind.REVERSAL,
            f"REV {channel.value.upper()} {merchant}",
        )
        self.scenario.expected_claims[debit.key] = delay * 10_000
        self.label("late_claim_without_reference")

    def twin_purchase(self) -> None:
        merchant = self.rng.choice(MERCHANTS)
        amount = self.amount()
        first_day = self.day(0, 200)
        second_day = first_day + timedelta(days=self.rng.randint(3, 20))
        ref = self.ref()
        self.add(first_day, D, amount, Channel.POS, Kind.PAYMENT, f"POS {merchant}", (self.ref(),))
        debit = self.add(second_day, D, amount, Channel.POS, Kind.PAYMENT, f"POS {merchant}", (ref,))
        delay = self.rng.randint(1, 20)
        self.add(
            second_day + timedelta(days=5 + delay), C, amount, Channel.POS, Kind.REVERSAL, f"POS REV {merchant}", (ref,)
        )
        self.scenario.expected_claims[debit.key] = delay * 10_000
        self.label("twin_purchase_one_reversed")

    def on_time(self) -> None:
        channel = self.rng.choice(CLAIM_CHANNELS)
        ref = self.ref()
        when = self.day(0, 250)
        amount = self.amount()
        self.add(when, D, amount, channel, Kind.PAYMENT, f"{channel.value.upper()} SHOP", (ref,))
        self.add(when + timedelta(days=self.rng.randint(0, 5)), C, amount, channel, Kind.REVERSAL, "REV SHOP", (ref,))
        self.label("on_time_reversal")

    def merchant_refund(self) -> None:
        merchant = self.rng.choice(MERCHANTS)
        when = self.day(0, 250)
        amount = self.amount()
        ref = self.ref()
        self.add(when, D, amount, Channel.UPI, Kind.PAYMENT, f"UPI {merchant}", (ref,))
        self.add(
            when + timedelta(days=self.rng.randint(6, 40)),
            C,
            amount,
            Channel.UPI,
            Kind.MERCHANT_REFUND,
            f"UPI REFUND {merchant}",
            (ref,),
        )
        self.label("merchant_refund")

    def credit_push(self) -> None:
        person = self.rng.choice(PEOPLE)
        when = self.day(0, 250)
        amount = self.amount()
        ref = self.ref()
        self.add(when, D, amount, Channel.IMPS, Kind.PAYMENT, f"IMPS {person}", (ref,))
        self.add(
            when + timedelta(days=self.rng.randint(3, 30)),
            C,
            amount,
            Channel.IMPS,
            Kind.REVERSAL,
            f"IMPS RET {person}",
            (ref,),
        )
        self.label("credit_push_late")

    def decoy_reversal(self) -> None:
        when = self.day(0, 250)
        amount = self.amount()
        self.add(when, D, amount, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE", (self.ref(),))
        self.add(
            when + timedelta(days=self.rng.randint(10, 30)),
            C,
            amount,
            Channel.POS,
            Kind.REVERSAL,
            "POS REV OTHER SHOP",
            (self.ref(),),
        )
        self.label("decoy_unrelated_reversal")

    def partial(self) -> None:
        when = self.day(0, 250)
        ref = self.ref()
        self.add(when, D, 100_000, Channel.ATM, Kind.PAYMENT, "ATM WDL", (ref,))
        self.add(when + timedelta(days=12), C, 40_000, Channel.ATM, Kind.REVERSAL, "ATM REV", (ref,))
        self.label("partial_reversal")


def build(seed: int, start: date = date(2026, 1, 1), noise: int = 250) -> Scenario:
    builder = Builder(seed, start)
    builder.noise(noise)
    makers = (
        (builder.late_claim, 4),
        (builder.late_claim_without_reference, 2),
        (builder.twin_purchase, 2),
        (builder.on_time, 4),
        (builder.merchant_refund, 3),
        (builder.credit_push, 2),
        (builder.decoy_reversal, 2),
        (builder.partial, 1),
    )
    for make, count in makers:
        for _ in range(builder.rng.randint(0, count)):
            make()
    return builder.scenario
