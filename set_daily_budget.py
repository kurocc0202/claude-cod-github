#!/usr/bin/env python3
"""Set the daily budget of Meta (Facebook) ad campaigns matched by name.

Dry run by default: it prints exactly what it would change and stops.
Pass --apply to actually write the budgets.

    export META_ACCESS_TOKEN=...
    export META_AD_ACCOUNT_ID=act_1234567890

    python3 set_daily_budget.py --name 三井 --name 完作 --budget 1000
    python3 set_daily_budget.py --name 三井 --name 完作 --budget 1000 --apply
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "v21.0"
GRAPH = "https://graph.facebook.com"

# Meta stores budgets in the ad account currency's minor unit (USD -> cents).
# These currencies have no minor unit, so the amount is passed as whole units.
ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "COP", "DJF", "GNF", "HUF", "ISK", "JPY", "KMF", "KRW",
    "MGA", "PYG", "RWF", "TWD", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}


class GraphError(RuntimeError):
    pass


def _request(path, token, params=None, data=None):
    url = "%s/%s/%s" % (GRAPH, API_VERSION, path.lstrip("/"))
    params = dict(params or {})
    params["access_token"] = token

    if data is None:
        url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
    else:
        body = dict(data)
        body.update(params)
        req = urllib.request.Request(
            url, data=urllib.parse.urlencode(body).encode(), method="POST"
        )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            message = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError):
            message = detail
        raise GraphError("%s %s: %s" % (exc.code, path, message)) from None


def get(path, token, **params):
    return _request(path, token, params=params)


def post(path, token, **data):
    return _request(path, token, data=data)


def get_all(path, token, **params):
    """GET an edge, following Meta's cursor pagination."""
    rows = []
    page = _request(path, token, params=dict(params, limit=params.get("limit", 200)))
    while True:
        rows.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")
        if not next_url:
            return rows
        try:
            with urllib.request.urlopen(next_url) as resp:
                page = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise GraphError("paging failed: %s" % exc.read().decode(errors="replace"))


def minor_units(amount, currency):
    """Convert a whole-currency amount to the integer Meta expects."""
    factor = 1 if currency.upper() in ZERO_DECIMAL_CURRENCIES else 100
    scaled = amount * factor
    if abs(scaled - round(scaled)) > 1e-9:
        raise SystemExit("Budget %s %s is not a whole minor unit." % (amount, currency))
    return int(round(scaled))


def format_amount(raw, currency):
    if raw in (None, ""):
        return "-"
    factor = 1 if currency.upper() in ZERO_DECIMAL_CURRENCIES else 100
    value = int(raw) / factor
    return ("%g" % value) + " " + currency


def match_campaigns(campaigns, names):
    """Case-insensitive substring match, preserving the order names were given."""
    matched = []
    seen = set()
    for name in names:
        needle = name.casefold()
        hits = [c for c in campaigns if needle in c.get("name", "").casefold()]
        if not hits:
            raise SystemExit("No campaign name contains %r." % name)
        for hit in hits:
            if hit["id"] not in seen:
                seen.add(hit["id"])
                matched.append(hit)
    return matched


def plan_for_campaign(campaign, token, target):
    """Decide where the budget lives: on the campaign (CBO) or on its ad sets."""
    if campaign.get("lifetime_budget") and int(campaign["lifetime_budget"]) > 0:
        raise SystemExit(
            "Campaign %r uses a lifetime budget; a daily budget cannot be set on it "
            "without first clearing the lifetime budget in Ads Manager."
            % campaign["name"]
        )

    if campaign.get("daily_budget") and int(campaign["daily_budget"]) > 0:
        return [
            {
                "level": "campaign",
                "id": campaign["id"],
                "name": campaign["name"],
                "status": campaign.get("effective_status", ""),
                "current": campaign.get("daily_budget"),
                "target": target,
            }
        ]

    adsets = get_all(
        "%s/adsets" % campaign["id"],
        token,
        fields="id,name,effective_status,daily_budget,lifetime_budget",
    )
    live = [a for a in adsets if a.get("effective_status") != "DELETED"]
    if not live:
        raise SystemExit("Campaign %r has no ad sets to budget." % campaign["name"])

    rows = []
    for adset in live:
        if adset.get("lifetime_budget") and int(adset["lifetime_budget"]) > 0:
            raise SystemExit(
                "Ad set %r (campaign %r) uses a lifetime budget; clear it in Ads "
                "Manager before setting a daily budget."
                % (adset["name"], campaign["name"])
            )
        rows.append(
            {
                "level": "adset",
                "id": adset["id"],
                "name": "%s / %s" % (campaign["name"], adset["name"]),
                "status": adset.get("effective_status", ""),
                "current": adset.get("daily_budget"),
                "target": target,
            }
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        action="append",
        required=True,
        metavar="TEXT",
        help="Campaign name (or any part of it). Repeat for several campaigns.",
    )
    parser.add_argument(
        "--budget",
        type=float,
        required=True,
        help="Daily budget per day, in the ad account currency (e.g. 1000).",
    )
    parser.add_argument(
        "--account",
        default=os.environ.get("META_AD_ACCOUNT_ID", ""),
        help="Ad account id, e.g. act_1234567890 (default: $META_AD_ACCOUNT_ID).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the budgets. Without this the script only prints the plan.",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("Set META_ACCESS_TOKEN to a token with ads_management.")
    account = args.account
    if not account:
        raise SystemExit("Set META_AD_ACCOUNT_ID or pass --account act_<id>.")
    if not account.startswith("act_"):
        account = "act_" + account

    currency = get(account, token, fields="currency")["currency"]
    target = minor_units(args.budget, currency)

    campaigns = get_all(
        "%s/campaigns" % account,
        token,
        fields="id,name,effective_status,daily_budget,lifetime_budget",
    )
    rows = []
    for campaign in match_campaigns(campaigns, args.name):
        rows.extend(plan_for_campaign(campaign, token, target))

    width = max(len(r["name"]) for r in rows)
    print("Ad account %s (%s)\n" % (account, currency))
    for row in rows:
        print(
            "  %-7s %-*s  %-12s %s -> %s"
            % (
                row["level"],
                width,
                row["name"],
                row["status"],
                format_amount(row["current"], currency),
                format_amount(row["target"], currency),
            )
        )

    adset_rows = [r for r in rows if r["level"] == "adset"]
    if len(adset_rows) > 1:
        print(
            "\nNote: %d ad sets get %s each, so the campaigns will spend up to %s per "
            "day in total." % (
                len(adset_rows),
                format_amount(target, currency),
                format_amount(target * len(adset_rows), currency),
            )
        )

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these budgets.")
        return 0

    print()
    for row in rows:
        post(row["id"], token, daily_budget=row["target"])
        print("  updated %s %s" % (row["level"], row["name"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GraphError as exc:
        sys.exit("Meta API error: %s" % exc)
