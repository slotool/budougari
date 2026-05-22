from __future__ import annotations

import html
import json
import re
from datetime import date
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import latest_grape_report_impl as report
from latest_grape_report_overrides import write_outputs_with_grade


PLAY_LEVEL_NAME = "適当時/チェリー狙い時"

# けんスロの「逆算に使う値について」にある打ち方別の実効分母。
# None は「なし」として払い出しに含めない。
PLAY_LEVEL_DENOMS: dict[str, dict[str, tuple[float | None, float | None, float | None]]] = {
    "マイジャグラー": {
        "random": (51.99, 4608.0, 10186.11),
        "cherry": (34.66, None, None),
    },
    "ネオアイム": {
        "random": (53.426, 4915.20, 10865.179),
        "cherry": (35.617, None, None),
    },
    "アイムジャグラー": {
        "random": (53.43, 4915.20, 10865.18),
        "cherry": (35.62, None, None),
    },
    "ゴーゴージャグラー": {
        "random": (49.80, 4915.20, 10865.18),
        "cherry": (33.20, None, None),
    },
    "ファンキー": {
        "random": (53.43, 4915.20, 10865.18),
        "cherry": (35.62, None, None),
    },
    "ハッピー": {
        "random": (84.818, 1474.56, 3802.813),
        "cherry": (56.55, None, None),
    },
    "ジャグラーガールズ": {
        "random": (49.95, 4915.20, 10865.18),
        "cherry": (33.30, None, None),
    },
    "ミスタージャグラー": {
        "random": (55.855, 5898.24, 1629.777),
        "cherry": (37.236, None, 2173.04),
    },
    "ウルトラミラクル": {
        "random": (52.29, 4608.0, 10186.11),
        "cherry": (34.86, None, None),
    },
}


def setting_grade(denom: float, spec: report.ModelSpec) -> str:
    pairs = [
        (1, spec.grape_denoms[0]),
        (2, spec.grape_denoms[1]),
        (3, spec.grape_denoms[2]),
        (4, spec.grape_denoms[3]),
        (5, spec.grape_denoms[4]),
        (6, spec.grape_denoms[5]),
    ]
    nearest_setting, _ = min(pairs, key=lambda item: abs(denom - item[1]))
    if denom <= spec.grape_denoms[5]:
        return "設定6以上目安"
    if denom > spec.grape_denoms[0]:
        return "設定1未満目安"
    return f"設定{nearest_setting}近辺"


def play_denoms_for(machine: str, level: str) -> tuple[float | None, float | None, float | None]:
    for key, levels in PLAY_LEVEL_DENOMS.items():
        if key in machine:
            return levels[level]
    spec = report.spec_for(machine)
    if level == "random":
        return spec.cherry_denom / (2 / 3), spec.bell_denom / (2 / 9), spec.pierrot_denom / 0.101
    return spec.cherry_denom, None, None


def setting_grade_or_none(denom: float | None, spec: report.ModelSpec) -> str:
    return setting_grade(denom, spec) if denom is not None else "計算不可"


def grape_from_known_payout(games: int, diff: int, known_payout: float) -> float | None:
    replay_count = games / report.REPLAY_DENOM
    input_medals = (games - replay_count) * 3
    grape_count = (diff + input_medals - known_payout) / 8
    if grape_count <= 0:
        return None
    return games / grape_count


def estimate_with_level(games: int, diff: int, bb: int, rb: int, spec: report.ModelSpec, machine: str, level: str) -> float | None:
    cherry_denom, bell_denom, pierrot_denom = play_denoms_for(machine, level)
    known_payout = bb * spec.big_payout + rb * spec.reg_payout
    if cherry_denom:
        known_payout += games / cherry_denom * spec.cherry_payout
    if bell_denom:
        known_payout += games / bell_denom * 14
    if pierrot_denom:
        known_payout += games / pierrot_denom * 10
    return grape_from_known_payout(games, diff, known_payout)


def estimate_grape_by_play_levels(row: dict[str, object]) -> dict[str, object]:
    games, diff, bb, rb = row.get("games"), row.get("diff"), row.get("bb"), row.get("rb")
    if not all(isinstance(x, int) for x in (games, diff, bb, rb)) or games <= 0:
        return {
            "grape_denom": None,
            "grade": "計算不可",
            "grape_denom_random": None,
            "grade_random": "計算不可",
            "grape_denom_cherry": None,
            "grade_cherry": "計算不可",
        }

    machine = str(row["machine"])
    spec = report.spec_for(machine)
    random_denom = estimate_with_level(games, diff, bb, rb, spec, machine, "random")
    cherry_denom = estimate_with_level(games, diff, bb, rb, spec, machine, "cherry")
    return {
        "grape_denom": cherry_denom,
        "grade": setting_grade_or_none(cherry_denom, spec),
        "grape_denom_random": random_denom,
        "grade_random": setting_grade_or_none(random_denom, spec),
        "grape_denom_cherry": cherry_denom,
        "grade_cherry": setting_grade_or_none(cherry_denom, spec),
        "model": spec.display,
        "play_level": PLAY_LEVEL_NAME,
    }


def _date_from_label(label: str, today: date) -> date | None:
    m = re.search(r"(?:(20\d{2})/)?(\d{1,2})/(\d{1,2})\((.)\)", label)
    if not m:
        return None
    year_text, month_text, day_text, weekday = m.groups()
    years = [int(year_text)] if year_text else range(today.year + 1, today.year - 4, -1)
    for year in years:
        try:
            candidate = date(year, int(month_text), int(day_text))
        except ValueError:
            continue
        if candidate > today:
            continue
        if weekday in report.WEEKDAY_INDEX and candidate.weekday() != report.WEEKDAY_INDEX[weekday]:
            continue
        return candidate
    return None


def _candidate(label: str, href: str | None, tag_url: str, today: date) -> dict[str, object] | None:
    if not href:
        return None
    report_url = urljoin(tag_url, href)
    path_id = urlparse(report_url).path.strip("/").split("/")[0]
    if not path_id.isdigit():
        return None
    rep_date = _date_from_label(label, today)
    if not rep_date:
        return None
    return {"date": rep_date, "url": report_url, "id": path_id, "label": label}


def _fetch_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"})
    with urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def _latest_from_wp_api(tag_url: str, today: date) -> dict[str, object] | None:
    parsed = urlparse(tag_url)
    slug = parsed.path.strip("/").split("/")[-1]
    if not slug:
        return None

    tags_url = f"{report.BASE_URL}/wp-json/wp/v2/tags?slug={slug}"
    tags = _fetch_json(tags_url)
    if not isinstance(tags, list) or not tags:
        return None
    tag_id = tags[0].get("id")
    if not tag_id:
        return None

    posts_url = f"{report.BASE_URL}/wp-json/wp/v2/posts?tags={tag_id}&per_page=10&_fields=id,link,title,date"
    posts = _fetch_json(posts_url)
    if not isinstance(posts, list):
        return None

    for post in posts:
        title = html.unescape(str(post.get("title", {}).get("rendered", "")))
        link = str(post.get("link", ""))
        found = _candidate(title, link, tag_url, today)
        if found:
            return found
    return None


def find_latest_report_resilient(source: str, tag_url: str, today: date) -> dict[str, object]:
    try:
        return _original_find_latest_report(source, tag_url, today)
    except RuntimeError:
        pass

    for table in report.parse_tables(source):
        if not table:
            continue
        header = [report.split_link(c)[0] for c in table[0]]
        if not header or header[0] != "日付":
            continue
        for row in table[1:]:
            for cell in row[:1]:
                label, href = report.split_link(cell)
                found = _candidate(label, href, tag_url, today)
                if found:
                    return found

    pattern = re.compile(
        r"<a[^>]+href=[\"']([^\"']*/\d+/?)['\"][^>]*>\s*((?:20\d{2}/)?\d{1,2}/\d{1,2}\([^<]+\)[^<]*)\s*</a>",
        re.IGNORECASE,
    )
    for href, label in pattern.findall(source):
        found = _candidate(html.unescape(label), href, tag_url, today)
        if found:
            return found

    found = _latest_from_wp_api(tag_url, today)
    if found:
        return found

    snippet = " ".join(source[:300].split())
    raise RuntimeError(f"最新掲載日の行が見つかりませんでした: snippet={snippet}")


_original_find_latest_report = report.find_latest_report
report.find_latest_report = find_latest_report_resilient
report.grade_grape = setting_grade
report.estimate_grape = estimate_grape_by_play_levels
report.PLAY_LEVEL_NAME = PLAY_LEVEL_NAME
report.write_outputs = lambda results: write_outputs_with_grade(report, results)
report.main()
