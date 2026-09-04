#!/usr/bin/env python3
"""Score Kaohsiung new-build projects for 完作's first-phase Meta test.

Two scores per project, each with a traceable breakdown:

- delivery_confidence: how likely the project is handing over right now,
  from public 驗屋/交屋 signals in data/signals.csv
- fit: how well the project matches 完作's 新屋模組化設計 service,
  from the project's own attributes in data/projects.csv

Missing inputs never default to a guess; they score 0 and are listed as 未查得.
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Every weight below is a proposed starting point pending human review.

# 交屋信心:最新訊號距今天數
RECENCY_POINTS = [(7, 30), (14, 25), (30, 15), (60, 8)]

# 交屋信心:訊號種類強度(取最強的一則)
SIGNAL_STRENGTH = {
    "交屋": 30,
    "領取鑰匙": 30,
    "搬家": 30,
    "入厝": 30,
    "冷氣進場": 30,
    "系統櫃進場": 30,
    "室內設計開工": 30,
    "建商通知交屋": 25,
    "複驗": 22,
    "團驗": 22,
    "多戶初驗": 18,
    "初驗": 15,
}

CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}

# 交屋信心:30 天內不同訊號數
DISTINCT_SIGNAL_POINTS = [(1, 5), (3, 12)]
DISTINCT_SIGNAL_MAX = 20

# 交屋信心:不同公開來源數
DISTINCT_SOURCE_POINTS = {1: 0, 2: 6}
DISTINCT_SOURCE_MAX = 10

LEFTOVER_UNIT_PENALTY = -15
SHOW_UNIT_PENALTY = -10

RECHECK_AFTER_DAYS = 14

# 模組化適配
FIT_LAYOUTS = {"2房": 30, "2+1房": 30, "3房": 30, "4房": 15}
FIT_PING_RANGE = (18, 40)
FIT_PING_POINTS = 20
FIT_FINISH_LEVEL = {"none": 15, "partial": 5, "full": -20}
FIT_BUYER_PROFILES = {"首購": 15, "小家庭": 15, "換屋": 15}
FIT_NEEDS = {"玄關", "電器櫃", "電視櫃", "衣櫃", "餐邊櫃", "書桌"}
FIT_NEED_POINTS_EACH = 5
FIT_NEED_POINTS_MAX = 20


def parse_date(value):
    if not value:
        return None
    return dt.date.fromisoformat(value.strip())


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def normalize_url(url):
    url = (url or "").strip().lower()
    for prefix in ("https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.rstrip("/").split("?", 1)[0]


def dedupe_signals(signals):
    """Count a public post once, and one event per project/type/date once."""
    seen = set()
    kept = []
    for sig in signals:
        url_key = normalize_url(sig.get("source_url"))
        event_key = (
            sig.get("project_id", "").strip(),
            sig.get("signal_type", "").strip(),
            (sig.get("event_date") or "").strip(),
        )
        key = ("url", url_key) if url_key else ("event", event_key)
        if key in seen or ("event", event_key) in seen:
            continue
        seen.add(key)
        seen.add(("event", event_key))
        kept.append(sig)
    return kept


def _step_points(value, steps, maximum):
    for threshold, points in steps:
        if value <= threshold:
            return points
    return maximum


def delivery_confidence(project_id, signals, today):
    """Return (score, breakdown) from this project's deduplicated signals."""
    own = [s for s in signals if s.get("project_id", "").strip() == project_id]
    breakdown = []
    if not own:
        return 0, [{"item": "公開訊號", "points": 0, "basis": "未查得"}]

    score = 0

    dated = [(parse_date(s.get("event_date")) or parse_date(s.get("post_date")), s) for s in own]
    dated = [(d, s) for d, s in dated if d]
    if dated:
        latest_date, latest = max(dated, key=lambda pair: pair[0])
        age = (today - latest_date).days
        pts = _step_points(age, RECENCY_POINTS, 0)
        score += pts
        breakdown.append({
            "item": "最新訊號距今",
            "points": pts,
            "basis": "%d 天(%s,%s)" % (age, latest.get("signal_type"), latest.get("source_url")),
        })
    else:
        breakdown.append({"item": "最新訊號距今", "points": 0, "basis": "未查得(訊號無日期)"})

    best = None
    for sig in own:
        base = SIGNAL_STRENGTH.get(sig.get("signal_type", "").strip())
        if base is None:
            continue
        weight = CONFIDENCE_WEIGHT.get(sig.get("confidence", "").strip().lower(), 0.4)
        pts = round(base * weight)
        if best is None or pts > best[0]:
            best = (pts, sig, weight)
    if best:
        pts, sig, weight = best
        score += pts
        breakdown.append({
            "item": "最強訊號種類",
            "points": pts,
            "basis": "%s × 信心 %.1f(%s)" % (sig.get("signal_type"), weight, sig.get("source_url")),
        })
    else:
        breakdown.append({"item": "最強訊號種類", "points": 0, "basis": "訊號種類不在已知清單"})

    recent = [
        s for d, s in dated if (today - d).days <= 30
    ]
    distinct_types = {s.get("signal_type", "").strip() for s in recent}
    pts = _step_points(len(distinct_types), DISTINCT_SIGNAL_POINTS, DISTINCT_SIGNAL_MAX) if recent else 0
    score += pts
    breakdown.append({
        "item": "30 天內不同訊號數",
        "points": pts,
        "basis": "%d 種:%s" % (len(distinct_types), "、".join(sorted(distinct_types)) or "無"),
    })

    sources = {s.get("source_name", "").strip() for s in own if s.get("source_name", "").strip()}
    pts = DISTINCT_SOURCE_POINTS.get(len(sources), DISTINCT_SOURCE_MAX if len(sources) >= 3 else 0)
    score += pts
    breakdown.append({"item": "不同公開來源數", "points": pts, "basis": "%d 個" % len(sources)})

    if any(_truthy(s.get("is_leftover_unit")) for s in own):
        score += LEFTOVER_UNIT_PENALTY
        breakdown.append({"item": "可能只是餘屋成交", "points": LEFTOVER_UNIT_PENALTY, "basis": "訊號標記 is_leftover_unit"})
    if any(_truthy(s.get("is_show_unit")) for s in own):
        score += SHOW_UNIT_PENALTY
        breakdown.append({"item": "實品屋／樣品屋", "points": SHOW_UNIT_PENALTY, "basis": "訊號標記 is_show_unit"})

    return max(0, min(100, score)), breakdown


def _truthy(value):
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def fit_score(project):
    """Return (score, breakdown) from the project's own attributes."""
    score = 0
    breakdown = []

    layout = project.get("main_layout", "").strip()
    if layout:
        pts = FIT_LAYOUTS.get(layout, 0)
        score += pts
        breakdown.append({"item": "主力房型", "points": pts, "basis": layout})
    else:
        breakdown.append({"item": "主力房型", "points": 0, "basis": "未查得"})

    lo, hi = project.get("indoor_ping_min", "").strip(), project.get("indoor_ping_max", "").strip()
    if lo and hi:
        lo_f, hi_f = float(lo), float(hi)
        inside = lo_f >= FIT_PING_RANGE[0] and hi_f <= FIT_PING_RANGE[1]
        pts = FIT_PING_POINTS if inside else 0
        score += pts
        breakdown.append({"item": "室內坪數", "points": pts, "basis": "%s–%s 坪" % (lo, hi)})
    else:
        breakdown.append({"item": "室內坪數", "points": 0, "basis": "未查得"})

    finish = project.get("developer_finish_level", "").strip().lower()
    if finish:
        pts = FIT_FINISH_LEVEL.get(finish, 0)
        score += pts
        breakdown.append({"item": "建商裝潢程度", "points": pts, "basis": finish})
    else:
        breakdown.append({"item": "建商裝潢程度", "points": 0, "basis": "未查得"})

    profile = project.get("buyer_profile", "").strip()
    if profile:
        pts = max((v for k, v in FIT_BUYER_PROFILES.items() if k in profile), default=0)
        score += pts
        breakdown.append({"item": "客群", "points": pts, "basis": profile})
    else:
        breakdown.append({"item": "客群", "points": 0, "basis": "未查得"})

    needs = {n.strip() for n in project.get("needs", "").split("|") if n.strip()}
    if needs:
        matched = sorted(needs & FIT_NEEDS)
        pts = min(len(matched) * FIT_NEED_POINTS_EACH, FIT_NEED_POINTS_MAX)
        score += pts
        breakdown.append({"item": "櫃體需求", "points": pts, "basis": "、".join(matched) or "無對應"})
    else:
        breakdown.append({"item": "櫃體需求", "points": 0, "basis": "未查得"})

    return max(0, min(100, score)), breakdown


def recheck_due(project_id, signals, today):
    """True when any signal for the project was last checked too long ago."""
    for sig in signals:
        if sig.get("project_id", "").strip() != project_id:
            continue
        checked = parse_date(sig.get("checked_at"))
        if checked is None or (today - checked).days > RECHECK_AFTER_DAYS:
            return True
    return False


def score_all(projects, signals, today):
    signals = dedupe_signals(signals)
    results = []
    for project in projects:
        pid = project.get("project_id", "").strip()
        if not pid:
            continue
        confidence, confidence_breakdown = delivery_confidence(pid, signals, today)
        fit, fit_breakdown = fit_score(project)
        results.append({
            "project_id": pid,
            "project_name": project.get("project_name", ""),
            "cluster": project.get("cluster", "") or "未分組",
            "delivery_confidence": confidence,
            "delivery_breakdown": confidence_breakdown,
            "fit": fit,
            "fit_breakdown": fit_breakdown,
            "recheck_due": recheck_due(pid, signals, today),
        })
    return sorted(results, key=lambda r: (r["cluster"], -r["delivery_confidence"], -r["fit"]))


def print_report(results):
    if not results:
        print("data/projects.csv 沒有任何建案。所有評分:未查得。")
        return
    for row in results:
        flag = "  [需重新查核]" if row["recheck_due"] else ""
        print("%s｜%s(%s)  交屋信心 %d  適配 %d%s" % (
            row["cluster"], row["project_name"], row["project_id"],
            row["delivery_confidence"], row["fit"], flag,
        ))
        for item in row["delivery_breakdown"]:
            print("    交屋  %+3d  %s:%s" % (item["points"], item["item"], item["basis"]))
        for item in row["fit_breakdown"]:
            print("    適配  %+3d  %s:%s" % (item["points"], item["item"], item["basis"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--today", help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    today = parse_date(args.today) or dt.date.today()
    projects = read_csv(os.path.join(args.data_dir, "projects.csv"))
    signals = read_csv(os.path.join(args.data_dir, "signals.csv"))
    results = score_all(projects, signals, today)

    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
