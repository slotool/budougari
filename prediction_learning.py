import datetime as dt
import json


def init_learning_db(conn):
    conn.executescript(
        """
        create table if not exists prediction_runs (
            id integer primary key autoincrement,
            hall_name text not null,
            target_date text not null,
            target_event text,
            source_latest_date text,
            created_at text not null,
            unique (hall_name, target_date, target_event)
        );

        create table if not exists prediction_picks (
            run_id integer not null,
            rank integer not null,
            unit_no integer not null,
            machine_name text not null,
            score real not null,
            learned_boost real not null default 0,
            reason_tags text not null,
            latest_diff integer,
            latest_game integer,
            actual_report_date text,
            actual_diff integer,
            actual_game integer,
            is_hit integer,
            updated_at text not null,
            primary key (run_id, unit_no),
            foreign key (run_id) references prediction_runs(id)
        );

        create table if not exists learned_weights (
            hall_name text not null,
            tag text not null,
            samples integer not null,
            hit_rate real not null,
            avg_diff real not null,
            score_adjustment real not null,
            updated_at text not null,
            primary key (hall_name, tag)
        );
        """
    )


def _weekday_jp(date_text):
    return "月火水木金土日"[dt.date.fromisoformat(date_text).weekday()]


def reason_tags(row, target_date, target_event):
    tags = [f"event:{target_event}", f"weekday:{_weekday_jp(target_date)}"]
    if row.get("recommended"):
        tags.append("recommended")
    if row.get("is_corner"):
        tags.append("corner")
    if row.get("weekday_boost"):
        tags.append("weekday_rule")
    if row.get("corner_boost"):
        tags.append("corner_rule")
    if row.get("tail_boost"):
        tags.append("predicted_tail")
        tags.append(f"predicted_tail_rank:{row.get('tail_pick_rank')}")
        if row.get("unit_no") is not None:
            tags.append(f"tail:{row['unit_no'] % 10}")
    if row.get("event_avg") is not None:
        tags.append("has_event_history")
        if row["event_avg"] > 0:
            tags.append("event_history_positive")
        if row["event_avg"] >= 500:
            tags.append("event_history_strong")
    if row.get("recent_avg") is not None:
        if row["recent_avg"] < 0:
            tags.append("recent_negative")
        if row["recent_avg"] >= 500:
            tags.append("recent_strong")
    latest_diff = row.get("latest_diff") or 0
    latest_game = row.get("latest_game") or 0
    if latest_diff <= -1000 and latest_game >= 2500:
        tags.append("latest_deep_loss")
    elif latest_diff <= -500 and latest_game >= 2500:
        tags.append("latest_loss")
    if latest_diff >= 2000:
        tags.append("latest_big_win")
    if latest_game < 1500:
        tags.append("latest_low_game")
    if (row.get("positive_rate") or 0) >= 55:
        tags.append("positive_rate_high")
    tags.append(f"machine:{row.get('current_machine', '')}")
    return tags


def update_prediction_outcomes(conn, hall_name):
    init_learning_db(conn)
    rows = conn.execute(
        """
        select pp.rowid as pick_rowid, pr.target_date, pp.unit_no
          from prediction_picks pp
          join prediction_runs pr on pr.id = pp.run_id
         where pr.hall_name = ?
           and pp.actual_report_date is null
        """,
        (hall_name,),
    ).fetchall()
    now = dt.datetime.now().isoformat(timespec="seconds")
    for row in rows:
        actual = conn.execute(
            """
            select mr.report_date, mr.avg_diff, mr.avg_game
              from machine_reports mr
              join daily_reports dr
                on dr.hall_key = mr.hall_key
               and dr.report_date = mr.report_date
             where dr.hall_name = ?
               and mr.report_date = ?
               and mr.category = 'unit'
               and mr.unit_no = ?
             order by mr.avg_game desc
             limit 1
            """,
            (hall_name, row["target_date"], row["unit_no"]),
        ).fetchone()
        if not actual:
            continue
        actual_diff = actual["avg_diff"]
        is_hit = None if actual_diff is None else int(actual_diff >= 500)
        conn.execute(
            """
            update prediction_picks
               set actual_report_date = ?,
                   actual_diff = ?,
                   actual_game = ?,
                   is_hit = ?,
                   updated_at = ?
             where rowid = ?
            """,
            (actual["report_date"], actual_diff, actual["avg_game"], is_hit, now, row["pick_rowid"]),
        )


def recompute_learned_weights(conn, hall_name):
    init_learning_db(conn)
    picks = conn.execute(
        """
        select pp.reason_tags, pp.actual_diff, pp.is_hit
          from prediction_picks pp
          join prediction_runs pr on pr.id = pp.run_id
         where pr.hall_name = ?
           and pp.actual_diff is not null
        """,
        (hall_name,),
    ).fetchall()
    stats = {}
    for pick in picks:
        for tag in json.loads(pick["reason_tags"]):
            item = stats.setdefault(tag, {"samples": 0, "hits": 0, "diff": 0.0})
            item["samples"] += 1
            item["hits"] += pick["is_hit"] or 0
            item["diff"] += pick["actual_diff"] or 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("delete from learned_weights where hall_name = ?", (hall_name,))
    for tag, item in stats.items():
        samples = item["samples"]
        if samples < 3:
            continue
        hit_rate = item["hits"] / samples
        avg_diff = item["diff"] / samples
        adjustment = avg_diff * 0.08 + (hit_rate - 0.5) * 300
        adjustment = max(-400, min(600, adjustment))
        conn.execute(
            """
            insert into learned_weights
            (hall_name, tag, samples, hit_rate, avg_diff, score_adjustment, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (hall_name, tag, samples, hit_rate, avg_diff, adjustment, now),
        )


def apply_learned_weights(conn, hall_name, summaries, target_date, target_event):
    init_learning_db(conn)
    update_prediction_outcomes(conn, hall_name)
    recompute_learned_weights(conn, hall_name)
    weight_rows = conn.execute(
        "select tag, score_adjustment from learned_weights where hall_name = ?",
        (hall_name,),
    ).fetchall()
    weights = {row["tag"]: row["score_adjustment"] for row in weight_rows}
    if not weights:
        for row in summaries:
            row["reason_tags"] = reason_tags(row, target_date, target_event)
        return sorted(summaries, key=lambda row: row["score"], reverse=True), []
    for row in summaries:
        tags = reason_tags(row, target_date, target_event)
        row["reason_tags"] = tags
        boost = sum(weights.get(tag, 0) for tag in tags)
        row["learned_boost"] = boost
        row["score"] += boost
    notes = [
        f"{tag}: {adjustment:+.0f}"
        for tag, adjustment in sorted(weights.items(), key=lambda item: abs(item[1]), reverse=True)[:6]
    ]
    return sorted(summaries, key=lambda row: row["score"], reverse=True), notes


def save_prediction_run(conn, hall_name, target_date, target_event, latest_date, summaries, limit=15):
    init_learning_db(conn)
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        insert into prediction_runs
        (hall_name, target_date, target_event, source_latest_date, created_at)
        values (?, ?, ?, ?, ?)
        on conflict(hall_name, target_date, target_event) do update set
            source_latest_date = excluded.source_latest_date,
            created_at = excluded.created_at
        """,
        (hall_name, target_date, target_event, latest_date, now),
    )
    run_id = conn.execute(
        """
        select id from prediction_runs
         where hall_name = ?
           and target_date = ?
           and target_event = ?
        """,
        (hall_name, target_date, target_event),
    ).fetchone()["id"]
    for rank, row in enumerate(summaries[:limit], 1):
        tags = row.get("reason_tags") or reason_tags(row, target_date, target_event)
        conn.execute(
            """
            insert into prediction_picks
            (run_id, rank, unit_no, machine_name, score, learned_boost, reason_tags,
             latest_diff, latest_game, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(run_id, unit_no) do update set
                rank = excluded.rank,
                machine_name = excluded.machine_name,
                score = excluded.score,
                learned_boost = excluded.learned_boost,
                reason_tags = excluded.reason_tags,
                latest_diff = excluded.latest_diff,
                latest_game = excluded.latest_game,
                updated_at = excluded.updated_at
            """,
            (
                run_id,
                rank,
                row["unit_no"],
                row["current_machine"],
                row["score"],
                row.get("learned_boost") or 0,
                json.dumps(tags, ensure_ascii=False),
                row.get("latest_diff"),
                row.get("latest_game"),
                now,
            ),
        )
    conn.commit()
