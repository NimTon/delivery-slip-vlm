"""
GUI 内置授权：必须联网，通过远程 URL 响应头 ``Date`` 得到参考日期，与程序内写死的截止日期比较。

- 若全部 URL 均无法取得服务器时间，则校验失败（不使用本机日期）。
- 发布前请修改 ``LICENSE_CHECK_ENABLED``、``LICENSE_VALID_UNTIL`` 与（可选）``LICENSE_TIME_URLS``。
"""

from __future__ import annotations

import email.utils
import logging
import ssl
from dataclasses import dataclass
from datetime import date, timezone
from typing import Iterable
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 发布前在此维护授权
# ---------------------------------------------------------------------------
# 是否启用 GUI 授权校验（False 时不访问网络、不校验截止日期）
LICENSE_CHECK_ENABLED: bool = False

# 截止日期（含当日仍有效，次日零时起视为过期；仅当 LICENSE_CHECK_ENABLED 为 True 时生效）
LICENSE_VALID_UNTIL: date = date(2026, 5, 1)

# 依次尝试；取响应头 ``Date``（RFC 7231）换算为 UTC 日历日作参考
LICENSE_TIME_URLS: tuple[str, ...] = (
    "https://www.baidu.com",
    "https://www.qq.com"
)

_DEFAULT_UA = "delivery-slip-vlm-gui/1.0 (+https://example.invalid)"


@dataclass(frozen=True)
class GuiLicenseStatus:
    allowed: bool
    message: str
    reference_date: date | None
    used_remote_date: bool
    check_skipped: bool = False


def _http_date_to_utc_date(date_header: str) -> date | None:
    try:
        dt = email.utils.parsedate_to_datetime(date_header.strip())
    except (TypeError, ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def fetch_reference_date(
    urls: Iterable[str] | None = None,
    *,
    timeout: float = 6.0,
) -> tuple[date | None, bool]:
    """
    返回 ``(服务器 UTC 日历日, 是否成功来自网络)``。
    若所有 URL 均失败则 ``(None, False)``（调用方不得使用本机日期替代）。
    """
    seq = tuple(urls) if urls is not None else LICENSE_TIME_URLS
    ctx = ssl.create_default_context()
    for url in seq:
        u = (url or "").strip()
        if not u:
            continue
        req = Request(
            u,
            method="HEAD",
            headers={"User-Agent": _DEFAULT_UA, "Accept": "*/*"},
        )
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310
                ds = resp.headers.get("Date")
                if not ds:
                    continue
                d = _http_date_to_utc_date(ds)
                if d is not None:
                    return (d, True)
        except (URLError, HTTPError, OSError, TimeoutError, ValueError) as e:
            _log.debug("授权时间探测 HEAD %s 失败: %s", u, e)
            continue
    return (None, False)


def evaluate_gui_license(
    *,
    valid_until: date | None = None,
    urls: Iterable[str] | None = None,
    timeout: float = 6.0,
) -> GuiLicenseStatus:
    if not LICENSE_CHECK_ENABLED:
        return GuiLicenseStatus(
            True,
            "授权校验已在程序内关闭（LICENSE_CHECK_ENABLED = False）。",
            None,
            False,
            True,
        )

    until = valid_until if valid_until is not None else LICENSE_VALID_UNTIL
    ref, remote = fetch_reference_date(urls, timeout=timeout)
    if ref is None:
        _log.warning("授权校验：无法从网络获取服务器时间（已尝试全部 URL）")
        return GuiLicenseStatus(
            False,
            "无法完成在线授权校验，请检查网络连接后重试。",
            None,
            False,
            False,
        )

    allowed = ref <= until
    if allowed:
        return GuiLicenseStatus(True, "授权校验通过。", ref, remote, False)

    return GuiLicenseStatus(
        False,
        "授权已到期，请联系管理员续期或更新程序。",
        ref,
        remote,
        False,
    )
