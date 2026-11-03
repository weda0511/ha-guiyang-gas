# -*- coding: utf-8 -*-
"""传感器: 账单金额/用气量/表读数/欠费/抄表/户号地址等, 2026-11-03 按贵阳燃气(数联慧云)实测接口定制."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GyGasCoordinator
from .const import (
    PAYOFF_MAP,
    STD_ADDRESS,
    STD_AMT_DATE,
    STD_BALANCE,
    STD_BILL_AMT,
    STD_BILL_DATE,
    STD_BILL_STATE,
    STD_CUR_READ_DATE,
    STD_CUR_READING,
    STD_DUE,
    STD_GAS_FEE,
    STD_LAST_READING,
    STD_LATE_FEE,
    STD_METER_NO,
    STD_OTHER_FEE,
    STD_PAYOFF,
    STD_PERIOD_END,
    STD_PERIOD_START,
    STD_READING,
    STD_STATUS,
    STD_UPDATED,
    STD_USAGE,
    STD_USER_NAME,
)

M3 = UnitOfVolume.CUBIC_METERS  # m³


@dataclass(frozen=True)
class GasSensorDescription(SensorEntityDescription):
    std_field: str = ""
    numeric: bool = False      # True = 输出前强制转 float, 供图表/统计使用
    value_map: dict | None = None


SENSOR_DESCRIPTIONS: tuple[GasSensorDescription, ...] = (
    # ---- 欠费 / 账户(来自 getOpayAmt) ----
    GasSensorDescription(
        key="due", std_field=STD_DUE, numeric=True,
        name="燃气欠费", icon="mdi:receipt-text",
        device_class=SensorDeviceClass.MONETARY, state_class=None,
        native_unit_of_measurement="CNY",
    ),
    GasSensorDescription(
        key="balance", std_field=STD_BALANCE, numeric=True,
        name="燃气账户余额", icon="mdi:cash",
        device_class=SensorDeviceClass.MONETARY, state_class=None,
        native_unit_of_measurement="CNY",
    ),
    GasSensorDescription(
        key="gas_fee", std_field=STD_GAS_FEE, numeric=True,
        name="欠费-气费本金", icon="mdi:gas-burner",
        device_class=SensorDeviceClass.MONETARY, state_class=None,
        native_unit_of_measurement="CNY",
    ),
    GasSensorDescription(
        key="late_fee", std_field=STD_LATE_FEE, numeric=True,
        name="欠费-违约金", icon="mdi:alert-circle-outline",
        device_class=SensorDeviceClass.MONETARY, state_class=None,
        native_unit_of_measurement="CNY",
    ),
    GasSensorDescription(
        key="other_fee", std_field=STD_OTHER_FEE, numeric=True,
        name="欠费-其他费用", icon="mdi:receipt",
        device_class=SensorDeviceClass.MONETARY, state_class=None,
        native_unit_of_measurement="CNY",
    ),
    GasSensorDescription(
        key="amt_date", std_field=STD_AMT_DATE,
        name="计费日期", icon="mdi:calendar-today",
    ),
    # ---- 当期账单(来自 getBillList 最新一期) ----
    GasSensorDescription(
        key="bill_amt", std_field=STD_BILL_AMT, numeric=True,
        name="当期燃气费", icon="mdi:receipt-text-outline",
        device_class=SensorDeviceClass.MONETARY, state_class=None,
        native_unit_of_measurement="CNY",
    ),
    GasSensorDescription(
        key="usage", std_field=STD_USAGE, numeric=True,
        name="当期用气量", icon="mdi:fire",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=M3,
    ),
    GasSensorDescription(
        key="reading", std_field=STD_READING, numeric=True,
        name="燃气表读数", icon="mdi:gauge",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=M3,
    ),
    GasSensorDescription(
        key="last_reading", std_field=STD_LAST_READING, numeric=True,
        name="上期表读数", icon="mdi:gauge-empty",
        device_class=SensorDeviceClass.GAS, state_class=None,
        native_unit_of_measurement=M3,
    ),
    GasSensorDescription(
        key="period_start", std_field=STD_PERIOD_START,
        name="账期起", icon="mdi:calendar-start",
    ),
    GasSensorDescription(
        key="period_end", std_field=STD_PERIOD_END,
        name="账期止", icon="mdi:calendar-end",
    ),
    GasSensorDescription(
        key="bill_date", std_field=STD_BILL_DATE,
        name="出账日", icon="mdi:calendar-month",
    ),
    GasSensorDescription(
        key="payoff", std_field=STD_PAYOFF, value_map=PAYOFF_MAP,
        name="缴费状态", icon="mdi:cash-check",
    ),
    GasSensorDescription(
        key="bill_state", std_field=STD_BILL_STATE,
        name="账单状态", icon="mdi:clipboard-check-outline",
    ),
    # ---- 抄表(来自 userucuser/list) ----
    GasSensorDescription(
        key="cur_reading", std_field=STD_CUR_READING, numeric=True,
        name="最新抄表读数", icon="mdi:meter-gas",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=M3,
    ),
    GasSensorDescription(
        key="cur_read_date", std_field=STD_CUR_READ_DATE,
        name="最新抄表日", icon="mdi:calendar-check",
    ),
    GasSensorDescription(
        key="user_name", std_field=STD_USER_NAME,
        name="户名", icon="mdi:account",
    ),
    GasSensorDescription(
        key="address", std_field=STD_ADDRESS,
        name="用气地址", icon="mdi:map-marker",
    ),
    GasSensorDescription(
        key="meter_no", std_field=STD_METER_NO,
        name="燃气表号", icon="mdi:identifier",
    ),
    # ---- 心跳 ----
    GasSensorDescription(
        key="status", std_field=STD_STATUS,
        name="接口状态", icon="mdi:cloud-check",
    ),
    GasSensorDescription(
        key="updated", std_field=STD_UPDATED,
        name="最后更新", icon="mdi:clock-outline",
    ),
)


class GyGasSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: GyGasCoordinator, desc: GasSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_unique_id = "%s_%s" % (coordinator.entry.entry_id, desc.key)
        self._attr_name = "%s %s" % (
            coordinator.entry.title or "贵阳燃气", desc.name
        )

    @property
    def native_value(self) -> Any:
        desc = self.entity_description
        val = self.coordinator.data.get(desc.std_field)
        if val is None or val == "":
            return None
        if desc.value_map and isinstance(val, str):
            return desc.value_map.get(val.strip().upper(), val)
        if desc.numeric:
            try:
                return float(str(val).replace(",", ""))
            except (TypeError, ValueError):
                return None
        return val

    @property
    def available(self) -> bool:
        # status/updated 两个"心跳"实体即使业务值为空也应可见
        if self.entity_description.std_field in ("status", "updated"):
            return self.coordinator.last_update_success
        return self.coordinator.last_update_success and self.native_value is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data["gy_gas"][entry.entry_id]
    async_add_entities(
        [GyGasSensor(coordinator, d) for d in SENSOR_DESCRIPTIONS], update_before_add=False
    )
