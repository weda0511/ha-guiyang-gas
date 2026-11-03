# -*- coding: utf-8 -*-
"""贵阳燃气(数联慧云 hallapp) 账单接入 —— 配置驱动.

微信公众号「贵阳燃气」网上营业厅(数联慧云 bc.shulianhuiyun.com)没有公开 API,
本集成复用一次抓包得到的登录态(token)轮询三个只读查询接口:

  1) 账单列表  getBillList   -> 当期账单金额 / 用气量 / 抄表读数 / 账期 / 缴费状态
  2) 欠费余额  getOpayAmt    -> 欠费总额 / 气费本金 / 违约金 / 账户余额
  3) 抄表读数  userucuser/list -> 最新抄表读数与抄表日 / 户名 / 地址 / 表号

设计原则(与 gy_water96015 一致):
  - URL / 请求头 / 字段映射全部写在集成配置里, 接口或字段变了改配置即可;
  - 实测鉴权只需 3 个请求头: tenantId / tenantCode / token(不需要 Cookie、UA、Referer);
  - token 失效(HTTP 401/403 或返回关键字)时进入重新认证流程, UI 里重贴新 token 即可。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AUTH_FAIL_KEYWORDS,
    CONF_ACCT_ID,
    CONF_AMT_URL,
    CONF_BODY,
    CONF_FIELD_MAP,
    CONF_HEADERS,
    CONF_METER_URL,
    CONF_METHOD,
    CONF_ROOT_PATH,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    DEFAULT_FIELD_MAP,
    DEFAULT_ROOT_PATH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PREFIX_AMT,
    PREFIX_METER,
    STD_STATUS,
    STD_UPDATED,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


def dig(obj: Any, path: str | None) -> Any:
    """按点路径取值, 支持 data.bsegList.bseg[-1] 形式; 取不到返回 None."""
    if not path:
        return obj
    for part in [p for p in re.split(r"\.|\[|\]", str(path)) if p != ""]:
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.lstrip("-").isdigit():
            try:
                obj = obj[int(part)]
            except (IndexError, ValueError):
                return None
        else:
            return None
    return obj


def merged_config(entry: ConfigEntry) -> dict:
    """options 覆盖 data, 保证老配置兼容."""
    return {**entry.data, **entry.options}


class GyGasCoordinator(DataUpdateCoordinator):
    """轮询三个查询接口, 把返回 JSON 归一化成标准字段."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        cfg = merged_config(entry)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )
        self.entry = entry

    def _headers(self) -> dict:
        cfg = merged_config(self.entry)
        try:
            return json.loads(cfg.get(CONF_HEADERS) or "{}")
        except ValueError as err:
            raise UpdateFailed("请求头不是合法 JSON: %s" % err) from err

    def _body(self) -> str:
        cfg = merged_config(self.entry)
        return (cfg.get(CONF_BODY) or "").replace(
            "{acct_id}", str(cfg.get(CONF_ACCT_ID, ""))
        )

    async def _fetch(self, session, url: str, method: str = "GET", body: str = "") -> Any:
        import aiohttp

        if not url:
            return None
        headers = self._headers()
        async with session.request(
            method, url, headers=headers, data=body or None,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            text = await resp.text()
            if resp.status in (401, 403):
                raise ConfigEntryAuthFailed(
                    "接口返回 HTTP %s, token 已失效, 请重新抓包并更新配置" % resp.status
                )
            if resp.status >= 400:
                raise UpdateFailed("接口返回 HTTP %s: %s" % (resp.status, text[:200]))
        for kw in AUTH_FAIL_KEYWORDS:
            if kw in text:
                raise ConfigEntryAuthFailed("返回含『%s』, 判定登录态失效, 请重新抓包" % kw)
        try:
            return json.loads(text)
        except ValueError as err:
            raise UpdateFailed("返回不是 JSON(接口可能变了): %s" % text[:200]) from err

    async def _async_update_data(self) -> dict:
        import aiohttp

        cfg = merged_config(self.entry)
        try:
            field_map = json.loads(cfg.get(CONF_FIELD_MAP) or "{}")
        except ValueError as err:
            raise UpdateFailed("字段映射不是合法 JSON: %s" % err) from err
        if not field_map:
            field_map = dict(DEFAULT_FIELD_MAP)

        session = async_get_clientsession(self.hass)
        method = cfg.get(CONF_METHOD, "GET")
        body = self._body()

        try:
            main = await self._fetch(session, cfg.get(CONF_URL, ""), method, body)
            amt = await self._fetch(session, cfg.get(CONF_AMT_URL, ""))
            meter = await self._fetch(session, cfg.get(CONF_METER_URL, ""))
        except TimeoutError as err:
            raise UpdateFailed("请求超时") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed("网络错误: %s" % err) from err

        root = dig(main, cfg.get(CONF_ROOT_PATH) or DEFAULT_ROOT_PATH) if main is not None else None
        result: dict = {}

        for std_field, path in field_map.items():
            if not path:
                result[std_field] = None
                continue
            if path.startswith(PREFIX_AMT):
                val = dig(amt, path[len(PREFIX_AMT):])
            elif path.startswith(PREFIX_METER):
                val = dig(meter, path[len(PREFIX_METER):])
            else:
                val = dig(root, path)
                if val is None:
                    val = dig(main, path)  # 允许从主接口响应根部写路径
            result[std_field] = val

        result[STD_STATUS] = "ok"
        result[STD_UPDATED] = datetime.now().astimezone().isoformat(timespec="seconds")
        _LOGGER.debug("gy_gas 更新完成: %s", result)
        return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GyGasCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """配置更新后重建协调器."""
    await hass.config_entries.async_reload(entry.entry_id)
