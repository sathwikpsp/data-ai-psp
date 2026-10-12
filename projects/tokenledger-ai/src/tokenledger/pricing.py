"""Effective-dated prices; Decimal calculation, integer micro-USD storage."""

import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from importlib.resources import files
from pathlib import Path

from tokenledger.contracts import UsageEvent


class RateCard:
    def __init__(self, path: Path | None = None):
        source = path or files("tokenledger").joinpath("assets/rates.json")
        self.document = json.loads(source.read_text())
        self.version = self.document["version"]
        self.rates = self.document["rates"]
        if not isinstance(self.version, str) or not self.version or not self.rates:
            raise ValueError("rate card needs a version and rates")
        for rate in self.rates:
            if rate["currency"] != "USD":
                raise ValueError("only USD rates are supported")
            start, end = self._window(rate)
            if start >= end:
                raise ValueError("invalid rate window")
            for key in ("input", "cached_input", "output"):
                price = Decimal(str(rate[key]))
                if not price.is_finite() or not 0 <= price <= 1_000_000:
                    raise ValueError("invalid price per million tokens")
        for i, left in enumerate(self.rates):
            for right in self.rates[i + 1 :]:
                if (left["provider"], left["model"]) != (right["provider"], right["model"]):
                    continue
                a, b = self._window(left)
                c, d = self._window(right)
                if max(a, c) < min(b, d):
                    raise ValueError("overlapping rate windows")

    @staticmethod
    def _window(rate: dict) -> tuple[datetime, datetime]:
        start = datetime.fromisoformat(rate["valid_from"])
        end = datetime.fromisoformat(rate["valid_to"])
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("rate timestamps need timezones")
        return start.astimezone(UTC), end.astimezone(UTC)

    def cost(self, event: UsageEvent) -> int:
        for rate in self.rates:
            start, end = self._window(rate)
            if (event.provider, event.model) == (rate["provider"], rate["model"]) and (
                start <= event.timestamp < end
            ):
                # USD / million tokens equals micro-USD / token; round once per request.
                cost = (
                    (event.input_tokens - event.cached_input_tokens) * Decimal(str(rate["input"]))
                    + event.cached_input_tokens * Decimal(str(rate["cached_input"]))
                    + event.output_tokens * Decimal(str(rate["output"]))
                )
                return int(cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        raise ValueError("unpriced_model_or_date")
