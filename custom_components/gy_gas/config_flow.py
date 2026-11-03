# -*- coding: utf-8 -*-
"""配置流: 首次添加 + token 失效后的重新认证 + 修改配置."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import (
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
)

_LOGGER = logging.getLogger(__name__)


def _request_schema(src: dict | None = None) -> vol.Schema:
    src = src or {}
    return vol.Schema({
        vol.Required(CONF_ACCT_ID, default=src.get(CONF_ACCT_ID, "")): str,
        vol.Optional(CONF_METHOD, default=src.get(CONF_METHOD, "GET")): vol.In(["GET", "POST"]),
        vol.Required(CONF_URL, default=src.get(CONF_URL, "")): str,
        vol.Required(CONF_AMT_URL, default=src.get(CONF_AMT_URL, "")): str,
        vol.Required(CONF_METER_URL, default=src.get(CONF_METER_URL, "")): str,
        vol.Required(CONF_HEADERS, default=src.get(CONF_HEADERS, "{}")): str,
        vol.Optional(CONF_BODY, default=src.get(CONF_BODY, "")): str,
        vol.Optional(CONF_ROOT_PATH, default=src.get(CONF_ROOT_PATH, DEFAULT_ROOT_PATH)): str,
        vol.Optional(CONF_FIELD_MAP, default=src.get(CONF_FIELD_MAP, "")): str,
        vol.Optional(CONF_SCAN_INTERVAL,
                     default=int(src.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))): vol.All(
            int, vol.Range(min=600)),
    })


REAUTH_SCHEMA = vol.Schema({
    vol.Required(CONF_HEADERS): str,
    vol.Optional(CONF_URL, default=""): str,
    vol.Optional(CONF_AMT_URL, default=""): str,
    vol.Optional(CONF_METER_URL, default=""): str,
})


def _validate_json_fields(user_input: dict) -> dict | None:
    errors: dict = {}
    for key in (CONF_HEADERS, CONF_FIELD_MAP):
        raw = (user_input.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                errors[key] = "not_json_object"
        except ValueError:
            errors[key] = "bad_json"
    return errors or None


def _fill_defaults(user_input: dict) -> dict:
    if not (user_input.get(CONF_FIELD_MAP) or "").strip():
        user_input[CONF_FIELD_MAP] = json.dumps(DEFAULT_FIELD_MAP, ensure_ascii=False)
    if not (user_input.get(CONF_ROOT_PATH) or "").strip():
        user_input[CONF_ROOT_PATH] = DEFAULT_ROOT_PATH
    return user_input


class GyGasConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> Any:
        errors: dict = {}
        if user_input is not None:
            errors = _validate_json_fields(user_input) or {}
            if not errors:
                user_input = _fill_defaults(user_input)
                return self.async_create_entry(
                    title="贵阳燃气 (%s)" % user_input[CONF_ACCT_ID], data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_request_schema(), errors=errors
        )

    async def async_step_reauth(self, entry_data: dict) -> Any:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None) -> Any:
        errors: dict = {}
        if user_input is not None and self._reauth_entry is not None:
            if not _validate_json_fields(user_input):
                entry = self._reauth_entry
                data = dict(entry.data)
                data[CONF_HEADERS] = user_input[CONF_HEADERS]
                for key in (CONF_URL, CONF_AMT_URL, CONF_METER_URL):
                    if user_input.get(key):
                        data[key] = user_input[key]
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_abort(reason="reauth_successful")
            errors = _validate_json_fields(user_input) or {}
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "GyGasOptionsFlow":
        return GyGasOptionsFlow(config_entry)


class GyGasOptionsFlow(OptionsFlow):
    """换 token / 改字段映射 / 调轮询间隔, 无需删了重建."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> Any:
        errors: dict = {}
        if user_input is not None:
            errors = _validate_json_fields(user_input) or {}
            if not errors:
                return self.async_create_entry(title="", data=_fill_defaults(user_input))
        src = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_request_schema(src), errors=errors
        )
