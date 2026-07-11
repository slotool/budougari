from __future__ import annotations

import latest_grape_report_impl as report


PLAY_LEVEL_NAME = "適当時/チェリー狙い時"

# Effective denominators from Kenslo's play-level assumptions.
# Tuple order: cherry, bell, pierrot. None means excluded from known payout.
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
    pairs = [(i + 1, d) for i, d in enumerate(spec.grape_denoms)]
    nearest_setting, _ = min(pairs, key=lambda item: abs(denom - item[1]))
    if denom <= spec.grape_denoms[5]:
        return "設定6以上目安"
    if denom > spec.grape_denoms[0]:
        return "設定1未満目安"
    return f"設定{nearest_setting}近辺"


def setting_grade_or_none(denom: float | None, spec: report.ModelSpec) -> str:
    return setting_grade(denom, spec) if denom is not None else "計算不可"


def play_denoms_for(machine: str, level: str) -> tuple[float | None, float | None, float | None]:
    for key, levels in PLAY_LEVEL_DENOMS.items():
        if key in machine:
            return levels[level]
    spec = report.spec_for(machine)
    if level == "random":
        return spec.cherry_denom / (2 / 3), spec.bell_denom / (2 / 9), spec.pierrot_denom / 0.101
    return spec.cherry_denom, None, None


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
