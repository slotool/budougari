from __future__ import annotations

import html
import json
import re
from datetime import date
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import latest_grape_report_impl as report
from latest_grape_report_overrides import write_outputs_with_grade


PLAY_LEVEL_NAME = "チェリー狙い時相当"


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


def estimate_grape_cherry_aim(row: dict[str, object]) -> dict[str, object]:
    games, diff, bb, rb = row.get("games"), row.get("diff"), row.get("bb"), row.get("rb")
    if not all(isinstance(x, int) for x in (games, diff, bb, rb)) or games <= 0:
        return {"grape_denom": None, "grade": "計算不可"}

    spec = report.spec_for(str(row["machine"]))
    replay_count = games / report.REPLAY_DENOM
    known_payout = bb * spec.big_payout + rb * spec.reg_payout
    known_payout += games / spec.cherry_denom * spec.cherry_payout
    input_medals = (games - replay_count) * 3
    grape_count = (diff + input_medals - known_payout) / 8
    if grape_count <= 0:
        return {"grape_denom": None, "grade": "計算不可"}
    denom = games / grape_count
    return {"grape_denom": denom, "grade": setting_grade(denom, spec), "model": spec.display, "play_level": PLAY_LEVEL_NAME}


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
report.estimate_grape = estimate_grape_cherry_aim
report.PLAY_LEVEL_NAME = PLAY_LEVEL_NAME
report.write_outputs = lambda results: write_outputs_with_grade(report, results)
report.main()
