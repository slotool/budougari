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


if __name__ == "__main__":
    unittest.main()

