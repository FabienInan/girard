"""
Tracking des coûts tokens par run.
"""


class TokenTracker:
    # Tarifs Claude Haiku ($/1M tokens, mars 2025)
    PRICE_INPUT       = 0.80
    PRICE_OUTPUT      = 4.00
    PRICE_CACHE_WRITE = 1.00
    PRICE_CACHE_READ  = 0.08

    def __init__(self):
        self.input_tokens       = 0
        self.output_tokens      = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens  = 0

    def record(self, usage_metadata: dict):
        if not usage_metadata:
            return
        self.input_tokens       += usage_metadata.get("input_tokens", 0)
        self.output_tokens      += usage_metadata.get("output_tokens", 0)
        self.cache_write_tokens += usage_metadata.get("cache_creation_input_tokens", 0)
        self.cache_read_tokens  += usage_metadata.get("cache_read_input_tokens", 0)

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens         / 1_000_000 * self.PRICE_INPUT
            + self.output_tokens      / 1_000_000 * self.PRICE_OUTPUT
            + self.cache_write_tokens / 1_000_000 * self.PRICE_CACHE_WRITE
            + self.cache_read_tokens  / 1_000_000 * self.PRICE_CACHE_READ
        )

    def summary(self) -> dict:
        return {
            "input_tokens"       : self.input_tokens,
            "output_tokens"      : self.output_tokens,
            "cache_write_tokens" : self.cache_write_tokens,
            "cache_read_tokens"  : self.cache_read_tokens,
            "estimated_cost_usd" : round(self.estimated_cost_usd, 5),
        }
