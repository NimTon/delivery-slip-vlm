from __future__ import annotations

from datetime import date
from unittest.mock import patch

from delivery_vlm.gui_license import GuiLicenseStatus, _http_date_to_utc_date, evaluate_gui_license


def test_http_date_to_utc_date() -> None:
    assert _http_date_to_utc_date("Wed, 30 Apr 2026 12:00:00 GMT") == date(2026, 4, 30)


def test_evaluate_allowed_with_remote() -> None:
    with patch(
        "delivery_vlm.gui_license.fetch_reference_date",
        return_value=(date(2026, 4, 30), True),
    ):
        st = evaluate_gui_license(valid_until=date(2027, 12, 31), timeout=1.0)
    assert isinstance(st, GuiLicenseStatus)
    assert st.allowed
    assert st.reference_date == date(2026, 4, 30)
    assert st.used_remote_date is True
    assert st.check_skipped is False


def test_evaluate_expired_with_remote() -> None:
    with patch(
        "delivery_vlm.gui_license.fetch_reference_date",
        return_value=(date(2028, 1, 1), True),
    ):
        st = evaluate_gui_license(valid_until=date(2027, 12, 31), timeout=1.0)
    assert not st.allowed
    assert "到期" in st.message
    assert st.check_skipped is False


def test_network_required_fails_when_no_remote_date() -> None:
    with patch("delivery_vlm.gui_license.fetch_reference_date", return_value=(None, False)):
        st = evaluate_gui_license(valid_until=date(2027, 12, 31), timeout=1.0)
    assert not st.allowed
    assert st.reference_date is None
    assert "网络" in st.message or "在线" in st.message
    assert st.check_skipped is False


def test_check_disabled_skips_network() -> None:
    with patch("delivery_vlm.gui_license.LICENSE_CHECK_ENABLED", False):
        st = evaluate_gui_license(timeout=1.0)
    assert st.allowed
    assert st.check_skipped is True
    assert st.reference_date is None
