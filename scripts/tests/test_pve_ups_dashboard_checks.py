"""Render the PVE UPS history and status templates in the existing UI-capable CI job."""
from __future__ import annotations

import unittest

from pve_ups_dashboard_checks import (
    test_history_tree_is_sorted_numerically_across_vm_and_lxc,
    test_shutdown_table_is_numerically_sorted_and_separates_actual_from_budget,
    test_missing_actual_values_are_not_reported_as_zero_time,
)


class PveUpsDashboardContractTests(unittest.TestCase):
    def test_history_is_sorted_numerically(self):
        test_history_tree_is_sorted_numerically_across_vm_and_lxc()

    def test_status_table_distinguishes_fact_and_budget(self):
        test_shutdown_table_is_numerically_sorted_and_separates_actual_from_budget()

    def test_unavailable_actual_duration_is_not_zero(self):
        test_missing_actual_values_are_not_reported_as_zero_time()
