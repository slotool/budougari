import argparse
import sqlite3
import sys


def query(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, params).fetchall()


def main():
    parser = argparse.ArgumentParser(description="Validate collected min-repo data before publishing reports.")
    parser.add_argument("--db", default="data/minrepo.sqlite")
    parser.add_argument("--require-bonus", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    errors = []
    warnings = []

    bad_weekdays = query(
        conn,
        """
        select hall_name, report_date, weekday,
               case strftime('%w', report_date)
                 when '0' then '日'
                 when '1' then '月'
                 when '2' then '火'
                 when '3' then '水'
                 when '4' then '木'
                 when '5' then '金'
                 when '6' then '土'
               end as expected_weekday
          from daily_reports
         where weekday is not null
           and weekday != expected_weekday
        """,
    )
    for row in bad_weekdays:
        errors.append(
            f"weekday mismatch: {row['hall_name']} {row['report_date']} "
            f"stored={row['weekday']} expected={row['expected_weekday']}"
        )

    latest_daily = query(
        conn,
        """
        select hall_name, max(report_date) as report_date
          from daily_reports
         group by hall_name
         order by hall_name
        """,
    )

    for daily in latest_daily:
        hall = daily["hall_name"]
        latest_date = daily["report_date"]
        unit_count = query(
            conn,
            """
            select count(*) as count
              from machine_reports mr
              join daily_reports dr
                on dr.hall_key = mr.hall_key
               and dr.report_date = mr.report_date
             where dr.hall_name = ?
               and mr.report_date = ?
               and mr.category = 'unit'
               and instr(mr.machine_name, 'ジャグラー') > 0
            """,
            (hall, latest_date),
        )[0]["count"]
        if unit_count == 0:
            warnings.append(f"no latest Juggler unit rows: {hall} {latest_date}")
            continue

        missing_diff = query(
            conn,
            """
            select mr.machine_name, mr.unit_no
              from machine_reports mr
              join daily_reports dr
                on dr.hall_key = mr.hall_key
               and dr.report_date = mr.report_date
             where dr.hall_name = ?
               and mr.report_date = ?
               and mr.category = 'unit'
               and instr(mr.machine_name, 'ジャグラー') > 0
               and mr.avg_diff is null
               and mr.payout_rate is null
             order by mr.machine_name, mr.unit_no
            """,
            (hall, latest_date),
        )
        if missing_diff:
            sample = ", ".join(f"{row['machine_name']}#{row['unit_no']}" for row in missing_diff[:8])
            errors.append(f"missing diff/rate on latest Juggler rows: {hall} {latest_date} count={len(missing_diff)} sample={sample}")

        if args.require_bonus:
            missing_bonus = query(
                conn,
                """
                select mr.machine_name, mr.unit_no
                  from machine_reports mr
                  join daily_reports dr
                    on dr.hall_key = mr.hall_key
                   and dr.report_date = mr.report_date
                  left join unit_bonus_reports ub
                    on ub.report_id = mr.report_id
                   and ub.unit_no = mr.unit_no
                 where dr.hall_name = ?
                   and mr.report_date = ?
                   and mr.category = 'unit'
                   and instr(mr.machine_name, 'ジャグラー') > 0
                   and (ub.bb_count is null or ub.rb_count is null)
                 order by mr.machine_name, mr.unit_no
                """,
                (hall, latest_date),
            )
            if missing_bonus:
                sample = ", ".join(f"{row['machine_name']}#{row['unit_no']}" for row in missing_bonus[:8])
                errors.append(f"missing BB/RB on latest Juggler rows: {hall} {latest_date} count={len(missing_bonus)} sample={sample}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("report data validation passed")


if __name__ == "__main__":
    main()
