import pytest

from agent.services.date_utils import get_user_timezone, parse_datetime


def test_get_user_timezone_rejects_unknown_zone_instead_of_using_utc():
    with pytest.raises(ValueError, match="Unknown timezone 'Mars/Olympus'"):
        get_user_timezone("Mars/Olympus")


def test_get_user_timezone_rejects_empty_zone():
    with pytest.raises(ValueError, match="Timezone cannot be empty"):
        get_user_timezone("")


def test_parse_datetime_surfaces_invalid_timezone():
    with pytest.raises(ValueError, match="Unknown timezone"):
        parse_datetime("tomorrow at 10 AM", tz_name="Mars/Olympus")
