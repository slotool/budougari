import unittest
from datetime import date
from unittest.mock import patch

import latest_grape_report_impl as report
import run_latest_grapes as runner


class MachinePageParserTests(unittest.TestCase):
    def test_report_is_refetched_after_auth_cookie_is_discovered(self) -> None:
        client = report.MinRepoClient(0)
        first = "<html><table><tr><td>-</td></tr></table><script>$.cookie('_d_a2', 'token')</script></html>"
        second = "<html><table><tr><td>-1,030</td></tr></table></html>"
        with patch.object(client, "_request", side_effect=[first, second]) as request:
            body = client.fetch("https://min-repo.com/1/?kishu=test")

        self.assertEqual(body, second)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(client.cookies["_d_a2"], "token")

    def test_individual_page_fills_exact_negative_diff(self) -> None:
        source = """
        <table class="kishu">
          <tr><th>機種</th><th>差枚</th><th>G数</th><th>出率</th></tr>
          <tr><td>ファンキージャグラー２ＫＴ</td><td>-1,030</td><td>4,774</td><td>92.8%</td></tr>
        </table>
        <table>
          <tr><th>BB</th><th>RB</th><th>合成</th><th>BB率</th><th>RB率</th></tr>
          <tr><td>14</td><td>11</td><td>1/191</td><td>1/341</td><td>1/434</td></tr>
        </table>
        """

        row = runner.parse_individual_unit(source, "ファンキージャグラー２ＫＴ", 353)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["diff"], -1030)
        self.assertEqual(row["games"], 4774)
        self.assertEqual(row["payout_rate"], 92.8)
        self.assertEqual(row["bb"], 14)
        self.assertEqual(row["rb"], 11)
        self.assertEqual(row["combined_rate"], 191.0)

    def test_all_units_reads_bonus_columns_without_machine_page(self) -> None:
        source = """
        <table>
          <tr><th>機種</th><th>台番</th><th>差枚</th><th>G数</th><th>出率</th>
              <th>BB</th><th>RB</th><th>合成</th><th>BB率</th><th>RB率</th></tr>
          <tr><td>ゴーゴージャグラー３</td><td>153</td><td>-1,333</td><td>2,603</td><td>82.9%</td>
              <td>5</td><td>7</td><td>1/217</td><td>1/521</td><td>1/372</td></tr>
        </table>
        """

        rows = report.parse_all_units(source)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["diff"], -1333)
        self.assertEqual(rows[0]["bb"], 5)
        self.assertEqual(rows[0]["rb"], 7)
        self.assertEqual(rows[0]["combined_rate"], 217.0)
        self.assertEqual(rows[0]["bb_rate"], 521.0)
        self.assertEqual(rows[0]["rb_rate"], 372.0)

    def test_graph_list_fills_missing_negative_diff(self) -> None:
        source = """
        <ul class="slump_list">
          <li><a href="https://min-repo.com/1/?num=1801">1801</a>
            <table><tr><th class="samai_cell">差枚</th><th>G数</th><th>合成</th></tr>
              <tr><td class="samai_cell">-891</td><td>3,461</td><td>1/182</td></tr></table>
          </li>
          <li><a href="https://min-repo.com/1/?num=1802">1802</a>
            <table><tr><th class="samai_cell">差枚</th><th>G数</th><th>合成</th></tr>
              <tr><td class="samai_cell">500</td><td>1,947</td><td>1/150</td></tr></table>
          </li>
        </ul>
        <table>
          <tr><th>台番</th><th>差枚</th><th>G数</th><th>出率</th><th>BB</th><th>RB</th>
              <th>合成</th><th>BB率</th><th>RB率</th></tr>
          <tr><td>1801</td><td>-</td><td>3,461</td><td>-</td><td>11</td><td>8</td>
              <td>1/182</td><td>1/315</td><td>1/433</td></tr>
          <tr><td>1802</td><td>500</td><td>1,947</td><td>108.6%</td><td>8</td><td>5</td>
              <td>1/150</td><td>1/243</td><td>1/389</td></tr>
        </table>
        """

        rows = report.parse_machine_units(source, "ゴーゴージャグラー３")

        self.assertEqual(rows[0]["unit"], 1801)
        self.assertEqual(rows[0]["diff"], -891)
        self.assertEqual(rows[0]["games"], 3461)
        self.assertAlmostEqual(rows[0]["payout_rate"], 91.42, places=2)
        self.assertEqual(rows[1]["diff"], 500)

    def test_incomplete_latest_report_falls_back_to_previous_complete_day(self) -> None:
        candidates = [
            {"date": date(2026, 9, 18), "url": "https://min-repo.com/2/", "id": "2"},
            {"date": date(2026, 9, 17), "url": "https://min-repo.com/1/", "id": "1"},
        ]
        incomplete = {
            "hall": "テスト店",
            "latest": candidates[0],
            "rows": [{"machine": "マイジャグラーV", "unit": 1, "games": 1000, "diff": None}],
        }
        complete = {
            "hall": "テスト店",
            "latest": candidates[1],
            "rows": [{"machine": "マイジャグラーV", "unit": 1, "games": 1000, "diff": -500}],
        }

        class FakeClient:
            def fetch(self, _url: str) -> str:
                return "tag page"

        hall = {"name": "テスト店", "tag_url": "https://min-repo.com/tag/test/"}
        with (
            patch.object(runner, "report_candidates_resilient", return_value=candidates),
            patch.object(runner, "collect_hall_candidate", side_effect=[incomplete, complete]) as collect,
        ):
            result = runner.collect_hall_resilient(FakeClient(), hall, date(2026, 9, 19))

        self.assertEqual(result["latest"]["date"], date(2026, 9, 17))
        self.assertEqual(collect.call_count, 2)

if __name__ == "__main__":
    unittest.main()
