from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, build_opener


BASE_URL = "https://min-repo.com"
JST = timezone(timedelta(hours=9))
REPLAY_DENOM = 7.298
WEEKDAY_INDEX = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    display: str
    big_payout: int
    reg_payout: int
    grape_denoms: tuple[float, float, float, float, float, float]
    cherry_denom: float
    bell_denom: float
    pierrot_denom: float
    cherry_payout: int = 2


MODEL_SPECS = (
    ModelSpec("マイジャグラー", "マイジャグラーV", 240, 96, (5.910, 5.870, 5.830, 5.800, 5.760, 5.670), 34.657, 1024.0, 1024.0),
    ModelSpec("ネオアイム", "ネオアイムジャグラーEX", 252, 96, (6.024, 6.020, 6.016, 6.012, 6.008, 5.848), 35.617, 1092.267, 1092.267),
    ModelSpec("アイムジャグラー", "アイムジャグラーEX", 252, 96, (6.024, 6.020, 6.016, 6.012, 6.008, 5.848), 35.617, 1092.267, 1092.267),
    ModelSpec("ゴーゴージャグラー", "ゴーゴージャグラー3", 240, 96, (6.2499, 6.2002, 6.1502, 6.0698, 5.9998, 5.9201), 33.20, 1092.267, 1092.267),
    ModelSpec("ファンキー", "ファンキージャグラー2", 240, 96, (5.94, 5.9298, 5.8798, 5.8301, 5.8000, 5.7700), 35.62, 1092.27, 1092.27),
    ModelSpec("ハッピー", "ハッピージャグラーVIII", 240, 96, (6.04, 6.01, 5.98, 5.86, 5.84, 5.82), 56.55, 655.36, 655.36, 4),
    ModelSpec("ジャグラーガールズ", "ジャグラーガールズSS", 252, 96, (6.01, 6.01, 6.01, 6.01, 5.92, 5.89), 33.301, 1092.267, 1092.267),
    ModelSpec("ミスタージャグラー", "ミスタージャグラー", 240, 96, (6.24212, 6.18381, 6.13690, 6.09807, 6.05973, 6.01689), 37.236, 655.36, 2173.04),
    ModelSpec("ウルトラミラクル", "ウルトラミラクルジャグラー", 240, 96, (5.940, 5.938, 5.936, 5.934, 5.933, 5.929), 34.86, 1024.0, 1024.0),
)


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_cell = False
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table":
            self._in_table = True
            self._rows = []
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []
            self._links = []
        elif self._in_cell and tag == "a" and attrs_dict.get("href"):
            self._links.append(attrs_dict["href"] or "")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_table and tag in {"td", "th"} and self._in_cell:
            text = " ".join("".join(self._cell).split())
            if self._links:
                text = f"{text}|||{self._links[0]}"
            if self._row is not None:
                self._row.append(text)
            self._in_cell = False
        elif self._in_table and tag == "tr":
            if self._row:
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._in_table:
            self.tables.append(self._rows)
            self._in_table = False


class MinRepoClient:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.opener = build_opener()
        self.cookies: dict[str, str] = {}
        self.last_fetch = 0.0

    def fetch(self, url: str) -> str:
        elapsed = time.monotonic() - self.last_fetch
        if self.last_fetch and elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        req = Request(url, headers=self._headers())
        try:
            with self.opener.open(req, timeout=30) as res:
                body = res.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"Fetch failed: {url}: {exc}") from exc
        self.last_fetch = time.monotonic()

        for name, value in re.findall(r"\$\.cookie\('(_d2|_d_a2)',\s*'([^']+)'", body):
            self.cookies[name] = value
        return body

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        }
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
        return headers


def parse_tables(source: str) -> list[list[list[str]]]:
    parser = TableParser()
    parser.feed(source)
    return parser.tables


def split_link(cell: str) -> tuple[str, str | None]:
    if "|||" in cell:
        text, link = cell.split("|||", 1)
        return text.strip(), link.strip()
    return cell.strip(), None


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    text = html.unescape(str(value)).strip()
    if not text or text == "-":
        return None
    negative = False
    if any(mark in text for mark in ("▲", "△", "マイナス")):
        negative = True
    text = text.replace("−", "-").replace("－", "-").replace("▲", "").replace("△", "")
    text = text.replace("+", "").replace(",", "").replace("枚", "").replace("G", "").replace("マイナス", "")
    m = re.search(r"-?\d+", text)
    if not m:
        return None
    number = int(m.group(0))
    if negative and number > 0:
        number *= -1
    return number


def parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace("−", "-").replace("－", "-"))
    return float(m.group(0)) if m else None


def parse_rate(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value)
    if "/" in text:
        text = text.split("/", 1)[1]
    m = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group(0)) if m else None


def report_date_from_text(text: str, today: date) -> date | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})\((.)\)", text)
    if not m:
        return None
    month, day, weekday = int(m.group(1)), int(m.group(2)), m.group(3)
    for year in range(today.year + 1, today.year - 4, -1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate > today:
            continue
        if weekday in WEEKDAY_INDEX and candidate.weekday() != WEEKDAY_INDEX[weekday]:
            continue
        return candidate
    return None


def find_latest_report(source: str, tag_url: str, today: date) -> dict[str, Any]:
    tables = parse_tables(source)
    for table in tables:
        if not table:
            continue
        header = [split_link(c)[0] for c in table[0]]
        if len(header) >= 2 and header[0] == "日付" and "総差枚" in header[1]:
            for row in table[1:]:
                if not row or row[0] == "日付":
                    continue
                date_text, href = split_link(row[0])
                rep_date = report_date_from_text(date_text, today)
                if rep_date and href:
                    report_url = urljoin(tag_url, href)
                    report_id = urlparse(report_url).path.strip("/").split("/")[0]
                    return {"date": rep_date, "url": report_url, "id": report_id, "label": date_text}
    raise RuntimeError("最新掲載日の行が見つかりませんでした")


def is_juggler(machine: str) -> bool:
    return "ジャグラー" in machine or "アイム" in machine


def spec_for(machine: str) -> ModelSpec:
    for spec in MODEL_SPECS:
        if spec.key in machine:
            return spec
    return MODEL_SPECS[1]


def header_map(header: list[str]) -> dict[str, int]:
    return {split_link(name)[0]: i for i, name in enumerate(header)}


def parse_all_units(source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in parse_tables(source):
        if not table:
            continue
        header = [split_link(c)[0] for c in table[0]]
        if {"機種", "台番", "差枚", "G数"}.issubset(set(header)):
            h = header_map(header)
            for row in table[1:]:
                if len(row) < len(header) or split_link(row[0])[0] in {"機種", "平均"}:
                    continue
                machine = split_link(row[h["機種"]])[0]
                if not is_juggler(machine):
                    continue
                unit = parse_int(split_link(row[h["台番"]])[0])
                if unit is None:
                    continue
                rows.append(
                    {
                        "machine": machine,
                        "unit": unit,
                        "diff": parse_int(row[h["差枚"]]),
                        "games": parse_int(row[h["G数"]]),
                        "payout_rate": parse_percent(row[h["出率"]]) if "出率" in h else None,
                        "source": "all",
                    }
                )
    return rows


def parse_machine_units(source: str, machine: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in parse_tables(source):
        if not table:
            continue
        header = [split_link(c)[0] for c in table[0]]
        required = {"台番", "差枚", "G数", "BB", "RB"}
        if not required.issubset(set(header)):
            continue
        h = header_map(header)
        for row in table[1:]:
            if len(row) < len(header) or split_link(row[0])[0] in {"台番", "平均"}:
                continue
            unit = parse_int(split_link(row[h["台番"]])[0])
            if unit is None:
                continue
            rows.append(
                {
                    "machine": machine,
                    "unit": unit,
                    "diff": parse_int(row[h["差枚"]]),
                    "games": parse_int(row[h["G数"]]),
                    "payout_rate": parse_percent(row[h["出率"]]) if "出率" in h else None,
                    "bb": parse_int(row[h["BB"]]),
                    "rb": parse_int(row[h["RB"]]),
                    "combined_rate": parse_rate(row[h["合成"]]) if "合成" in h else None,
                    "bb_rate": parse_rate(row[h["BB率"]]) if "BB率" in h else None,
                    "rb_rate": parse_rate(row[h["RB率"]]) if "RB率" in h else None,
                    "source": "machine",
                }
            )
    return rows


def estimate_grape(row: dict[str, Any]) -> dict[str, Any]:
    games, diff, bb, rb = row.get("games"), row.get("diff"), row.get("bb"), row.get("rb")
    if not all(isinstance(x, int) for x in (games, diff, bb, rb)) or games <= 0:
        return {"grape_denom": None, "grade": "計算不可"}

    spec = spec_for(row["machine"])
    replay_count = games / REPLAY_DENOM
    known_payout = bb * spec.big_payout + rb * spec.reg_payout
    known_payout += games / spec.cherry_denom * spec.cherry_payout
    known_payout += games / spec.bell_denom * 14
    known_payout += games / spec.pierrot_denom * 10
    input_medals = (games - replay_count) * 3
    grape_count = (diff + input_medals - known_payout) / 8
    if grape_count <= 0:
        return {"grape_denom": None, "grade": "計算不可"}
    denom = games / grape_count
    return {"grape_denom": denom, "grade": grade_grape(denom, spec), "model": spec.display}


def grade_grape(denom: float, spec: ModelSpec) -> str:
    s1, s2, s3, s4, s5, s6 = spec.grape_denoms
    if denom <= s6:
        return "設定6近辺以上"
    if denom <= s5:
        return "設定5-6近辺"
    if denom <= s3:
        return "中間以上目安"
    if denom <= s1:
        return "設定1より良好"
    return "弱め"


def fmt_int(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else "-"


def fmt_grape(value: Any) -> str:
    return f"1/{value:.2f}" if isinstance(value, (int, float)) and math.isfinite(value) else "-"


def collect_hall(client: MinRepoClient, hall: dict[str, str], today: date) -> dict[str, Any]:
    tag_html = client.fetch(hall["tag_url"])
    latest = find_latest_report(tag_html, hall["tag_url"], today)
    all_url = f"{latest['url'].rstrip('/')}/?kishu=all&sort=num"
    all_rows = parse_all_units(client.fetch(all_url))

    by_key: dict[tuple[str, int], dict[str, Any]] = {(r["machine"], r["unit"]): r for r in all_rows}
    machines = sorted({r["machine"] for r in all_rows})
    for machine in machines:
        machine_url = f"{BASE_URL}/{latest['id']}/?kishu={quote(machine)}"
        for row in parse_machine_units(client.fetch(machine_url), machine):
            key = (row["machine"], row["unit"])
            merged = by_key.get(key, {"machine": row["machine"], "unit": row["unit"]})
            merged.update({k: v for k, v in row.items() if v is not None})
            by_key[key] = merged

    rows = []
    for row in by_key.values():
        row.update(estimate_grape(row))
        rows.append(row)
    rows.sort(key=lambda r: (r["machine"], r["unit"]))
    return {"hall": hall["name"], "latest": latest, "rows": rows}


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for machine in sorted({r["machine"] for r in rows}):
        ms = [r for r in rows if r["machine"] == machine]
        calc = [r for r in ms if isinstance(r.get("grape_denom"), (int, float))]
        result.append(
            {
                "machine": machine,
                "count": len(ms),
                "calc_count": len(calc),
                "avg_grape": sum(r["grape_denom"] for r in calc) / len(calc) if calc else None,
                "avg_games": round(sum((r.get("games") or 0) for r in ms) / len(ms)) if ms else None,
                "total_diff": sum((r.get("diff") or 0) for r in ms),
                "bb": sum((r.get("bb") or 0) for r in ms),
                "rb": sum((r.get("rb") or 0) for r in ms),
            }
        )
    return result


def write_outputs(results: list[dict[str, Any]]) -> None:
    Path("reports").mkdir(exist_ok=True)
    Path("exports").mkdir(exist_ok=True)

    lines: list[str] = []
    lines.append("# 最新掲載日 ジャグラーぶどう逆算")
    lines.append("")
    lines.append(f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    lines.append("")
    lines.append("前提: 最新掲載日のジャグラー各機種だけを対象に、BB/RB・差枚・G数から台番別に逆算しています。チェリー、ベル、ピエロは実測値ではなく機種別の公表確率前提です。")
    lines.append("")

    csv_rows: list[dict[str, Any]] = []
    for result in results:
        latest = result["latest"]
        rows = result["rows"]
        lines.append(f"## {result['hall']}")
        lines.append("")
        lines.append(f"- 参照データ日: {latest['date'].isoformat()} ({latest['label']})")
        lines.append(f"- レポートURL: {latest['url']}")
        lines.append(f"- 対象台数: {len(rows)}")
        lines.append("")
        lines.append("### 機種別まとめ")
        lines.append("")
        lines.append("| 機種 | 推定ぶどう | 台数 | 計算台数 | 平均G | 合計差枚 | BB/RB |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for s in summarize(rows):
            lines.append(
                f"| {s['machine']} | {fmt_grape(s['avg_grape'])} | {s['count']} | {s['calc_count']} | {fmt_int(s['avg_games'])} | {fmt_int(s['total_diff'])} | {fmt_int(s['bb'])}/{fmt_int(s['rb'])} |"
            )
        lines.append("")
        lines.append("### 台番別")
        lines.append("")
        for machine in sorted({r["machine"] for r in rows}):
            ms = sorted([r for r in rows if r["machine"] == machine], key=lambda r: r["unit"])
            lines.append(f"#### {machine}")
            lines.append("")
            lines.append("| 台番 | 推定ぶどう | 判定 | G数 | 差枚 | BB/RB | 出率 |")
            lines.append("|---:|---:|---|---:|---:|---:|---:|")
            for r in ms:
                rate = f"{r['payout_rate']:.1f}%" if isinstance(r.get("payout_rate"), (int, float)) else "-"
                lines.append(
                    f"| {r['unit']} | {fmt_grape(r.get('grape_denom'))} | {r.get('grade', '-')} | {fmt_int(r.get('games'))} | {fmt_int(r.get('diff'))} | {fmt_int(r.get('bb'))}/{fmt_int(r.get('rb'))} | {rate} |"
                )
                csv_rows.append(
                    {
                        "hall": result["hall"],
                        "date": latest["date"].isoformat(),
                        "machine": machine,
                        "unit": r["unit"],
                        "grape_denom": f"{r.get('grape_denom'):.4f}" if isinstance(r.get("grape_denom"), (int, float)) else "",
                        "grade": r.get("grade", ""),
                        "games": r.get("games", ""),
                        "diff": r.get("diff", ""),
                        "bb": r.get("bb", ""),
                        "rb": r.get("rb", ""),
                        "payout_rate": r.get("payout_rate", ""),
                    }
                )
            lines.append("")

    Path("reports/grape_estimates.md").write_text("\n".join(lines), encoding="utf-8")
    with Path("exports/latest_grapes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["hall"])
        writer.writeheader()
        writer.writerows(csv_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--delay", type=float, default=None)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    delay = args.delay if args.delay is not None else float(config.get("delay_seconds", 10))
    client = MinRepoClient(delay_seconds=delay)
    today = datetime.now(JST).date()

    results = [collect_hall(client, hall, today) for hall in config["halls"]]
    write_outputs(results)


if __name__ == "__main__":
    main()
