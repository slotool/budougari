from __future__ import annotations

import latest_grape_report_impl as report


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


report.grade_grape = setting_grade
report.main()
