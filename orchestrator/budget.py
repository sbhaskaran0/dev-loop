"""Token/cost budget ledger for one run.

Two independent limits: cumulative OUTPUT tokens (the primary, user-stated
unit) and a USD ceiling (backstop for cache/input-heavy pathologies). A
reserve fraction is held back so integrate + finalize always have room.
"""


class Budget:
    def __init__(self, policy: dict, override_tokens: int | None = None):
        self.limit_tokens = override_tokens or policy["budget_output_tokens"]
        self.limit_usd = float(policy["budget_usd_ceiling"])
        self.reserve = float(policy["reserve_fraction"])
        self.entries: list[dict] = []

    def record(self, entry: dict) -> None:
        self.entries.append(entry)

    @property
    def spent_tokens(self) -> int:
        return sum(e.get("output_tokens", 0) for e in self.entries)

    @property
    def spent_usd(self) -> float:
        return round(sum(e.get("cost_usd", 0.0) or 0.0 for e in self.entries), 4)

    @property
    def effective_limit(self) -> int:
        return int(self.limit_tokens * (1 - self.reserve))

    def exhausted(self) -> bool:
        return (self.spent_tokens >= self.effective_limit
                or self.spent_usd >= self.limit_usd)

    def can_admit(self, est_tokens: int, running_est: int = 0) -> bool:
        """Lane admission: spent + running lanes' estimates + this lane's
        estimate must fit inside the reserved-down limit (and USD ceiling)."""
        if self.spent_usd >= self.limit_usd:
            return False
        return (self.spent_tokens + running_est + est_tokens
                <= self.effective_limit)

    def summary(self) -> dict:
        return {
            "limit_output_tokens": self.limit_tokens,
            "effective_limit": self.effective_limit,
            "spent_output_tokens": self.spent_tokens,
            "spent_usd": self.spent_usd,
            "usd_ceiling": self.limit_usd,
            "entries": self.entries,
        }
