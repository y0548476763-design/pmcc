"""
risk_guard.py — Golden Rule Validator + PMCC structural integrity checks
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    is_valid:  bool
    reason:    str
    rule_name: str


class RiskGuard:
    """
    Validates proposed orders against PMCC rules before submission.
    Any violation blocks the order entirely.
    """

    # ─── The Golden Rule ─────────────────────────────────────────────────────

    @staticmethod
    def golden_rule(
        short_call_strike:    float,
        leaps_strike:         float,
        leaps_cost_basis:     float,
        premium_received:     float,
    ) -> ValidationResult:
        """
        Block if: short_call_strike < (leaps_strike + leaps_cost_basis - premium_received)

        This ensures we can NEVER lose money if both legs are exercised/called away.
        Break-even on assignment = leaps_strike + leaps_cost_basis - premium_received.
        Short call strike must be above this level.
        """
        breakeven = leaps_strike + leaps_cost_basis - premium_received
        if short_call_strike < breakeven:
            return ValidationResult(
                is_valid=False,
                reason=(
                    f"⛔ GOLDEN RULE VIOLATED: Short call strike ${short_call_strike:.2f} "
                    f"< breakeven ${breakeven:.2f} "
                    f"(LEAPS strike ${leaps_strike:.2f} + cost ${leaps_cost_basis:.2f} "
                    f"− premium ${premium_received:.2f}). "
                    f"Order BLOCKED."
                ),
                rule_name="GoldenRule",
            )
        return ValidationResult(
            is_valid=True,
            reason=(
                f"✅ Golden Rule OK: Strike ${short_call_strike:.2f} ≥ "
                f"breakeven ${breakeven:.2f} "
                f"(margin: ${short_call_strike - breakeven:.2f})"
            ),
            rule_name="GoldenRule",
        )

    # ─── Delta Health ─────────────────────────────────────────────────────────

    @staticmethod
    def delta_health_check(
        leaps_delta: float,
        short_delta: float,
        threshold: float = 0.50,
    ) -> ValidationResult:
        """Warn (but don't block) if delta spread is collapsing."""
        health = leaps_delta - abs(short_delta)
        if health < threshold:
            return ValidationResult(
                is_valid=True,   # warn only, not block
                reason=(
                    f"⚠️  Delta Health {health:.2f} < {threshold} "
                    f"— PMCC structure weakening. Consider rolling short."
                ),
                rule_name="DeltaHealth",
            )
        return ValidationResult(
            is_valid=True,
            reason=f"✅ Delta Health {health:.2f} ≥ {threshold}",
            rule_name="DeltaHealth",
        )

    # ─── Composite Validation ────────────────────────────────────────────────

    @classmethod
    def validate_short_call(
        cls,
        short_call_strike: float,
        leaps_strike:      float,
        leaps_cost_basis:  float,
        premium_received:  float,
        leaps_delta:       float = 0.80,
        short_delta:       float = 0.30,
    ) -> list[ValidationResult]:
        """Run all checks and return list of results (pass/fail)."""
        results = [
            cls.golden_rule(
                short_call_strike, leaps_strike,
                leaps_cost_basis, premium_received
            ),
            cls.delta_health_check(leaps_delta, short_delta),
        ]
        return results

    @staticmethod
    def is_blocked(results: list[ValidationResult]) -> bool:
        return any(not r.is_valid for r in results)

    @staticmethod
    def summary(results: list[ValidationResult]) -> str:
        return "\n".join(r.reason for r in results)


# Singleton
_guard = RiskGuard()


def get_guard() -> RiskGuard:
    return _guard
