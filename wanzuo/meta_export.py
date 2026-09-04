#!/usr/bin/env python3
"""Export the audiences and ad-set targeting of a Meta ad account (read-only).

Writes three files into wanzuo/meta/ so the account's real audience setup
can be reviewed and reused without anyone retyping it:

    custom_audiences.json   自訂受眾 / 類似受眾(含規則與規模區間)
    saved_audiences.json    儲存受眾(含完整 targeting)
    adsets.json             每個廣告組的實際 targeting、目標、預算與狀態

    export META_ACCESS_TOKEN=...      # 需要 ads_read
    export META_AD_ACCOUNT_ID=act_1234567890
    python3 wanzuo/meta_export.py
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from set_daily_budget import GraphError, get, get_all  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meta")

CUSTOM_AUDIENCE_FIELDS = ",".join([
    "id", "name", "subtype", "description", "rule", "retention_days",
    "approximate_count_lower_bound", "approximate_count_upper_bound",
    "delivery_status", "operation_status", "time_updated",
])
SAVED_AUDIENCE_FIELDS = ",".join([
    "id", "name", "targeting", "approximate_count", "time_updated",
])
ADSET_FIELDS = ",".join([
    "id", "name", "status", "effective_status", "campaign{id,name,objective}",
    "optimization_goal", "billing_event", "promoted_object",
    "daily_budget", "lifetime_budget", "targeting", "start_time", "end_time",
])


def summarize_targeting(targeting):
    """One-line human summary of a targeting spec, for the console."""
    geo = targeting.get("geo_locations", {})
    parts = []
    for loc in geo.get("custom_locations", []):
        parts.append("pin %.4f,%.4f r=%s%s" % (
            loc.get("latitude", 0), loc.get("longitude", 0),
            loc.get("radius", "?"), loc.get("distance_unit", "km"),
        ))
    for city in geo.get("cities", []):
        parts.append("city %s" % city.get("name", city.get("key")))
    for region in geo.get("regions", []):
        parts.append("region %s" % region.get("name", region.get("key")))
    for country in geo.get("countries", []):
        parts.append("country %s" % country)
    age = "%s-%s" % (targeting.get("age_min", "?"), targeting.get("age_max", "?"))
    interests = [i.get("name") for flex in targeting.get("flexible_spec", [])
                 for i in flex.get("interests", [])]
    custom = [a.get("name", a.get("id")) for a in targeting.get("custom_audiences", [])]
    excluded = [a.get("name", a.get("id")) for a in targeting.get("excluded_custom_audiences", [])]
    return "geo=[%s] age=%s interests=%s custom=%s excluded=%s" % (
        "; ".join(parts) or "none", age, interests or "none", custom or "none", excluded or "none",
    )


def export(account, token, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    info = get(account, token, fields="name,currency,timezone_name")
    print("Ad account %s — %s (%s, %s)\n" % (
        account, info.get("name"), info.get("currency"), info.get("timezone_name")))

    custom = get_all("%s/customaudiences" % account, token, fields=CUSTOM_AUDIENCE_FIELDS)
    saved = get_all("%s/saved_audiences" % account, token, fields=SAVED_AUDIENCE_FIELDS)
    adsets = get_all("%s/adsets" % account, token, fields=ADSET_FIELDS)

    for name, rows in (("custom_audiences", custom), ("saved_audiences", saved), ("adsets", adsets)):
        path = os.path.join(out_dir, name + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        print("wrote %d rows -> %s" % (len(rows), os.path.relpath(path)))

    print("\n自訂受眾 (%d)" % len(custom))
    for row in custom:
        print("  %-14s %-40s %s–%s  %s" % (
            row.get("subtype", ""), row.get("name", ""),
            row.get("approximate_count_lower_bound", "?"),
            row.get("approximate_count_upper_bound", "?"),
            (row.get("delivery_status") or {}).get("description", ""),
        ))

    print("\n儲存受眾 (%d)" % len(saved))
    for row in saved:
        print("  %-40s ~%s  %s" % (
            row.get("name", ""), row.get("approximate_count", "?"),
            summarize_targeting(row.get("targeting", {})),
        ))

    print("\n廣告組 (%d)" % len(adsets))
    for row in adsets:
        campaign = row.get("campaign", {})
        print("  [%s] %s / %s\n      %s | %s | daily=%s\n      %s" % (
            row.get("effective_status", ""), campaign.get("name", ""), row.get("name", ""),
            campaign.get("objective", ""), row.get("optimization_goal", ""),
            row.get("daily_budget", "-"), summarize_targeting(row.get("targeting", {})),
        ))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=os.environ.get("META_AD_ACCOUNT_ID", ""))
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args(argv)

    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("Set META_ACCESS_TOKEN to a token with ads_read.")
    account = args.account
    if not account:
        raise SystemExit("Set META_AD_ACCOUNT_ID or pass --account act_<id>.")
    if not account.startswith("act_"):
        account = "act_" + account

    try:
        export(account, token, args.out_dir)
    except GraphError as exc:
        raise SystemExit("Meta API error: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
