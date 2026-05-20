from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

import latest_grape_report_impl as report
from latest_grape_report_overrides import write_outputs_with_grade


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
        r"<a[^>]+href=[\"']([^\"']*/\d+/?)['\"][^>]*>\s*((?:20\d{2}/)?\d{1,2}/\d{1,2}\([^<]+\))\s*</a>",
        re.IGNORECASE,
    )
    for href, label in pattern.findall(source):
        found = _candidate(label, href, tag_url, today)
        if found:
            return found

    raise RuntimeError("最新掲載日の行が見つかりませんでした")


_original_find_latest_report = report.find_latest_report
report.find_latest_report = find_latest_report_resilient
report.grade_grape = setting_grade
report.write_outputs = lambda results: write_outputs_with_grade(report, results)
report.main()
