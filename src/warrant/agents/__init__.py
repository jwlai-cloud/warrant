"""The agents. This package is the product (ADR-0008).

It may import an agent framework; `warrant.engine` and `warrant.providers`
may not (ADR-0005's layering rule, which ADR-0008 keeps).
"""
from .base import GovernedResult, WarrantRejected, governed_call, verify_warrant

__all__ = ["governed_call", "verify_warrant", "GovernedResult", "WarrantRejected"]
