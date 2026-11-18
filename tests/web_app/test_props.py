import pytest
from aws_cdk import Duration

from gds_idea_cdk_constructs.web_app.props import (
    CronSchedule,
    RefreshSchedule,
    WebAppContainerProperties,
)


def test_refresh_schedule_accepts_rate():
    """Test that a rate-only RefreshSchedule is valid."""
    schedule = RefreshSchedule(rate=Duration.hours(1))
    assert schedule.rate is not None
    assert schedule.cron is None


def test_refresh_schedule_accepts_cron():
    """Test that a cron-only RefreshSchedule is valid."""
    schedule = RefreshSchedule(cron=CronSchedule(minute="0", hour="6"))
    assert schedule.cron.hour == "6"
    assert schedule.rate is None


def test_refresh_schedule_rejects_neither():
    """Test that RefreshSchedule requires at least one of rate or cron."""
    with pytest.raises(ValueError, match=r"exactly one of 'rate' or 'cron'"):
        RefreshSchedule()


def test_refresh_schedule_rejects_both():
    """Test that RefreshSchedule rejects setting both rate and cron."""
    with pytest.raises(ValueError, match=r"exactly one of 'rate' or 'cron'"):
        RefreshSchedule(rate=Duration.hours(1), cron=CronSchedule(minute="0", hour="6"))


def test_refresh_schedule_rejects_sub_minute_rate():
    """Test that a sub-minute rate is rejected at construction, not at synth."""
    with pytest.raises(ValueError, match=r"whole number of minutes"):
        RefreshSchedule(rate=Duration.seconds(30))


def test_refresh_schedule_rejects_fractional_minute_rate():
    """Test that a non-whole-minute rate is rejected."""
    with pytest.raises(ValueError, match=r"whole number of minutes"):
        RefreshSchedule(rate=Duration.seconds(90))


def test_refresh_schedule_every_constructor():
    """Test the every() convenience constructor."""
    schedule = RefreshSchedule.every(Duration.hours(6))
    assert schedule.rate is not None
    assert schedule.cron is None


def test_refresh_schedule_daily_at_constructor():
    """Test the daily_at() convenience constructor."""
    schedule = RefreshSchedule.daily_at(6)
    assert schedule.cron.hour == "6"
    assert schedule.cron.minute == "0"


def test_refresh_schedule_default_retry_settings():
    """Test the default retry policy values."""
    schedule = RefreshSchedule.every(Duration.hours(6))
    assert schedule.retry_attempts == 2
    assert schedule.max_event_age.to_minutes() == 60


def test_cron_schedule_requires_minute_and_hour():
    """Test that minute and hour are required (no silent partial expansion)."""
    with pytest.raises(TypeError):
        CronSchedule(hour="6")


def test_cron_schedule_defaults_to_europe_london():
    """Test that cron fields are interpreted in Europe/London by default."""
    cron = CronSchedule(minute="0", hour="6")
    assert cron.time_zone.timezone_name == "Europe/London"


def test_cron_schedule_rejects_both_day_and_week_day():
    """Test that day and week_day are mutually exclusive (AWS cron rule)."""
    with pytest.raises(ValueError, match=r"at most one of 'day' or 'week_day'"):
        CronSchedule(minute="0", hour="6", day="15", week_day="MON")


def test_container_props_rejects_no_room_for_replacement():
    """Test that a config with no room for a replacement task is rejected."""
    with pytest.raises(ValueError, match=r"no room for a replacement"):
        WebAppContainerProperties(
            desired_count=1, min_healthy_percent=100, max_healthy_percent=150
        )


def test_container_props_defaults_are_valid():
    """Test that the default healthy percents leave room for a replacement."""
    props = WebAppContainerProperties()
    assert props.min_healthy_percent == 50
    assert props.max_healthy_percent == 200
