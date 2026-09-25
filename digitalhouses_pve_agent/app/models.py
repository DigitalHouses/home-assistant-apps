from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareIdentity:
    manufacturer: str | None
    model: str | None
    product_version: str | None
    hardware_source: str
    system_vendor: str | None
    system_model: str | None
    system_version: str | None
    board_vendor: str | None
    board_model: str | None
    board_version: str | None


@dataclass(frozen=True)
class MemorySnapshot:
    total_kib: int
    available_kib: int
    used_kib: int
    usage_percent: float
    swap_total_kib: int
    swap_free_kib: int
    swap_used_kib: int
    swap_usage_percent: float


@dataclass(frozen=True)
class MemoryModule:
    locator: str | None
    bank_locator: str | None
    size_gib: float
    form_factor: str | None
    memory_type: str | None
    speed_mt_s: int | None
    configured_speed_mt_s: int | None
    manufacturer: str | None
    part_number: str | None


@dataclass(frozen=True)
class MemoryInventory:
    total_slots: int
    populated_slots: int
    total_gib: float
    memory_type: str | None
    form_factor: str | None
    speed_mt_s: int | None
    configured_speed_mt_s: int | None
    modules: tuple[MemoryModule, ...]


@dataclass(frozen=True)
class CpuTopology:
    model: str | None
    cores: int
    threads: int
    sockets: int
    threads_per_core: int
    min_mhz: float | None
    max_mhz: float | None


@dataclass(frozen=True)
class CpuFrequencySnapshot:
    available: bool
    average_mhz: float | None
    minimum_current_mhz: float | None
    maximum_current_mhz: float | None
    hardware_minimum_mhz: float | None
    hardware_maximum_mhz: float | None
    scaling_minimum_mhz: float | None
    scaling_maximum_mhz: float | None
    source: str | None
    scaling_driver: str | None
    scaling_governor: str | None
    policy_count: int


@dataclass(frozen=True)
class ThrottleCounters:
    available: bool
    counter_source: str | None
    count_since_boot: int | None
    time_since_boot_ms: int | None
    package_count_since_boot: int | None
    package_time_since_boot_ms: int | None
    core_count_max_since_boot: int | None
    core_time_max_since_boot_ms: int | None
    cpu_entry_count: int
