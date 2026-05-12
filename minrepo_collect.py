import argparse
import csv
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "Mozilla/5.0"


def clean_text(value, preserve_newlines=False):
    value = html.unescape(value or "")
    if preserve_newlines:
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r" *\n+ *", "\n", value)
    else:
        value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_int(value):
    value = clean_text(value)
    if value in {"", "-"}:
        return None
    value = (
        value.replace(",", "")
        .replace("+", "")
        .replace("−", "-")
        .replace("－", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("▲", "-")
        .replace("△", "-")
    )
    value = re.sub(r"^マイナス\s*", "-", value)
    try:
        return int(value)
    except ValueError:
        return None


def parse_percent(value):
    value = clean_text(value).replace("%", "")
    if value in {"", "-"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_win_rate(value):
    value = clean_text(value)
    match = re.match(r"(\d+)\s*/\s*(\d+)", value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tables = []
        self._table_stack = []
        self._current_row = None
        self._current_cell = None
        self._capture_cell = False
        self._link_stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            classes = attrs.get("class", "")
            self._table_stack.append({"class": classes, "rows": []})
        elif tag == "tr" and self._table_stack:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = {"text": [], "links": [], "header": tag == "th"}
            self._capture_cell = True
        elif tag == "a" and self._capture_cell:
            href = attrs.get("href")
            if href:
                self._link_stack.append(href)
        elif tag == "br" and self._capture_cell and self._current_cell is not None:
            self._current_cell["text"].append("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self._link_stack:
            self._link_stack.pop()
        elif tag in {"td", "th"} and self._current_cell is not None:
            self._current_cell["text"] = clean_text("".join(self._current_cell["text"]).replace("\n ", "\n"), True)
            self._current_row.append(self._current_cell)
            self._current_cell = None
            self._capture_cell = False
        elif tag == "tr" and self._current_row is not None:
            if self._table_stack:
                self._table_stack[-1]["rows"].append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())

    def handle_data(self, data):
        if self._capture_cell and self._current_cell is not None:
            self._current_cell["text"].append(data)
            if self._link_stack:
                href = self._link_stack[-1]
                if not self._current_cell["links"] or self._current_cell["links"][-1] != href:
                    self._current_cell["links"].append(href)


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def parse_tables(page_html):
    parser = TableParser()
    parser.feed(page_html)
    return parser.tables


def infer_report_date(month, day, collected_on):
    year = collected_on.year
    candidate = dt.date(year, month, day)
    if candidate > collected_on:
        candidate = dt.date(year - 1, month, day)
    return candidate


def classify_event(report_date, event_rules):
    if not event_rules:
        return None, None
    day_ones = str(dt.date.fromisoformat(report_date).day % 10)
    rule = event_rules.get(day_ones)
    if not rule:
        return None, None
    return rule.get("type"), rule.get("note")


def parse_daily_table(page_html, base_url, hall_name, collected_on, event_rules=None):
    reports = []
    for table in parse_tables(page_html):
        rows = table["rows"]
        if not rows:
            continue
        headers = [cell["text"] for cell in rows[0]]
        if headers[:5] != ["日付", "総差枚", "平均差枚", "平均G", "機種・末尾"]:
            continue
        for row in rows[1:]:
            if len(row) < 5:
                continue
            date_text = row[0]["text"]
            match = re.search(r"(\d{1,2})/(\d{1,2})\((.)\)", date_text)
            if not match:
                continue
            report_url = urljoin(base_url, row[0]["links"][0]) if row[0]["links"] else None
            report_id = None
            if report_url:
                report_id = urlparse(report_url).path.strip("/").split("/")[0]
            report_date = infer_report_date(int(match.group(1)), int(match.group(2)), collected_on)
            event_type, event_note = classify_event(report_date.isoformat(), event_rules or {})
            featured = [line.strip() for line in row[4]["text"].splitlines() if line.strip()]
            reports.append(
                {
                    "hall_name": hall_name,
                    "report_date": report_date.isoformat(),
                    "weekday": match.group(3),
                    "report_url": report_url,
                    "report_id": report_id,
                    "total_diff": parse_int(row[1]["text"]),
                    "avg_diff": parse_int(row[2]["text"]),
                    "avg_game": parse_int(row[3]["text"]),
                    "featured": "\n".join(featured),
                    "event_type": event_type,
                    "event_note": event_note,
                }
            )
    return reports


def parse_detail_page(page_html, report, row_category="variety"):
    records = []
    summary = {}
    for table in parse_tables(page_html):
        rows = table["rows"]
        if not rows:
            continue
        if table["class"] == "sou":
            for row in rows:
                if len(row) >= 2:
                    key = row[0]["text"]
                    value = row[1]["text"]
                    if key == "状況":
                        summary["status"] = value
                    elif key == "勝率":
                        win, total = parse_win_rate(value)
                        summary["win_count"] = win
                        summary["machine_count"] = total
            continue

        headers = [cell["text"] for cell in rows[0]]
        if headers == ["機種", "平均差枚", "平均G数", "勝率", "出率"]:
            for row in rows[1:]:
                if len(row) < 5 or row[0]["header"]:
                    continue
                win, total = parse_win_rate(row[3]["text"])
                records.append(
                    {
                        "category": "machine",
                        "machine_name": row[0]["text"],
                        "unit_no": None,
                        "avg_diff": parse_int(row[1]["text"]),
                        "avg_game": parse_int(row[2]["text"]),
                        "win_count": win,
                        "total_count": total,
                        "payout_rate": parse_percent(row[4]["text"]),
                        "count_hint": parse_int(row[0].get("data-count")),
                    }
                )
        elif headers == ["機種", "台番", "差枚", "G数", "出率"]:
            for row in rows[1:]:
                if len(row) < 5 or row[0]["header"]:
                    continue
                records.append(
                    {
                        "category": row_category,
                        "machine_name": row[0]["text"],
                        "unit_no": parse_int(row[1]["text"]),
                        "avg_diff": parse_int(row[2]["text"]),
                        "avg_game": parse_int(row[3]["text"]),
                        "win_count": None,
                        "total_count": 1,
                        "payout_rate": parse_percent(row[4]["text"]),
                        "count_hint": 1,
                    }
                )
    return summary, records


def init_db(conn):
    conn.executescript(
        """
        create table if not exists daily_reports (
            hall_key text not null,
            hall_name text not null,
            report_date text not null,
            weekday text,
            report_url text,
            report_id text,
            event_type text,
            event_note text,
            total_diff integer,
            avg_diff integer,
            avg_game integer,
            featured text,
            collected_at text not null,
            raw_path text,
            primary key (hall_key, report_date)
        );

        create table if not exists detail_summaries (
            report_id text primary key,
            hall_key text not null,
            report_date text not null,
            status text,
            win_count integer,
            machine_count integer,
            collected_at text not null,
            raw_path text
        );

        create table if not exists machine_reports (
            report_id text not null,
            hall_key text not null,
            report_date text not null,
            category text not null,
            machine_name text not null,
            unit_no integer,
            unit_key text not null,
            avg_diff integer,
            avg_game integer,
            win_count integer,
            total_count integer,
            payout_rate real,
            count_hint integer,
            collected_at text not null,
            primary key (report_id, category, machine_name, unit_key)
        );

        create table if not exists crawl_logs (
            id integer primary key autoincrement,
            url text not null,
            target_name text,
            status text not null,
            message text,
            collected_at text not null
        );
        """
    )
    ensure_column(conn, "daily_reports", "event_type", "text")
    ensure_column(conn, "daily_reports", "event_note", "text")


def ensure_column(conn, table, column, definition):
    columns = {row[1] for row in conn.execute(f"pragma table_info({table})")}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def hall_key(name, url):
    parsed = urlparse(url)
    slug = parsed.path.strip("/").split("/")[-1]
    return slug or hashlib.sha1(f"{name}:{url}".encode("utf-8")).hexdigest()[:12]


def save_raw(raw_dir, collected_on, hall, label, page_html):
    directory = Path(raw_dir) / collected_on.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", hall)
    path = directory / f"{safe}_{label}.html"
    path.write_text(page_html, encoding="utf-8")
    return str(path)


def upsert_daily(conn, hall_id, report, collected_at, raw_path):
    conn.execute(
        """
        insert into daily_reports
        (hall_key, hall_name, report_date, weekday, report_url, report_id, event_type, event_note, total_diff, avg_diff, avg_game, featured, collected_at, raw_path)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(hall_key, report_date) do update set
            hall_name=excluded.hall_name,
            weekday=excluded.weekday,
            report_url=excluded.report_url,
            report_id=excluded.report_id,
            event_type=excluded.event_type,
            event_note=excluded.event_note,
            total_diff=excluded.total_diff,
            avg_diff=excluded.avg_diff,
            avg_game=excluded.avg_game,
            featured=excluded.featured,
            collected_at=excluded.collected_at,
            raw_path=excluded.raw_path
        """,
        (
            hall_id,
            report["hall_name"],
            report["report_date"],
            report["weekday"],
            report["report_url"],
            report["report_id"],
            report["event_type"],
            report["event_note"],
            report["total_diff"],
            report["avg_diff"],
            report["avg_game"],
            report["featured"],
            collected_at,
            raw_path,
        ),
    )


def save_detail(conn, hall_id, report, summary, records, collected_at, raw_path):
    if summary:
        conn.execute(
            """
            insert into detail_summaries
            (report_id, hall_key, report_date, status, win_count, machine_count, collected_at, raw_path)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(report_id) do update set
                status=excluded.status,
                win_count=excluded.win_count,
                machine_count=excluded.machine_count,
                collected_at=excluded.collected_at,
                raw_path=excluded.raw_path
            """,
            (
                report["report_id"],
                hall_id,
                report["report_date"],
                summary.get("status"),
                summary.get("win_count"),
                summary.get("machine_count"),
                collected_at,
                raw_path,
            ),
        )
    for item in records:
        conn.execute(
            """
            insert into machine_reports
            (report_id, hall_key, report_date, category, machine_name, unit_no, unit_key, avg_diff, avg_game, win_count, total_count, payout_rate, count_hint, collected_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(report_id, category, machine_name, unit_key) do update set
                avg_diff=excluded.avg_diff,
                avg_game=excluded.avg_game,
                win_count=excluded.win_count,
                total_count=excluded.total_count,
                payout_rate=excluded.payout_rate,
                count_hint=excluded.count_hint,
                collected_at=excluded.collected_at
            """,
            (
                report["report_id"],
                hall_id,
                report["report_date"],
                item["category"],
                item["machine_name"],
                item["unit_no"],
                str(item["unit_no"]) if item["unit_no"] is not None else "-",
                item["avg_diff"],
                item["avg_game"],
                item["win_count"],
                item["total_count"],
                item["payout_rate"],
                item["count_hint"],
                collected_at,
            ),
        )


def export_csv(conn, csv_dir):
    directory = Path(csv_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for table in ["daily_reports", "detail_summaries", "machine_reports"]:
        rows = conn.execute(f"select * from {table}").fetchall()
        columns = [desc[0] for desc in conn.execute(f"select * from {table} limit 1").description]
        with (directory / f"{table}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)


def log(conn, url, target_name, status, message, collected_at):
    conn.execute(
        "insert into crawl_logs (url, target_name, status, message, collected_at) values (?, ?, ?, ?, ?)",
        (url, target_name, status, message, collected_at),
    )


def collect(config, with_details=True):
    collected_on = dt.date.today()
    collected_at = dt.datetime.now().isoformat(timespec="seconds")
    db_path = Path(config["database"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)

    total_daily = 0
    total_details = 0
    for target in config["targets"]:
        name = target["name"]
        url = target["url"]
        hall_id = hall_key(name, url)
        try:
            page_html = fetch(url)
            raw_path = save_raw(config["raw_dir"], collected_on, hall_id, "list", page_html)
            reports = parse_daily_table(page_html, url, name, collected_on, target.get("event_rules"))
            for report in reports:
                upsert_daily(conn, hall_id, report, collected_at, raw_path)
            total_daily += len(reports)
            log(conn, url, name, "ok", f"daily reports: {len(reports)}", collected_at)
            conn.commit()

            if with_details:
                detail_reports = [r for r in reports if r["report_url"] and r["report_id"]]
                for report in detail_reports[: int(config.get("detail_pages_per_target", 3))]:
                    time.sleep(float(config.get("request_delay_seconds", 1.0)))
                    detail_html = fetch(report["report_url"])
                    detail_raw_path = save_raw(config["raw_dir"], collected_on, hall_id, report["report_id"], detail_html)
                    summary, records = parse_detail_page(detail_html, report)
                    save_detail(conn, hall_id, report, summary, records, collected_at, detail_raw_path)

                    all_url = report["report_url"].rstrip("/") + "/?kishu=all&sort=num"
                    time.sleep(float(config.get("request_delay_seconds", 1.0)))
                    all_html = fetch(all_url)
                    all_raw_path = save_raw(config["raw_dir"], collected_on, hall_id, f"{report['report_id']}_all", all_html)
                    _, unit_records = parse_detail_page(all_html, report, row_category="unit")
                    save_detail(conn, hall_id, report, {}, unit_records, collected_at, all_raw_path)

                    total_details += 1
                    conn.commit()

            time.sleep(float(config.get("request_delay_seconds", 1.0)))
        except Exception as exc:
            log(conn, url, name, "error", repr(exc), collected_at)
            conn.commit()
            raise

    export_csv(conn, config["csv_dir"])
    conn.close()
    return total_daily, total_details


def main():
    parser = argparse.ArgumentParser(description="Collect min-repo daily reports into SQLite and CSV.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--no-details", action="store_true", help="Collect only the hall daily list pages.")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    daily, details = collect(config, with_details=not args.no_details)
    print(f"saved daily_reports={daily}, detail_pages={details}")


if __name__ == "__main__":
    main()
