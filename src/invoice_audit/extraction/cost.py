"""Token usage → estimated USD (PLAN 9.7). Prices come from [ai.pricing] in the run file."""

from decimal import Decimal

from invoice_audit.config import Pricing
from invoice_audit.models import TokenUsage

MILLION = Decimal(1_000_000)
ESTIMATE_INPUT_TOKENS = 3000  # per document, for --dry-run
ESTIMATE_OUTPUT_TOKENS = 1000


def usage_cost(usage: TokenUsage, pricing: Pricing, batch: bool = False) -> Decimal:
    cost = (
        Decimal(usage.input_tokens) * pricing.input
        + Decimal(usage.output_tokens) * pricing.output
        + Decimal(usage.cache_read_tokens) * pricing.cache_read
        + Decimal(usage.cache_creation_tokens) * pricing.cache_write
    ) / MILLION
    return cost * pricing.batch_discount if batch else cost


def estimate_cost(documents: int, pricing: Pricing, batch: bool) -> Decimal:
    usage = TokenUsage(input_tokens=documents * ESTIMATE_INPUT_TOKENS, output_tokens=documents * ESTIMATE_OUTPUT_TOKENS)
    return usage_cost(usage, pricing, batch)
