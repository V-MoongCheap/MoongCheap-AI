import unittest

from moongcheap_ai.demand_clustering import load_min_cluster_participants


class ClusteringConfigTest(unittest.TestCase):
    def test_defaults_to_five_participants(self) -> None:
        self.assertEqual(load_min_cluster_participants({}), 5)

    def test_loads_a_configmap_override(self) -> None:
        self.assertEqual(
            load_min_cluster_participants({"CLUSTER_MIN_PARTICIPANTS": "7"}),
            7,
        )

    def test_rejects_invalid_values(self) -> None:
        for value in ("zero", "0", "-1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "must be"):
                    load_min_cluster_participants(
                        {"CLUSTER_MIN_PARTICIPANTS": value}
                    )


if __name__ == "__main__":
    unittest.main()
