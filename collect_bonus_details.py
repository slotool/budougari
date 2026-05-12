import argparse
import csv
import datetime as dt
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import minrepo_collect as collector


def init_db(conn):
    conn.execute(
        """
        create table if not exists unit_bonus_reports (
            report_id text not null,
            hall_key text not null,
            hall_name text not null,
            report_date text not null,
            machine_name text not null,
            unit_no integer not null,
            bb_count integer,
            rb_count integer,
            combined_rate real,
            bb_rate real,
            rb_rate real,
            collected_at text not null,
            primary key (report_id, unit_no)
        )
        """
    )


def parse_rate(value):
    value = collector.clean_text(value)
    if not value or value == "-":
        return None
    if value.startswith("1/"):
        return collector.parse_int(value[2:])
    return collector.parse_int(value)


def extract_cookie(page_html, name):
    match = re.search(rf"\$\.cookie\('{re.escape(name)}',\s*'([^']+)'", page_html)
    return match.group(1) if match else None


def fetch_with_d2(url, d2_cookie=None):
    headers = {"User-Agent": collector.USER_AGENT}
    if d2_cookie:
        headers["Cookie"] = f"_d2={d2_cookie}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def parse_graph_diffs(page_html):
    graph_diffs = {}
    pattern = re.compile(
        r'<a[^>]+[?&]num=(\d+)[^>]*>\s*\d+\s*</a>.*?data:\s*\[(.*?)\]',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(page_html):
        unit_no = collector.parse_int(match.group(1))
        values = [int(value) for value in re.findall(r'-?\d+', match.group(2))]
        if unit_no is not None and values:
            graph_diffs[unit_no] = values[-1]
    return graph_diffs


def header_index(headers):
    normalized = [header.replace(" ", "").replace("　", "") for header in headers]
    result = {}
    aliases = {
        "unit_no": ["台番", "台番号"],
        "avg_diff": ["差枚"],
        "avg_game": ["G数", "ゲーム数"],
        "payout_rate": ["出率"],
        "bb_count": ["BB", "BIG", "BIG回数"],
        "rb_count": ["RB", "REG", "REG回数"],
        "combined_rate": ["合成", "合算"],
        "bb_rate": ["BB率", "BIG確率"],
        "rb_rate": ["RB率", "REG確率"],
    }
    for key, names in aliases.items():
        for name in names:
            if name in normalized:
                result[key] = normalized.index(name)
                break
    return result


def parse_machine_bonus_rows(page_html):
    bonus_rows = []
    for table in collector.parse_tables(page_html):
        rows = table["rows"]
        if len(rows) < 2:
            continue
        headers = [cell["text"] for cell in rows[0]]
        indexes = header_index(headers)
        if not {"unit_no", "bb_count", "rb_count"} <= indexes.keys():
            continue
        for row in rows[1:]:
            if len(row) <= max(indexes.values()) or row[0].get("header"):
                continue
            unit_no = collector.parse_int(row[indexes["unit_no"]]["text"])
            if unit_no is None:
                continue
            avg_game = collector.parse_int(row[indexes["avg_game"]]["text"]) if "avg_game" in indexes else None
            avg_diff = collector.parse_int(row[indexes["avg_diff"]]["text"]) if "avg_diff" in indexes else None
            payout_rate = (
                collector.parse_percent(row[indexes["payout_rate"]]["text"]) if "payout_rate" in indexes else None
            )
            if payout_rate is None and avg_diff is not None and avg_game:
                payout_rate = (avg_game * 3 + avg_diff) / (avg_game * 3) * 100
            bonus_rows.append(
                {
                    "unit_no": unit_no,
                    "avg_diff": avg_diff,
                    "avg_game": avg_game,
                    "payout_rate": payout_rate,
                    "bb_count": collector.parse_int(row[indexes["bb_count"]]["text"]),
                    "rb_count": collector.parse_int(row[indexes["rb_count"]]["text"]),
                    "combined_rate": parse_rate(row[indexes["combined_rate"]]["text"])
                    if "combined_rate" in indexes
                    else None,
                    "bb_rate": parse_rate(row[indexes["bb_rate"]]["text"]) if "bb_rate" in indexes else None,
                    "rb_rate": parse_rate(row[indexes["rb_rate"]]["text"]) if "rb_rate" in indexes else None,
                }
            )
    return bonus_rows


def available_dates(conn, target_date, hall=None):
    params = [target_date.isoformat()]
    hall_filter = ""
    if hall:
        hall_filter = " and dr.hall_name = ?"
        params.append(hall)
    rows = conn.execute(
        f"""
        select dr.hall_name, max(mr.report_date) as report_date
          from machine_reports mr
          join daily_reports dr
            on dr.hall_key = mr.hall_key
           and dr.report_date = mr.report_date
         where mr.category = 'unit'
           and mr.report_date <= ?
           and instr(mr.machine_name, 'ジャグラー') > 0
           {hall_filter}
         group by dr.hall_name
         order by dr.hall_name
        """,
        params,
    ).fetchall()
    return [(row["hall_name"], dt.date.fromisoformat(row["report_date"])) for row in rows]


def target_machines(conn, report_date, hall=None, limit=None, missing_only=True):
    params = [report_date.isoformat()]
    hall_filter = ""
    if hall:
        hall_filter = " and dr.hall_name = ?"
        params.append(hall)
    having_filter = "having bonus_unit_count < unit_count" if missing_only else ""
    sql_limit = " limit ?" if limit else ""
    if limit:
        params.append(limit)
    return conn.execute(
        f"""
        select mr.report_id, mr.hall_key, dr.hall_name, mr.report_date, mr.machine_name,
               count(*) unit_count,
               sum(case when ub.bb_count is not null and ub.rb_count is not null then 1 else 0 end) bonus_unit_count
          from machine_reports mr
          join daily_reports dr
            on dr.hall_key = mr.hall_key
           and dr.report_date = mr.report_date
          left join unit_bonus_reports ub
            on ub.report_id = mr.report_id
           and ub.unit_no = mr.unit_no
         where mr.category = 'unit'
           and mr.report_date = ?
           and instr(mr.machine_name, 'ジャグラー') > 0
           {hall_filter}
         group by mr.report_id, mr.hall_key, dr.hall_name, mr.report_date, mr.machine_name
         {having_filter}
         order by dr.hall_name, mr.machine_name
         {sql_limit}
        """,
        params,
    ).fetchall()


def save_bonus_rows(conn, machine, bonus_rows, collected_at):
    count = 0
    for bonus in bonus_rows:
        conn.execute(
            """
            insert into unit_bonus_reports
            (report_id, hall_key, hall_name, report_date, machine_name, unit_no, bb_count, rb_count, combined_rate, bb_rate, rb_rate, collected_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(report_id, unit_no) do update set
                machine_name=excluded.machine_name,
                bb_count=excluded.bb_count,
                rb_count=excluded.rb_count,
                combined_rate=excluded.combined_rate,
                bb_rate=excluded.bb_rate,
                rb_rate=excluded.rb_rate,
                collected_at=excluded.collected_at
            """,
            (
                machine["report_id"],
                machine["hall_key"],
                machine["hall_name"],
                machine["report_date"],
                machine["machine_name"],
                bonus["unit_no"],
                bonus["bb_count"],
                bonus["rb_count"],
                bonus["combined_rate"],
                bonus["bb_rate"],
                bonus["rb_rate"],
                collected_at,
            ),
        )
        conn.execute(
            """
            update machine_reports
               set avg_diff = ?,
                   avg_game = coalesce(?, avg_game),
                   payout_rate = ?,
                   collected_at = ?
             where report_id = ?
               and category = 'unit'
               and unit_no = ?
            """,
            (
                bonus.get("avg_diff"),
                bonus.get("avg_game"),
                bonus.get("payout_rate"),
                collected_at,
                machine["report_id"],
                bonus["unit_no"],
            ),
        )
        count += 1
    return count


def export_bonus_csv(conn, csv_dir="exports"):
    csv_path = Path(csv_dir)
    csv_path.mkdir(parents=True, exist_ok=True)
    cursor = conn.execute("select * from unit_bonus_reports order by hall_name, report_date, machine_name, unit_no")
    columns = [description[0] for description in cursor.description]
    with (csv_path / "unit_bonus_reports.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(cursor.fetchall())


def collect(target_date, hall=None, limit=None, delay=8.0, missing_only=True, dry_run=False):
    conn = sqlite3.connect("data/minrepo.sqlite")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    targets = available_dates(conn, target_date, hall)
    machine_targets = []
    for hall_name, report_date in targets:
        machines = target_machines(conn, report_date, hall_name, limit, missing_only)
        machine_targets.append((hall_name, report_date, machines))
    if dry_run:
        total = 0
        for hall_name, report_date, machines in machine_targets:
            for machine in machines:
                print(
                    f"{machine['report_date']} {machine['hall_name']} {machine['machine_name']} "
                    f"{machine['bonus_unit_count']}/{machine['unit_count']}"
                )
            total += len(machines)
            print(f"would check {len(machines)} machine pages for {hall_name} {report_date.isoformat()}")
        print(f"would check machine pages={total}")
        conn.close()
        return
    collected_at = dt.datetime.now().isoformat(timespec="seconds")
    count = 0
    checked = 0
    d2_cookie = None
    for hall_name, report_date, machines in machine_targets:
        print(f"checking {hall_name} {report_date.isoformat()} machine pages={len(machines)}")
        for machine in machines:
            url = f"https://min-repo.com/{machine['report_id']}/?kishu={quote(machine['machine_name'])}"
            html = fetch_with_d2(url, d2_cookie)
            if not d2_cookie:
                d2_cookie = extract_cookie(html, "_d2")
                if d2_cookie:
                    time.sleep(delay)
                    html = fetch_with_d2(url, d2_cookie)
            debug_dir = Path("data/raw/machine_pages") / machine["report_date"]
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / f"{machine['report_id']}_{machine['unit_count']}_{machine['machine_name']}.html"
            debug_path.write_text(html, encoding="utf-8")
            checked += 1
            count += save_bonus_rows(conn, machine, parse_machine_bonus_rows(html), collected_at)
            conn.commit()
            time.sleep(delay)
    collector.export_csv(conn, "exports")
    export_bonus_csv(conn, "exports")
    conn.close()
    print(f"checked machine pages={checked}, collected bonus rows={count}")


def main():
    parser = argparse.ArgumentParser(description="Collect BB/RB details from min-repo machine list pages.")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--hall")
    parser.add_argument("--limit", type=int, help="Limit machine-list pages, not unit pages.")
    parser.add_argument("--delay", type=float, default=8.0)
    parser.add_argument("--include-complete", action="store_true", help="Fetch already-complete machine pages too.")
    parser.add_argument("--dry-run", action="store_true", help="Show target machine-list pages without fetching.")
    args = parser.parse_args()
    collect(
        dt.date.fromisoformat(args.date),
        args.hall,
        args.limit,
        args.delay,
        missing_only=not args.include_complete,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
