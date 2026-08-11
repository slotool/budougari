import unittest
from datetime import date, timedelta

import juggler_daily as daily


def sample_row(day: date, unit: int, diff: int) -> dict[str, object]:
    return {
        "hall": "テスト店",
        "date": day.isoformat(),
        "day": day,
        "weekday": day.weekday(),
        "day_digit": day.day % 10,
        "unit_digit": unit % 10,
        "machine": "テストジャグラー",
        "unit": str(unit),
        "games": 3000,
        "diff": diff,
        "bb": 10,
        "rb": 10,
        "hit": int(diff >= 500),
    }


class TemporalFeatureTests(unittest.TestCase):
    def test_current_outcome_does_not_change_prior_features(self) -> None:
        start = date(2026, 1, 1)
        history = [sample_row(start + timedelta(days=i), 1, -700 + i * 50) for i in range(14)]
        target_day = start + timedelta(days=14)
        losing = daily.temporal_feature_rows(history + [sample_row(target_day, 1, -3000)])[-1]
        winning = daily.temporal_feature_rows(history + [sample_row(target_day, 1, 3000)])[-1]
        self.assertEqual(losing["_short_features"], winning["_short_features"])

    def test_machine_worst_features_cover_lags_and_rolling_windows(self) -> None:
        start = date(2026, 1, 1)
        rows = []
        for i in range(14):
            day = start + timedelta(days=i)
            rows.append(sample_row(day, 1, -1000 - i * 10))
            rows.append(sample_row(day, 2, 1000 + i * 10))
        target_day = start + timedelta(days=14)
        rows.extend([sample_row(target_day, 1, 0), sample_row(target_day, 2, 0)])

        target_rows = [row for row in daily.temporal_feature_rows(rows) if row["day"] == target_day]
        by_unit = {row["unit"]: {item[0] for item in row["_short_features"]} for row in target_rows}

        self.assertIn("lag1_worst", by_unit["1"])
        self.assertIn("lag2_worst", by_unit["1"])
        self.assertIn("lag3_worst", by_unit["1"])
        for window in daily.SHORT_WINDOWS:
            self.assertIn(f"roll{window}_worst", by_unit["1"])
            self.assertIn(f"roll{window}_best", by_unit["2"])

    def test_answer_feedback_strengthens_hits_and_weakens_misses(self) -> None:
        predictions = []
        for index in range(10):
            predictions.append({
                "result_hit": 1,
                "result_diff": 1500,
                "reasons": "前日凹み: 当たり30% (100件)",
            })
            predictions.append({
                "result_hit": 0,
                "result_diff": -1500,
                "reasons": "前日好調: 当たり20% (100件)",
            })

        multipliers, _ = daily.prediction_feedback(predictions)

        self.assertGreater(multipliers["前日凹み"], 1.0)
        self.assertLess(multipliers["前日好調"], 1.0)
        self.assertGreaterEqual(multipliers["前日好調"], 0.75)
        self.assertLessEqual(multipliers["前日凹み"], 1.25)

    def test_automatic_features_combine_context_and_different_history_groups(self) -> None:
        row = sample_row(date(2026, 1, 8), 17, 0)
        row.update({
            "weekday": 3,
            "day_digit": 8,
            "unit_digit": 7,
            "_short_features": [
                ("lag1_down", "前日凹み", "lag_state"),
                ("roll7_worst", "7日差枚ワースト", "rolling_rank"),
            ],
        })
        labels = dict(daily.automatic_features(row))

        self.assertIn("lag1_down__weekday_3", labels)
        self.assertIn("lag1_down__roll7_worst", labels)
        self.assertIn("前日凹み", labels["lag1_down__weekday_3"])

    def test_discovered_contribution_requires_enough_positive_evidence(self) -> None:
        base = daily.Stats(count=100, hits=20, diff_sum=0)
        strong = daily.Stats(count=40, hits=16, diff_sum=24000)
        weak_sample = daily.Stats(count=10, hits=8, diff_sum=30000)

        accepted = daily.discovered_contribution(strong, base, "木曜 × 前日凹み", {})
        rejected = daily.discovered_contribution(weak_sample, base, "木曜 × 前日凹み", {})

        self.assertIsNotNone(accepted)
        self.assertIn("平均差枚+600", accepted[1])
        self.assertIsNone(rejected)

    def test_target_features_use_prediction_date_context(self) -> None:
        history_day = date(2026, 1, 6)
        target_day = date(2026, 1, 12)
        prior = sample_row(history_day, 17, -1000)
        candidate = sample_row(history_day, 17, -1000)

        target = daily.target_short_features([prior], [candidate], target_day)[("テスト店", "17")]

        self.assertEqual(target["weekday"], target_day.weekday())
        self.assertEqual(target["day_digit"], 2)
        labels = dict(daily.automatic_features(target))
        self.assertTrue(any("2の日" in label for label in labels.values()))
        self.assertFalse(any("6の日" in label for label in labels.values()))

    def test_single_conditions_are_derived_from_numeric_distribution(self) -> None:
        rows = []
        for value in range(100):
            row = sample_row(date(2026, 1, 1), value + 1, 0)
            row["_auto_numeric"] = {"lag1_diff": float(value * 100 - 5000)}
            rows.append(row)

        definitions = daily.build_auto_single_definitions(rows)
        labels = [str(item["label"]) for item in definitions["テスト店"]]

        self.assertTrue(any("前日差枚" in label and "以下" in label for label in labels))
        self.assertTrue(any("前日差枚" in label and "以上" in label for label in labels))


if __name__ == "__main__":
    unittest.main()

