"""SQLite persistence, rankings and rename/migration acceptance tests."""

import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, Device


IEEE1 = "0x00158d0000000001"
IEEE2 = "0x00158d0000000002"


def device(ieee, name, network="floor_1"):
    return Device(ieee, network, name, "TRV", "Acme", "Router")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime" / "activity.sqlite"

    def test_durable_counts_and_renames_do_not_reset_history(self):
        with ActivityStore(self.path) as store:
            store.upsert_inventory((device(IEEE1, "Old name"),), observed_at=100)
            store.commit_counts({(120, "floor_1", IEEE1): 3})
            store.commit_counts({(180, "floor_1", IEEE1): 5})
            store.upsert_inventory((device(IEEE1, "New name"),), observed_at=200)
        with ActivityStore(self.path) as store:
            top = store.top(from_epoch=120, until_epoch=240)
            self.assertEqual(top[0]["ieee_address"], IEEE1)
            self.assertEqual(top[0]["messages"], 8)
            self.assertEqual(top[0]["name"], "New name")

    def test_ranking_sort_and_network_filter(self):
        with ActivityStore(self.path) as store:
            store.upsert_inventory((
                device(IEEE1, "A"),
                device(IEEE2, "B", network="floor_2"),
            ), observed_at=100)
            store.commit_counts({
                (120, "floor_1", IEEE1): 2,
                (120, "floor_2", IEEE2): 10,
                (180, "floor_1", IEEE1): 5,
            })
            self.assertEqual(
                [r["ieee_address"] for r in store.top(from_epoch=120, until_epoch=240)],
                [IEEE2, IEEE1],
            )
            one = store.top(from_epoch=120, until_epoch=240, network_id="floor_1")
            self.assertEqual([r["ieee_address"] for r in one], [IEEE1])

    def test_device_transfer_keeps_physical_history(self):
        with ActivityStore(self.path) as store:
            store.upsert_inventory((device(IEEE1, "Office", network="floor_1"),),
                                   observed_at=100)
            store.commit_counts({(120, "floor_1", IEEE1): 2})
            store.upsert_inventory((device(IEEE1, "Office", network="floor_2"),),
                                   observed_at=300)
            store.commit_counts({(360, "floor_2", IEEE1): 4})
            top = store.top(from_epoch=120, until_epoch=420)
            self.assertEqual(top[0]["messages"], 6)
            self.assertEqual(top[0]["network_id"], "floor_2")

    def test_retention_only_deletes_time_buckets(self):
        with ActivityStore(self.path) as store:
            store.upsert_inventory((device(IEEE1, "Living"),), observed_at=100)
            store.commit_counts({(60, "floor_1", IEEE1): 4,
                                 (120, "floor_1", IEEE1): 3})
            self.assertEqual(store.trim_minutes(before_epoch=120), 1)
            self.assertEqual(store.top(from_epoch=0, until_epoch=180)[0]["messages"], 3)
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM devices").fetchone()[0], 1)

    def test_invalid_minutes_not_written(self):
        with ActivityStore(self.path) as store:
            with self.assertRaises(ValueError):
                store.commit_counts({(121, "floor_1", IEEE1): 1})
            with self.assertRaises(ValueError):
                store.commit_counts({(120, "floor_1", IEEE1): -1})
            self.assertEqual(store.top(from_epoch=0, until_epoch=240), [])


if __name__ == "__main__":
    unittest.main()
