from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import grape_history_report as collector
import latest_grape_report_impl as report


JST = report.JST
SOURCE_HISTORY = Path("data/grape_history.csv")
HISTORY_CSV = Path("data/juggler_history.csv")
PREDICTIONS_CSV = Path("data/juggler_predictions.csv")
CATALOG_DEBUG_JSON = Path("data/juggler_catalog_debug.json")
REPORT_CATALOG_JSON = Path("data/juggler_report_catalog.json")
FAILED_PAGE_HTML = Path("data/juggler_failed_page.html")
LATEST_CSV = Path("exports/latest_grapes.csv")
ANALYSIS_MD = Path("reports/juggler_analysis.md")
PICKS_MD = Path("reports/juggler_picks.md")
ANALYSIS_HTML = Path("site/juggler_analysis.html")
PICKS_HTML = Path("site/juggler_picks.html")

HISTORY_FIELDS = [
    "hall", "date", "label", "report_url", "machine", "unit", "games", "diff",
    "bb", "rb", "payout_rate", "low_activity", "hit", "collected_at",
]
PREDICTION_FIELDS = [
    "prediction_date", "hall", "machine", "unit", "rank", "score", "reasons",
    "source_date", "created_at", "result_games", "result_diff", "result_bb",
    "result_rb", "result_hit", "evaluated_at",
]
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]
SHORT_WINDOWS = (3, 5, 7, 10, 14)
LAG_LABELS = {1: "前日", 2: "前々日", 3: "3日前"}


@dataclass
class Stats:
    count: int = 0
    hits: int = 0
    diff_sum: int = 0
    games_sum: int = 0
    bb_sum: int = 0
    rb_sum: int = 0
    bonus_games_sum: int = 0

    def add(self, row: dict[str, object]) -> None:
        self.count += 1
        self.hits += int(row["hit"])
        self.diff_sum += int(row["diff"])
        self.games_sum += int(row["games"])
        if isinstance(row.get("bb"), int) and isinstance(row.get("rb"), int):
            self.bb_sum += int(row["bb"])
            self.rb_sum += int(row["rb"])
            self.bonus_games_sum += int(row["games"])

    @property
    def hit_rate(self) -> float:
        return self.hits / self.count if self.count else 0.0

    @property
    def avg_diff(self) -> float:
        return self.diff_sum / self.count if self.count else 0.0

    @property
    def rb_denom(self) -> float | None:
        return self.bonus_games_sum / self.rb_sum if self.rb_sum else None

    @property
    def combined_denom(self) -> float | None:
        total = self.bb_sum + self.rb_sum
        return self.bonus_games_sum / total if total else None


def integer(value: object, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(float(str(value).replace(",", "")))


def floating(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace("%", ""))


def payout_rate(games: int, diff: int, supplied: object = None) -> float:
    if games == 0:
        return 100.0
    parsed = floating(supplied)
    if parsed is not None:
        return parsed
    return round(100.0 + diff / (games * 3) * 100.0, 1)


def is_hit(games: int, diff: int, bb: int | None = None, rb: int | None = None) -> int:
    # Low activity is retained as a miss instead of being discarded.
    if games < 100:
        return 0
    return int(diff >= 500)


def normalize(raw: dict[str, object], collected_at: str | None = None) -> dict[str, object]:
    games = integer(raw.get("games"))
    diff = integer(raw.get("diff"))
    bb = None if raw.get("bb") in (None, "") else integer(raw.get("bb"))
    rb = None if raw.get("rb") in (None, "") else integer(raw.get("rb"))
    return {
        "hall": str(raw.get("hall", "")),
        "date": str(raw.get("date", "")),
        "label": str(raw.get("label", "")),
        "report_url": str(raw.get("report_url", "")),
        "machine": str(raw.get("machine", "")),
        "unit": str(integer(raw.get("unit"))),
        "games": games,
        "diff": diff,
        "bb": "" if bb is None else bb,
        "rb": "" if rb is None else rb,
        "payout_rate": f"{payout_rate(games, diff, raw.get('payout_rate')):.1f}",
        "low_activity": int(games < 100),
        "hit": is_hit(games, diff, bb, rb),
        "collected_at": collected_at or str(raw.get("collected_at", "")),
    }


def history_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    return str(row["hall"]), str(row["date"]), str(row["machine"]), str(row["unit"])


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_history() -> dict[tuple[str, str, str, str], dict[str, object]]:
    source = HISTORY_CSV if HISTORY_CSV.exists() else SOURCE_HISTORY
    return {history_key(row): normalize(row) for row in read_csv(source)}


def add_latest_export(rows: dict[tuple[str, str, str, str], dict[str, object]]) -> None:
    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S%z")
    for raw in read_csv(LATEST_CSV):
        out = normalize(raw, stamp)
        rows[history_key(out)] = out


def add_collected_result(
    rows: dict[tuple[str, str, str, str], dict[str, object]],
    result: dict[str, object],
) -> None:
    latest = result["latest"]
    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S%z")
    for raw in result["rows"]:
        enriched = dict(raw)
        enriched.update({
            "hall": result["hall"],
            "date": latest["date"].isoformat(),
            "label": latest["label"],
            "report_url": latest["url"],
        })
        out = normalize(enriched, stamp)
        rows[history_key(out)] = out


def collect_summary_report(
    client: report.MinRepoClient,
    hall: dict[str, str],
    latest: dict[str, object],
) -> dict[str, object]:
    report_url = f"{str(latest['url']).rstrip('/')}/"
    # Min-repo can return an empty page when the filtered table is opened
    # directly. Open the normal report first so its browsing cookie is set.
    landing_source = client.fetch(report_url)
    if not landing_source.strip():
        raise RuntimeError(f"通常レポートが空です: {report_url}")
    all_url = f"{report_url}?kishu=all&sort=num"
    source = client.fetch(all_url)
    rows = report.parse_all_units(source)
    if not rows:
        FAILED_PAGE_HTML.write_text(source, encoding="utf-8")
        headers = [
            [report.split_link(cell)[0] for cell in table[0]]
            for table in report.parse_tables(source)
            if table
        ]
        raise RuntimeError(f"ジャグラー行が0件です: {all_url} / headers={headers[:8]}")
    return {"hall": hall["name"], "latest": latest, "rows": rows}


def parse_catalog_page(
    source: str,
    hall: dict[str, str],
    today: date,
) -> list[dict[str, object]]:
    items: dict[str, dict[str, object]] = {}
    for table in report.parse_tables(source):
        if not table:
            continue
        header = [report.split_link(cell)[0] for cell in table[0]]
        if not header or header[0] != "日付":
            continue
        for row in table[1:]:
            if not row:
                continue
            label, href = report.split_link(row[0])
            item = collector.candidate(label, href, hall["tag_url"], today)
            if item:
                items[str(item["id"])] = item
    return sorted(items.values(), key=lambda item: item["date"])


def list_reports_catalog(
    client: report.MinRepoClient,
    hall: dict[str, str],
    today: date,
    days: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """List the full lookback window; the hall tag HTML only exposes its first page."""
    since = today - timedelta(days=days)
    source = client.fetch(hall["tag_url"])
    found_by_id: dict[str, dict[str, object]] = {}
    first_page = parse_catalog_page(source, hall, today)
    if not first_page:
        raise RuntimeError(f"過去一覧が0件です（空ページ・アクセス制限の可能性）: {hall['tag_url']}")
    for item in first_page:
        if since <= item["date"] <= today:
            found_by_id[str(item["id"])] = item

    body_match = re.search(r"<body\b[^>]*class=(['\"])(.*?)\1", source, flags=re.IGNORECASE | re.DOTALL)
    body_classes = body_match.group(2).split() if body_match else []
    tag_ids = [int(value[4:]) for value in body_classes if re.fullmatch(r"tag-\d+", value)]
    tag_id = tag_ids[-1] if tag_ids else None
    page_sizes = [len(first_page)]

    for page in range(2, 61):
        url = f"{hall['tag_url'].rstrip('/')}/page/{page}/"
        try:
            page_source = client.fetch(url)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                break
            raise
        page_items = parse_catalog_page(page_source, hall, today)
        page_sizes.append(len(page_items))
        if not page_items:
            break

        for item in page_items:
            if since <= item["date"] <= today:
                found_by_id[str(item["id"])] = item
        if min(item["date"] for item in page_items) < since:
            break

    listed = sorted(found_by_id.values(), key=lambda item: item["date"])
    return listed, {
        "hall": hall["name"],
        "tag_id": tag_id,
        "body_classes": body_classes,
        "api_page_sizes": page_sizes,
        "listed_reports": len(listed),
        "oldest": listed[0]["date"].isoformat() if listed else None,
        "newest": listed[-1]["date"].isoformat() if listed else None,
    }


def current_backfill_batch() -> int:
    status_path = Path("data/juggler_backfill_status.txt")
    if not status_path.exists():
        return 0
    match = re.search(r"(?m)^batch=(\d+)$", status_path.read_text(encoding="utf-8", errors="replace"))
    return int(match.group(1)) if match else 0


def load_report_catalog(today: date, days: int) -> dict[str, list[dict[str, object]]]:
    if not REPORT_CATALOG_JSON.exists():
        return {}
    payload = json.loads(REPORT_CATALOG_JSON.read_text(encoding="utf-8"))
    if payload.get("as_of") != today.isoformat() or int(payload.get("lookback_days", 0)) < days:
        return {}
    output: dict[str, list[dict[str, object]]] = {}
    for hall, items in payload.get("halls", {}).items():
        output[hall] = [dict(item, date=date.fromisoformat(item["date"])) for item in items]
    if len(output) < 2 or any(len(items) < 100 for items in output.values()):
        return {}
    return output


def write_report_catalog(
    catalog: dict[str, list[dict[str, object]]],
    today: date,
    days: int,
) -> None:
    if len(catalog) < 2 or any(len(items) < 100 for items in catalog.values()):
        raise RuntimeError("過去一覧キャッシュが空または不完全なため保存しません")
    payload = {
        "as_of": today.isoformat(),
        "lookback_days": days,
        "halls": {
            hall: [dict(item, date=item["date"].isoformat()) for item in items]
            for hall, items in catalog.items()
        },
    }
    REPORT_CATALOG_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_missing(
    rows: dict[tuple[str, str, str, str], dict[str, object]],
    config: dict[str, object],
    delay: float,
    backfill_days: int,
    max_new_reports: int,
) -> int:
    client = report.MinRepoClient(delay_seconds=delay)
    today = datetime.now(JST).date()
    existing_dates = {(str(r["hall"]), str(r["date"])) for r in rows.values()}
    candidates: list[tuple[dict[str, str], dict[str, object]]] = []
    catalog_debug: list[dict[str, object]] = []
    catalog = load_report_catalog(today, backfill_days)
    catalog_changed = False
    for hall in config["halls"]:
        if hall["name"] in catalog:
            listed = catalog[hall["name"]]
            debug = {
                "hall": hall["name"],
                "source": "cache",
                "listed_reports": len(listed),
                "oldest": listed[0]["date"].isoformat() if listed else None,
                "newest": listed[-1]["date"].isoformat() if listed else None,
            }
        else:
            listed, debug = list_reports_catalog(client, hall, today, backfill_days)
            catalog[hall["name"]] = listed
            catalog_changed = True
        missing_count = 0
        for latest in reversed(listed):
            if (hall["name"], latest["date"].isoformat()) not in existing_dates:
                candidates.append((hall, latest))
                missing_count += 1
        debug["missing_reports"] = missing_count
        catalog_debug.append(debug)

    if catalog_changed:
        write_report_catalog(catalog, today, backfill_days)

    CATALOG_DEBUG_JSON.parent.mkdir(exist_ok=True)
    CATALOG_DEBUG_JSON.write_text(
        json.dumps({"generated_at": datetime.now(JST).isoformat(), "halls": catalog_debug}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    candidates.sort(key=lambda pair: pair[1]["date"], reverse=True)
    added = 0
    for hall, latest in candidates[:max_new_reports]:
        result = collect_summary_report(client, hall, latest)
        add_collected_result(rows, result)
        added += 1
    return added


def write_history(rows: dict[tuple[str, str, str, str], dict[str, object]]) -> None:
    HISTORY_CSV.parent.mkdir(exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (str(r["hall"]), str(r["date"]), str(r["machine"]), int(r["unit"])))
    with HISTORY_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def typed_rows(rows: dict[tuple[str, str, str, str], dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for raw in rows.values():
        row = dict(raw)
        row["day"] = date.fromisoformat(str(row["date"]))
        row["weekday"] = int(row["day"].weekday())
        row["day_digit"] = int(row["day"].day % 10)
        row["unit_digit"] = int(row["unit"]) % 10
        row["games"] = integer(row["games"])
        row["diff"] = integer(row["diff"])
        row["bb"] = None if row.get("bb") in (None, "") else integer(row["bb"])
        row["rb"] = None if row.get("rb") in (None, "") else integer(row["rb"])
        row["hit"] = integer(row["hit"])
        out.append(row)
    return sorted(out, key=lambda r: (r["day"], str(r["hall"]), str(r["machine"]), int(r["unit"])))


def aggregate(rows: list[dict[str, object]], key_fn) -> dict[object, Stats]:
    groups: dict[object, Stats] = defaultdict(Stats)
    for row in rows:
        groups[key_fn(row)].add(row)
    return groups


def condition_tables(rows: list[dict[str, object]]) -> tuple[dict[object, Stats], dict[object, Stats]]:
    weekdays = aggregate(rows, lambda r: (r["hall"], r["weekday"]))
    digits = aggregate(rows, lambda r: (r["hall"], r["day_digit"]))
    return weekdays, digits


def confidence(n: int) -> str:
    if n >= 1000:
        return "高"
    if n >= 400:
        return "中"
    return "低"


def denom(value: float | None) -> str:
    return f"1/{value:.0f}" if value and math.isfinite(value) else "-"


def stats_row(name: str, stats: Stats) -> str:
    return (
        f"| {name} | {stats.count:,} | {stats.hit_rate * 100:.1f}% | "
        f"{stats.avg_diff:+.0f} | {denom(stats.combined_denom)} | {denom(stats.rb_denom)} | {confidence(stats.count)} |"
    )


def build_feature_stats(rows: list[dict[str, object]]) -> dict[str, dict[object, Stats]]:
    return {
        "hall": aggregate(rows, lambda r: r["hall"]),
        "machine": aggregate(rows, lambda r: (r["hall"], r["machine"])),
        "machine_weekday": aggregate(rows, lambda r: (r["hall"], r["machine"], r["weekday"])),
        "machine_digit": aggregate(rows, lambda r: (r["hall"], r["machine"], r["day_digit"])),
        "unit": aggregate(rows, lambda r: (r["hall"], r["unit"])),
        "unit_weekday": aggregate(rows, lambda r: (r["hall"], r["unit"], r["weekday"])),
        "unit_digit": aggregate(rows, lambda r: (r["hall"], r["unit"], r["day_digit"])),
        "tail_digit": aggregate(rows, lambda r: (r["hall"], r["unit_digit"], r["day_digit"])),
    }


def contribution(
    stats: Stats | None,
    base: Stats,
    label: str,
    strength: float = 1.0,
    min_count: int = 5,
) -> tuple[float, str] | None:
    if stats is None or stats.count < min_count:
        return None
    weight = stats.count / (stats.count + 20)
    hit_points = (stats.hit_rate - base.hit_rate) * 42 * weight * strength
    diff_points = max(-4.0, min(4.0, (stats.avg_diff - base.avg_diff) / 180)) * weight * strength
    points = hit_points + diff_points
    return points, f"{label}: 当たり{stats.hit_rate * 100:.0f}% ({stats.count}件)"


def diff_state(diff: int) -> tuple[str, str]:
    if diff <= -500:
        return "down", "凹み"
    if diff >= 500:
        return "up", "好調"
    return "flat", "中間"


def add_short_feature(
    row: dict[str, object], feature_id: str, label: str, group: str
) -> None:
    row.setdefault("_short_features", []).append((feature_id, label, group))


def temporal_feature_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Attach prior-only features to each row without looking at its outcome."""
    histories: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    rows_by_day: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        rows_by_day[row["day"]].append(row)

    enriched: list[dict[str, object]] = []
    for day in sorted(rows_by_day):
        current: list[dict[str, object]] = []
        for original in rows_by_day[day]:
            row = dict(original)
            row["_short_features"] = []
            history = histories[(str(row["hall"]), str(row["unit"]))]
            lag_diffs: dict[int, int] = {}
            rolling_sums: dict[int, int] = {}

            for lag, lag_label in LAG_LABELS.items():
                if len(history) < lag:
                    continue
                prior = history[-lag]
                prior_diff = int(prior["diff"])
                lag_diffs[lag] = prior_diff
                state_id, state_label = diff_state(prior_diff)
                add_short_feature(row, f"lag{lag}_{state_id}", f"{lag_label}{state_label}", "lag_state")
                if int(prior["games"]) < 100:
                    add_short_feature(row, f"lag{lag}_low_activity", f"{lag_label}低稼働", "lag_state")

            if len(history) >= 2:
                newest_state = diff_state(int(history[-1]["diff"]))[0]
                older_state = diff_state(int(history[-2]["diff"]))[0]
                if newest_state == older_state == "down":
                    add_short_feature(row, "down_streak_2", "2日連続凹み", "pattern")
                if newest_state == older_state == "up":
                    add_short_feature(row, "up_streak_2", "2日連続好調", "pattern")
                if newest_state == "down" and older_state == "up":
                    add_short_feature(row, "up_to_down", "前々日好調→前日凹み", "pattern")
                if newest_state == "up" and older_state == "down":
                    add_short_feature(row, "down_to_up", "前々日凹み→前日好調", "pattern")

            if len(history) >= 3:
                states = [diff_state(int(prior["diff"]))[0] for prior in history[-3:]]
                diffs = [int(prio…1310 tokens truncated…n candidates:
        row = dict(candidate)
        row.update({"day": target, "date": target.isoformat(), "_target_short_feature": True})
        placeholders.append(row)
    enriched = temporal_feature_rows(training + placeholders)
    return {
        (str(row["hall"]), str(row["unit"])): row
        for row in enriched
        if row.get("_target_short_feature")
    }


def latest_inventory(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    latest_by_hall: dict[str, date] = {}
    for row in rows:
        hall = str(row["hall"])
        latest_by_hall[hall] = max(latest_by_hall.get(hall, row["day"]), row["day"])
    return {
        hall: [r for r in rows if r["hall"] == hall and r["day"] == latest]
        for hall, latest in latest_by_hall.items()
    }


def previous_by_unit(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    previous: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        previous[(str(row["hall"]), str(row["unit"]))] = row
    return previous


def terminal_targets(feature_stats: dict[str, dict[object, Stats]], hall: str, target: date) -> list[int]:
    if hall != "パーラーゾーン姪浜" or target.day % 10 != 3:
        return []
    base = feature_stats["hall"].get(hall, Stats())
    ranked = []
    for digit in range(10):
        stats = feature_stats["tail_digit"].get((hall, digit, 3))
        if stats and stats.count >= 10:
            score = stats.hit_rate - base.hit_rate + stats.avg_diff / 10000
            ranked.append((score, digit))
    return [digit for _, digit in sorted(ranked, reverse=True)[:2]]


def rule_points(hall: str, target: date, previous: dict[str, object] | None) -> tuple[float, list[str]]:
    digit = target.day % 10
    reasons: list[str] = []
    points = 0.0
    if hall == "パーラーゾーン姪浜":
        priors = {3: (2.0, "3の日"), 5: (3.0, "5の日ジャグラー"), 6: (1.0, "6の日メリハリ"), 9: (2.0, "9の日並び候補")}
        if digit in priors:
            value, label = priors[digit]
            points += value
            reasons.append(f"店舗ルール: {label}")
        if target.weekday() == 5:
            points += 1.5
            reasons.append("店舗ルール: 土曜は各機種配分")
        if target.weekday() == 6 and previous and int(previous["diff"]) < 0:
            points += 3.0
            reasons.append("日曜補正: 前回マイナス")
    elif hall == "アウトバーンブリッツ" and digit in (4, 8):
        points += 3.0
        reasons.append(f"店舗ルール: {digit}の日")
    return points, reasons


def make_picks(rows: list[dict[str, object]], target: date) -> list[dict[str, object]]:
    training = [r for r in rows if r["day"] < target]
    features = build_feature_stats(training)
    short_stats, _ = build_short_feature_stats(training)
    inventories = latest_inventory(training)
    all_candidates = [candidate for candidates in inventories.values() for candidate in candidates]
    current_short = target_short_features(training, all_candidates, target)
    previous = previous_by_unit(training)
    picks: list[dict[str, object]] = []
    for hall, candidates in inventories.items():
        base = features["hall"].get(hall)
        if not base:
            continue
        tails = terminal_targets(features, hall, target)
        by_machine: dict[str, list[dict[str, object]]] = defaultdict(list)
        for candidate in candidates:
            machine = str(candidate["machine"])
            unit = str(candidate["unit"])
            score = 50.0
            reasons: list[tuple[float, str]] = []
            specs = [
                ("machine", (hall, machine), "機種の通算", 0.7),
                ("machine_weekday", (hall, machine, target.weekday()), f"{WEEKDAYS[target.weekday()]}曜×機種", 1.0),
                ("machine_digit", (hall, machine, target.day % 10), f"{target.day % 10}の日×機種", 1.0),
                ("unit", (hall, unit), "台番の通算", 0.7),
                ("unit_weekday", (hall, unit, target.weekday()), f"{WEEKDAYS[target.weekday()]}曜×台番", 0.9),
                ("unit_digit", (hall, unit, target.day % 10), f"{target.day % 10}の日×台番", 0.9),
            ]
            for feature_name, key, label, strength in specs:
                item = contribution(features[feature_name].get(key), base, label, strength)
                if item:
                    points, reason = item
                    score += points
                    reasons.append((abs(points), reason))

            short_row = current_short.get((hall, unit))
            short_by_group: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
            if short_row:
                for feature_id, label, group in short_row["_short_features"]:
                    learned = short_stats["machine"].get((hall, machine, feature_id))
                    if learned is None or learned.count < 15:
                        learned = short_stats["hall"].get((hall, feature_id))
                    item = contribution(learned, base, label, strength=0.9, min_count=15)
                    if item:
                        points, reason = item
                        short_by_group[group].append((abs(points), points, reason))
            group_limits = {
                "lag_state": 2,
                "lag_rank": 2,
                "rolling_state": 1,
                "rolling_hits": 1,
                "rolling_rank": 2,
                "pattern": 2,
                "drought": 1,
            }
            selected_short = []
            for group, learned_items in short_by_group.items():
                learned_items.sort(reverse=True)
                selected_short.extend(learned_items[:group_limits.get(group, 1)])
            selected_short.sort(reverse=True)
            short_points = max(-12.0, min(12.0, sum(item[1] for item in selected_short)))
            score += short_points
            reasons.extend((item[0], item[2]) for item in selected_short[:6])
            prev = previous.get((hall, unit))
            rule_score, rule_reasons = rule_points(hall, target, prev)
            score += rule_score
            reasons.extend((abs(rule_score), text) for text in rule_reasons)
            if tails and int(unit) % 10 in tails:
                score += 7.0
                reasons.append((7.0, f"3の日の末尾候補{int(unit) % 10}"))
            by_machine[machine].append({
                "prediction_date": target.isoformat(), "hall": hall, "machine": machine,
                "unit": unit, "score": round(max(1.0, min(99.0, score)), 1),
                "reasons": " / ".join(text for _, text in sorted(reasons, reverse=True)[:4]) or "通算実績",
                "source_date": candidate["date"],
            })
        for machine, machine_candidates in by_machine.items():
            machine_candidates.sort(key=lambda p: (-float(p["score"]), int(p["unit"])))
            pick_count = 2 if len(machine_candidates) >= 10 else 1
            for rank, pick in enumerate(machine_candidates[:pick_count], 1):
                pick["rank"] = rank
                picks.append(pick)
    return sorted(picks, key=lambda p: (str(p["hall"]), str(p["machine"]), int(p["rank"])))


def load_predictions() -> list[dict[str, str]]:
    return read_csv(PREDICTIONS_CSV)


def update_predictions(predictions: list[dict[str, str]], picks: list[dict[str, object]], rows: list[dict[str, object]], target: date) -> list[dict[str, object]]:
    actual = {(str(r["hall"]), str(r["date"]), str(r["machine"]), str(r["unit"])): r for r in rows}
    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S%z")
    updated: list[dict[str, object]] = []
    for old in predictions:
        row: dict[str, object] = dict(old)
        key = (old["hall"], old["prediction_date"], old["machine"], old["unit"])
        result = actual.get(key)
        if result and old.get("result_hit", "") == "":
            row.update({
                "result_games": result["games"], "result_diff": result["diff"],
                "result_bb": result["bb"], "result_rb": result["rb"],
                "result_hit": result["hit"], "evaluated_at": stamp,
            })
        if old["prediction_date"] != target.isoformat():
            updated.append(row)
    for pick in picks:
        updated.append({
            **pick, "created_at": stamp, "result_games": "", "result_diff": "",
            "result_bb": "", "result_rb": "", "result_hit": "", "evaluated_at": "",
        })
    PREDICTIONS_CSV.parent.mkdir(exist_ok=True)
    updated.sort(key=lambda r: (str(r["prediction_date"]), str(r["hall"]), str(r["machine"]), int(r["rank"])))
    with PREDICTIONS_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        writer.writerows(updated)
    return updated


def prediction_summary(predictions: list[dict[str, object]]) -> tuple[int, int, float, float]:
    evaluated = [p for p in predictions if str(p.get("result_hit", "")) != ""]
    if not evaluated:
        return 0, 0, 0.0, 0.0
    hits = sum(integer(p["result_hit"]) for p in evaluated)
    diffs = [integer(p["result_diff"]) for p in evaluated]
    return len(evaluated), hits, hits / len(evaluated), sum(diffs) / len(diffs)


def render_analysis(rows: list[dict[str, object]], added: int) -> str:
    weekdays, digits = condition_tables(rows)
    short_stats, short_labels = build_short_feature_stats(rows)
    dates = [r["day"] for r in rows]
    halls = sorted(set(str(r["hall"]) for r in rows))
    learned_hall_dates = {(str(r["hall"]), str(r["date"])) for r in rows}
    lines = [
        "# ジャグラー過去傾向分析", "",
        f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}", "",
        f"対象期間: {min(dates).isoformat()}～{max(dates).isoformat()} / {len(rows):,}台分",
        f"学習済み: {len(rows):,}台 / {len(learned_hall_dates):,}店舗日",
        "当たり定義: 100G未満は0。100G以上で差枚+500以上。全期間で同じ基準を使います。",
        "0Gは差枚0・出率100%。低稼働も削除せずDBに保存します。設定を断定する指標ではありません。", "",
    ]
    for hall in halls:
        hall_dates = sorted(set(r["date"] for r in rows if r["hall"] == hall))
        first_day = date.fromisoformat(str(hall_dates[0]))
        last_day = date.fromisoformat(str(hall_dates[-1]))
        missing_days = (last_day - first_day).days + 1 - len(hall_dates)
        lines.extend([f"## {hall}", "", f"掲載日数: {len(hall_dates)} / {hall_dates[0]}～{hall_dates[-1]}",
                      f"未掲載・未取得日: {missing_days}（店休日を含む）", "", "### 曜日別", "",
                      "| 曜日 | 台データ | 当たり率 | 平均差枚 | 合算 | REG | 信頼度 |", "|---|---:|---:|---:|---:|---:|---|"])
        for weekday in range(7):
            stats = weekdays.get((hall, weekday), Stats())
            lines.append(stats_row(WEEKDAYS[weekday], stats))
        lines.extend(["", "### 日付の一の位別", "", "| 一の位 | 台データ | 当たり率 | 平均差枚 | 合算 | REG | 信頼度 |", "|---|---:|---:|---:|---:|---:|---|"])
        for digit in range(10):
            lines.append(stats_row(str(digit), digits.get((hall, digit), Stats())))
        base = aggregate([row for row in rows if row["hall"] == hall], lambda row: row["hall"]).get(hall, Stats())
        hall_short = [
            (feature_id, stats)
            for (feature_hall, feature_id), stats in short_stats["hall"].items()
            if feature_hall == hall and stats.count >= 20
        ]
        hall_short.sort(
            key=lambda item: (
                -abs(item[1].hit_rate - base.hit_rate),
                -item[1].count,
                short_labels.get(item[0], item[0]),
            )
        )
        lines.extend([
            "", "### 短期履歴傾向", "",
            "前日・前々日・3日前、連続傾向、直近3/5/7/10/14掲載日の累計差枚・当たり回数・機種内順位を学習。",
            "| 条件 | 台データ | 当たり率 | 平均差枚 | 合算 | REG | 信頼度 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ])
        for feature_id, stats in hall_short[:40]:
            lines.append(stats_row(short_labels.get(feature_id, feature_id), stats))
    return "\n".join(lines)


def render_picks(picks: list[dict[str, object]], predictions: list[dict[str, object]], target: date) -> str:
    evaluated, hit_count, hit_rate, avg_diff = prediction_summary(predictions)
    lines = [
        f"# {target.isoformat()} ジャグラー狙い台", "",
        f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}", "",
        "前日までに取得できた実績だけで採点。機種ごとに1～2台を選出しています。",
        "点数は順位付け用で、設定投入を保証する確率ではありません。", "",
        "## 答え合わせ成績", "",
        f"- 評価済み予想: {evaluated}",
        f"- 的中: {hit_count} ({hit_rate * 100:.1f}%)" if evaluated else "- 的中: まだ評価データなし",
        f"- 平均差枚: {avg_diff:+.0f}" if evaluated else "- 平均差枚: -", "",
    ]
    current_hall = current_machine = None
    for pick in picks:
        if pick["hall"] != current_hall:
            current_hall = pick["hall"]
            current_machine = None
            lines.extend([f"## {current_hall}", ""])
        if pick["machine"] != current_machine:
            current_machine = pick["machine"]
            lines.extend([f"### {current_machine}", ""])
        lines.extend([
            f"#### {pick['rank']}位 台番{pick['unit']} / スコア{float(pick['score']):.1f}", "",
            f"根拠: {pick['reasons']}", f"使用した最新台構成: {pick['source_date']}", "",
        ])
    return "\n".join(lines)


def markdown_html(markdown: str, title: str, picks: bool = False) -> str:
    body: list[str] = []
    lines = markdown.splitlines()
    i = 0
    open_pick = False
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        if picks and open_pick and line.startswith(("# ", "## ", "### ", "#### ")):
            body.append("</section>")
            open_pick = False
        if line.startswith("#### "):
            css = "pick" if picks else ""
            body.append(f'<section class="{css}"><h4>{html.escape(line[5:])}</h4>')
            open_pick = picks
        elif line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{html.escape(lines[i][2:])}</li>")
                i += 1
            body.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows = [[c.strip() for c in row.strip("|").split("|")] for row in table_lines]
            header = "".join(f"<th>{html.escape(c)}</th>" for c in rows[0])
            table_body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in rows[2:])
            body.append(f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{table_body}</tbody></table></div>')
            continue
        else:
            body.append(f"<p>{html.escape(line)}</p>")
        i += 1
    if open_pick:
        body.append("</section>")
    nav = '<nav><a href="juggler_picks.html">今日の狙い台</a><a href="juggler_analysis.html">過去傾向</a><a href="grape_estimates.html">ぶどう推定</a></nav>'
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
body{{margin:0;background:#f4f6f8;color:#17212b;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.55}}main{{max-width:1050px;margin:auto;padding:12px 10px 48px}}nav{{display:flex;gap:8px;overflow:auto;padding:10px;background:#17212b;position:sticky;top:0;z-index:5}}nav a{{color:#fff;text-decoration:none;white-space:nowrap;padding:7px 10px;border:1px solid #536273;border-radius:4px}}h1{{font-size:23px;margin:12px 0}}h2{{font-size:19px;border-top:3px solid #c7362f;padding-top:10px;margin-top:28px}}h3{{font-size:17px}}h4{{font-size:18px;margin:0 0 8px}}p,li{{font-size:14px}}.table-wrap{{overflow:auto;background:#fff;border:1px solid #d5dce3}}table{{width:100%;min-width:620px;border-collapse:collapse;font-size:13px}}th,td{{padding:8px;border-bottom:1px solid #d5dce3;white-space:nowrap;text-align:right}}th{{background:#eaf0f6}}th:first-child,td:first-child{{text-align:left;position:sticky;left:0;background:#fff;font-weight:700}}th:first-child{{background:#eaf0f6}}.pick{{display:block;background:#fff;border-left:5px solid #c7362f;padding:13px;margin:9px 0;border-radius:4px;box-shadow:0 1px 3px #00000018}}.pick p{{margin:5px 0}}@media(max-width:640px){{main{{padding:8px 8px 36px}}h1{{font-size:20px}}.pick h4{{font-size:18px}}table{{font-size:12px}}}}
</style></head><body>{nav}<main>{''.join(body)}</main></body></html>'''


def write_reports(rows: list[dict[str, object]], picks: list[dict[str, object]], predictions: list[dict[str, object]], target: date, added: int) -> None:
    analysis = render_analysis(rows, added)
    pick_report = render_picks(picks, predictions, target)
    for path in (ANALYSIS_MD, PICKS_MD, ANALYSIS_HTML, PICKS_HTML):
        path.parent.mkdir(exist_ok=True)
    ANALYSIS_MD.write_text(analysis, encoding="utf-8")
    PICKS_MD.write_text(pick_report, encoding="utf-8")
    ANALYSIS_HTML.write_text(markdown_html(analysis, "ジャグラー過去傾向"), encoding="utf-8")
    PICKS_HTML.write_text(markdown_html(pick_report, "今日のジャグラー狙い台", picks=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--delay", type=float, default=None)
    parser.add_argument("--backfill-days", type=int, default=365)
    parser.add_argument("--max-new-reports", type=int, default=120)
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--target-date", default="")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    rows_by_key = load_history()
    add_latest_export(rows_by_key)
    added = 0
    if not args.skip_fetch:
        delay = args.delay if args.delay is not None else float(config.get("delay_seconds", 5))
        added = collect_missing(rows_by_key, config, delay, args.backfill_days, args.max_new_reports)
    write_history(rows_by_key)
    rows = typed_rows(rows_by_key)
    target = date.fromisoformat(args.target_date) if args.target_date else datetime.now(JST).date()
    picks = make_picks(rows, target)
    predictions = update_predictions(load_predictions(), picks, rows, target)
    write_reports(rows, picks, predictions, target, added)


if __name__ == "__main__":
    main()

