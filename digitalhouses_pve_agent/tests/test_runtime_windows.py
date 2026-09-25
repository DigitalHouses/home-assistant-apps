import math

from app.presentation import PublicationProfile
from app.runtime_windows import RollingAverage, TwoProfileDecision


def test_rolling_average_excludes_missing_and_expired_samples():
    window = RollingAverage(60.0)
    window.observe(0.0, 10.0)
    window.observe(10.0, None)
    window.observe(20.0, 30.0)

    assert window.average(20.0) == 20.0
    assert window.average(70.1) == 30.0


def test_empty_window_returns_none_not_zero():
    assert RollingAverage(60.0).average(100.0) is None


def test_invalid_samples_are_excluded_not_zeroed():
    window = RollingAverage(60.0)
    window.observe(0.0, 20.0)
    window.observe(10.0, True)
    window.observe(20.0, False)
    window.observe(30.0, math.nan)
    window.observe(40.0, math.inf)
    window.observe(50.0, -math.inf)

    assert window.average(50.0) == 20.0


def test_window_requires_positive_duration():
    for value in (0.0, -1.0):
        try:
            RollingAverage(value)
        except ValueError:
            pass
        else:
            raise AssertionError("non-positive rolling window must be rejected")


def test_profile_uses_strict_comparison_and_keeps_state_on_equality():
    decision = TwoProfileDecision(threshold=80.0)

    assert decision.update(81.0) is PublicationProfile.DETAIL
    assert decision.update(80.0) is PublicationProfile.DETAIL
    assert decision.update(79.0) is PublicationProfile.NORMAL
    assert decision.update(None) is PublicationProfile.NORMAL


def test_profile_ignores_invalid_decision_average():
    decision = TwoProfileDecision(threshold=80.0)

    assert decision.update(81.0) is PublicationProfile.DETAIL
    assert decision.update(True) is PublicationProfile.DETAIL
    assert decision.update(math.nan) is PublicationProfile.DETAIL
    assert decision.update(math.inf) is PublicationProfile.DETAIL
