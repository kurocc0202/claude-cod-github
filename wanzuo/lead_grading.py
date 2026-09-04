#!/usr/bin/env python3
"""Grade a 完作 form submission A / B / C.

The grade decides follow-up priority, not ad delivery. Every grade comes
with the reasons that produced it so the rule can be audited later.

    python3 wanzuo/lead_grading.py leads.csv
"""

import csv
import sys

FORM_FIELDS = [
    "district",              # 1 新屋所在行政區
    "project_name",          # 2 建案名稱
    "house_stage",           # 3 等待驗屋／正在初驗／等待複驗／已完成交屋／已入住
    "layout",                # 4 2房／2+1房／3房／4房以上
    "indoor_ping",           # 5 室內坪數區間
    "start_timing",          # 6 1個月內／1至3個月／3至6個月／尚未確定
    "priority_space",        # 7 玄關／客廳／廚房電器收納／主臥／次臥／全室整體規劃
    "main_concern",          # 8 收納／空間感／動線／材質與風格／施工時間／預算配置
    "has_floor_plan",        # 9 是／否
    "will_share_floor_plan", # 10 是／否
    "name",                  # 11
    "contact",               # 12 電話或 LINE
    "consent",               # 13 是／否
]

DELIVERED_STAGES = {"已完成交屋", "已入住"}
NEAR_DELIVERY_STAGES = {"等待複驗", "正在初驗"}
PRE_DELIVERY_STAGES = {"等待驗屋"}
SERVICE_LAYOUTS = {"2房", "2+1房", "3房"}
SOON = {"1個月內", "1至3個月"}
LATER = {"3至6個月"}
MODULE_SPACES = {"玄關", "客廳", "廚房電器收納", "主臥", "次臥", "全室整體規劃"}


def _yes(value):
    return (value or "").strip() in {"是", "yes", "y", "true", "1"}


def grade(lead):
    """Return (grade, reasons)."""
    reasons = []
    stage = (lead.get("house_stage") or "").strip()
    layout = (lead.get("layout") or "").strip()
    timing = (lead.get("start_timing") or "").strip()
    project = (lead.get("project_name") or "").strip()
    space = (lead.get("priority_space") or "").strip()
    consent = _yes(lead.get("consent"))
    has_plan = _yes(lead.get("has_floor_plan"))
    share_plan = _yes(lead.get("will_share_floor_plan"))

    if not consent:
        return "C", ["明確不願接受後續聯絡"]
    if not project and not stage:
        return "C", ["沒有建案名稱也沒有房屋進度,無法確認是否已購屋"]
    if layout and layout not in SERVICE_LAYOUTS:
        reasons.append("房型 %s 不在主要服務範圍" % layout)

    delivered_or_near = stage in DELIVERED_STAGES or stage in NEAR_DELIVERY_STAGES
    if delivered_or_near:
        reasons.append("房屋進度:%s" % stage)
    if timing in SOON:
        reasons.append("規劃時程:%s" % timing)
    if project:
        reasons.append("建案名稱明確")
    if has_plan:
        reasons.append("已有平面圖")
    if share_plan:
        reasons.append("願意提供平面圖")
    if space in MODULE_SPACES:
        reasons.append("明確空間需求:%s" % space)

    is_a = (
        delivered_or_near
        and timing in SOON
        and layout in SERVICE_LAYOUTS
        and space in MODULE_SPACES
        and (has_plan or share_plan)
    )
    if is_a:
        return "A", reasons

    is_b = (
        layout in SERVICE_LAYOUTS
        and space in MODULE_SPACES
        and (timing in LATER or stage in PRE_DELIVERY_STAGES or (delivered_or_near and timing not in SOON))
        and project
    )
    if is_b:
        reasons.append("尚未進入 1–3 個月內的規劃期,或尚未交屋")
        return "B", reasons

    reasons.append("缺少明確時程、建案、平面圖或空間需求")
    return "C", reasons


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    with open(argv[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        g, reasons = grade(row)
        print("%s  %s  %s" % (g, row.get("project_name") or "(無建案)", ";".join(reasons)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
