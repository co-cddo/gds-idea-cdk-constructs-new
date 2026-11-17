import pytest
from aws_cdk import Duration

from gds_idea_cdk_constructs.web_app.props import RefreshSchedule


def test_refresh_schedule_accepts_rate():
    """Test that a rate-only RefreshSchedule is valid."""
    schedule = RefreshSchedule(rate=Duration.hours(1))
    assert schedule.rate is not None
    assert schedule.cron is None


def test_refresh_schedule_accepts_cron():
    """Test that a cron-only RefreshSchedule is valid."""
    schedule = RefreshSchedule(cron={"hour": "6", "minute": "0"})
    assert schedule.cron == {"hour": "6", "minute": "0"}
    assert schedule.rate is None


def test_refresh_schedule_rejects_neither():
    """Test that RefreshSchedule requires at least one of rate or cron."""
    with pytest.raises(ValueError, match=r"exactly one of 'rate' or 'cron'"):
        RefreshSchedule()


def test_refresh_schedule_rejects_both():
    """Test that RefreshSchedule rejects setting both rate and cron."""
    with pytest.raises(ValueError, match=r"exactly one of 'rate' or 'cron'"):
        RefreshSchedule(rate=Duration.hours(1), cron={"hour": "6"})
