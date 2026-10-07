#!/usr/bin/env python3
"""Remediation runbook: runs the memo's nine-step plan of action as a checklist.

  python runbook.py start --vendor NewAI --discovered 2026-10-05T09:00
  python runbook.py status
  python runbook.py done 7 --note "Emails sent to both DPOs"
  python runbook.py reset

Nothing is sent to customers. Slack is mocked unless SLACK_BOT_TOKEN is set.
"""
import argparse
import csv
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing PyYAML. Run: pip install -r requirements.txt")

ROOT = Path(__file__).parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
INCIDENTS = ROOT / "incidents"

FIELD_ORDER = ["name", "work_email", "gross_pay", "net_pay", "church_tax", "sick_pay", "union_dues", "health"]
LOCATION = {"us": "United States", "eu": "EU", "uk": "UK"}
COUNTRY = {"uk": "UK", "de": "Germany", "fr": "France", "us": "U.S.", "ie": "Ireland",
           "nl": "Netherlands", "es": "Spain", "it": "Italy"}
FIELD = {"name": "names", "work_email": "work email addresses", "gross_pay": "gross pay",
         "net_pay": "net pay", "church_tax": "church tax", "sick_pay": "sick pay",
         "union_dues": "union dues", "health": "health information"}

# ---------- terminal formatting ----------
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
def c(text, code): return f"\033[{code}m{text}\033[0m" if USE_COLOR else text
def bold(t): return c(t, "1")
def dim(t): return c(t, "2")
def red(t): return c(t, "31")
def green(t): return c(t, "32")
def yellow(t): return c(t, "33")
def head(t): print("\n" + bold(t)); print(dim("─" * len(t)))


def load(name):
    with open(DATA / name) as f:
        return yaml.safe_load(f)


def fmt_dt(dt):
    return dt.strftime("%a %b %-d, %-I:%M %p")


def add_business_days(start, n):
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def due_at(discovered, due):
    if due.get("today"):
        return discovered.replace(hour=23, minute=59, second=0, microsecond=0)
    if "hours" in due:
        return discovered + timedelta(hours=due["hours"])
    return add_business_days(discovered, due["bd"])


def human_list(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------- facts ----------
def gather_facts(vendor):
    rows = [r for r in csv.DictReader(open(DATA / "processing_log.csv")) if r["vendor"] == vendor]
    if not rows:
        sys.exit(f"No processing found for vendor '{vendor}'.")
    rules = load("rules.yaml")
    eu_uk = set(rules["eu_uk_regions"])
    special = set(rules["special_category_fields"])

    by_customer = defaultdict(lambda: {"people": set(), "docs": set(), "countries": Counter(),
                                       "fields": set(), "first": None, "last": None})
    for r in rows:
        cst = by_customer[r["customer"]]
        if r["person_id"] not in cst["people"]:
            cst["countries"][r["person_country"]] += 1
        cst["people"].add(r["person_id"])
        cst["docs"].add(r["document_id"])
        cst["fields"].update(r["fields"].split(";"))
        ts = r["timestamp"]
        cst["first"] = min(cst["first"] or ts, ts)
        cst["last"] = max(cst["last"] or ts, ts)

    facts = {"vendor": vendor, "customers": {}}
    for name, cst in by_customer.items():
        facts["customers"][name] = {
            "people": len(cst["people"]),
            "documents": len(cst["docs"]),
            "countries": dict(cst["countries"]),
            "fields": sorted(cst["fields"]),
            "first": cst["first"],
            "last": cst["last"],
            "eu_uk": any(k in eu_uk for k in cst["countries"]),
            "special_category": sorted(cst["fields"] & special),
        }
    return facts


def by_country_text(countries):
    return ", ".join(f"{n} in {COUNTRY.get(k, k.upper())}" for k, n in sorted(countries.items(), key=lambda x: -x[1]))


def fields_text(fields):
    ordered = sorted(fields, key=lambda f: FIELD_ORDER.index(f) if f in FIELD_ORDER else 99)
    return human_list(FIELD.get(f, f) for f in ordered)


# ---------- rules ----------
def evaluate_flags(facts, vendor_rec, customers):
    """Each condition is True/False, or a list of the customers that triggered it."""
    rules = load("rules.yaml")["rules"]
    affected_eu = [n for n, f in facts["customers"].items() if f["eu_uk"]]
    us_customers = [n for n, f in facts["customers"].items() if f["countries"].get("us")]
    us_people = sum(f["countries"].get("us", 0) for f in facts["customers"].values())
    conditions = {
        "always": True,
        "affected_eu_uk": bool(affected_eu),
        "special_category_present": any(f["special_category"] for f in facts["customers"].values()),
        "german_tax_adviser_affected": [n for n in affected_eu
                                        if customers.get(n, {}).get("profession") == "tax_adviser"
                                        and facts["customers"][n]["countries"].get("de")],
        "vendor_no_transfer_mechanism": vendor_rec.get("transfer_mechanism", "none") not in ("dpf", "sccs"),
        "vendor_no_dpa": not vendor_rec.get("dpa_signed", False),
        "customer_requires_approval": [n for n in affected_eu if customers.get(n, {}).get("approval_required")],
        "us_customers_affected": us_customers,
        "us_people_500_plus": us_people >= 500,
    }
    flags = []
    for r in rules:
        hit = conditions.get(r["when"])
        if not hit:
            continue
        names = human_list(hit) if isinstance(hit, list) else ""
        flags.append({"id": r["id"], "text": r["flag"].replace("{customers}", names)})
    return flags


# ---------- step automations ----------
def step2_confirm(facts):
    head("Step 2  Confirm what the provider received")
    for name, f in facts["customers"].items():
        tag = yellow("UK/EU") if f["eu_uk"] else dim("U.S. only")
        print(f"  {bold(name)}  [{tag}]")
        print(f"    {f['documents']} documents, {f['first'][:10]} to {f['last'][:10]}")
        print(f"    Fields: {fields_text(f['fields'])}")


def step3_stop(vendor, regions, inc_dir):
    head("Step 3  Stop the processing for UK/EU data (all customers)")
    path = DATA / "feature_flags.yaml"
    flags = yaml.safe_load(open(path))
    changed = []
    for feature, cfg in flags.items():
        v = cfg.get("vendors", {}).get(vendor)
        if not v:
            continue
        for region in regions:
            if v.get(region) is True:
                v[region] = False
                changed.append(f"{feature}: {vendor} for {region.upper()} data  on -> off")
    with open(path, "w") as fh:
        fh.write("# Which vendors each feature may send data to, by region.\n# The runbook's kill switch edits this file. Set back to true to undo.\n\n")
        yaml.safe_dump(flags, fh, sort_keys=False)
    for line in changed or ["already off"]:
        print(f"  {green('✓')} {line}")
    print(dim(f"  U.S. routing left as is. Undo by editing data/feature_flags.yaml."))
    return datetime.now()


def step4_size(facts):
    head("Step 4  Size the population")
    total = Counter()
    for name, f in facts["customers"].items():
        total.update(f["countries"])
        line = f"  {name}: {f['people']} people ({by_country_text(f['countries'])})"
        if f["special_category"]:
            line += "  " + red(f"special category: {fields_text(f['special_category'])}")
        print(line)
    print(bold(f"  Total: {sum(total.values())} people ({by_country_text(total)})"))


def step5_transfer(vendor_rec):
    head("Step 5  Confirm the transfer mechanism")
    tm = vendor_rec.get("transfer_mechanism", "none")
    ok = lambda b: green("✓") if b else red("✗")
    print(f"  {ok(vendor_rec.get('dpa_signed'))} Signed DPA")
    has_tm = tm in ("dpf", "sccs")
    print(f"  {ok(has_tm)} Transfer mechanism (DPF/UK Extension or SCCs/UK Addendum): {tm.upper() if has_tm else 'none on file'}")
    print(f"  {ok(not vendor_rec.get('trains_on_data'))} No training on our data")
    print(f"  {ok(bool(vendor_rec.get('approved_regions')))} Approved regions: {', '.join(vendor_rec.get('approved_regions') or []) or 'none'}")


TRANSFER = {
    "dpf": "the EU-U.S. Data Privacy Framework and its UK Extension",
    "sccs": "Standard Contractual Clauses with the UK Addendum",
}


def transfer_sentence(vendor_rec):
    """Customer-facing. Never implies coverage the registry doesn't show (memo App. A: if open, say so)."""
    tm = vendor_rec.get("transfer_mechanism", "none")
    if tm in TRANSFER:
        return f"The transfer was covered by {TRANSFER[tm]}."
    return ("We are still confirming the transfer mechanism that applied (the EU-U.S. Data Privacy Framework "
            "and its UK Extension, or Standard Contractual Clauses with the UK Addendum), and we will update you "
            "as soon as we have.")


def contract_sentence(vendor, vendor_rec):
    """Customer-facing. Only describes contract terms when a signed DPA is on file."""
    retention = vendor_rec.get("log_retention_days")
    if vendor_rec.get("dpa_signed"):
        terms = "prohibits using your data to train models"
        if retention:
            terms += f" and limits log retention to {retention} days"
        return f"{vendor} works under a contract with us that {terms}."
    return (f"We are confirming in writing with {vendor} that it has not used your data to train models, "
            f"and what it has retained.")


def transfer_safeguards(vendor_rec):
    tm = vendor_rec.get("transfer_mechanism", "none")
    if tm in TRANSFER:
        return f"Covered by {TRANSFER[tm]}."
    return ("Not yet confirmed. [Legal and Product to complete once step 5 closes: DPF and UK Extension "
            "certification, or SCCs with the UK Addendum, or the gap and how we are closing it.]")


def reenable_text(cust):
    if cust.get("approval_required"):
        return ("the feature stays off for UK/EU data until we have given you notice and received your written "
                "approval, as your contract requires.")
    return (f"the feature stays off for UK/EU data until we have given you notice "
            f"({cust.get('notice_days', 30)} days under your contract).")


def step6_delete(vendor):
    head("Step 6  Secure, then delete")
    print(f"  ○ Contact {vendor} and confirm the scope of data it holds")
    print("  ○ Capture the metadata we need to answer customer questions, before anything is deleted")
    print(f"  ○ {vendor} deletes content and logs and certifies deletion in writing")


def step7_emails(facts, vendor_rec, customers, switch_off, discovered, inc_dir):
    head("Step 7  Respond to the customer (drafts only)")
    tpl = (TEMPLATES / "customer_email.md").read_text()
    out = inc_dir / "emails"
    out.mkdir(exist_ok=True)
    for name, f in facts["customers"].items():
        if not f["eu_uk"]:
            continue
        cust = customers.get(name, {})
        text = tpl.format(
            greeting=cust.get("greeting", "[Name]"),
            dpo_name=cust.get("dpo_name", "[Name]"),
            dpo_email=cust.get("dpo_email", "[email]"),
            relationship_manager=cust.get("relationship_manager", "[RM]"),
            first_date=f["first"][:10], last_date=f["last"][:10],
            vendor=facts["vendor"], fields=fields_text(f["fields"]),
            people=f["people"], by_country=by_country_text(f["countries"]),
            vendor_location=LOCATION.get(vendor_rec.get("hosted_in"), "[location]"),
            contract_sentence=contract_sentence(facts["vendor"], vendor_rec),
            transfer_sentence=transfer_sentence(vendor_rec),
            switch_off_time=switch_off.strftime("%-I:%M %p"),
            send_by=fmt_dt(discovered + timedelta(hours=24)),
        )
        p = out / f"{slug(name)}.md"
        p.write_text(text)
        print(f"  {green('✓')} {p.relative_to(ROOT)}")


def step8_plan(facts, vendor_rec, customers, discovered, inc_dir):
    head("Step 8  Five-business-day plan (drafts)")
    tpl = (TEMPLATES / "five_day_plan.md").read_text()
    out = inc_dir / "plans"
    out.mkdir(exist_ok=True)
    for name, f in facts["customers"].items():
        if not f["eu_uk"]:
            continue
        p = out / f"{slug(name)}.md"
        p.write_text(tpl.format(
            customer=name, due=fmt_dt(add_business_days(discovered, 5)),
            first_date=f["first"][:10], last_date=f["last"][:10], vendor=facts["vendor"],
            people=f["people"], by_country=by_country_text(f["countries"]),
            documents=f["documents"], fields=fields_text(f["fields"]),
            transfer_safeguards=transfer_safeguards(vendor_rec),
            reenable=reenable_text(customers.get(name, {})),
        ))
        print(f"  {green('✓')} {p.relative_to(ROOT)}")


def step1_channel(incident_id, facts, inc_dir):
    head("Step 1  Create a locked incident channel")
    channel = f"#{incident_id.lower()}-priv"
    n = sum(1 for f in facts["customers"].values() if f["eu_uk"])
    post_slack(channel, incident_id, facts["vendor"], n, inc_dir)
    print(dim("    Limit access to the remediation team. Keep facts and discussion there, not in DMs or texts."))
    return channel


def vendor_status_text(vendor_rec):
    tm = vendor_rec.get("transfer_mechanism", "none")
    dpa = "signed DPA on file" if vendor_rec.get("dpa_signed") else "no signed DPA on file"
    return f"{dpa}; transfer mechanism: {TRANSFER.get(tm, 'none on file')}"


def step9_privilege(incident_id, channel, facts, vendor_rec, flags, deadlines, discovered, inc_dir):
    head("Step 9  Privilege, outside counsel and insurers")
    customers_affected = [n for n, f in facts["customers"].items() if f["eu_uk"]]
    allf = [f for f in facts["customers"].values() if f["eu_uk"]]
    countries = Counter()
    for f in allf:
        countries.update(f["countries"])
    report = (TEMPLATES / "incident_report.md").read_text().format(
        incident_id=incident_id, vendor=facts["vendor"], discovered=fmt_dt(discovered), channel=channel,
        customers=human_list(customers_affected),
        first_date=min(f["first"] for f in allf)[:10], last_date=max(f["last"] for f in allf)[:10],
        people=sum(f["people"] for f in allf), documents=sum(f["documents"] for f in allf),
        by_country=by_country_text(countries),
        fields=fields_text(sorted(set().union(*[f["fields"] for f in allf]))),
        vendor_status=vendor_status_text(vendor_rec),
        us_line=us_line(facts),
        flags="\n".join(f"- {fl['text']}" for fl in flags),
        deadlines="\n".join(f"- **{d['title']}** ({d['owner']}): {d['due']}" for d in deadlines),
        retention=vendor_rec.get("log_retention_days", "[X]"),
    )
    (inc_dir / "incident_report.md").write_text(report)
    print(f"  {green('✓')} {(inc_dir / 'incident_report.md').relative_to(ROOT)} (privileged)")
    print("  ○ Gut-check the approach with data privacy counsel with a Germany/UK office or local ties")
    print("  ○ Check notice requirements under our cyber and E&O policies")


def us_line(facts):
    us = [(n, f) for n, f in facts["customers"].items() if not f["eu_uk"] and f["countries"].get("us")]
    if not us:
        return ""
    parts = [f"{n} ({f['countries']['us']} people)" for n, f in us]
    return f"- Also U.S.-only data: {human_list(parts)}. See the U.S. flags below.\n"


def post_slack(channel, incident_id, vendor, n_customers, inc_dir):
    banner = (f":lock: *Privileged & Confidential — prepared at the direction of counsel.*\n"
              f"*{incident_id}*: {vendor} processed UK/EU customer data without approval. "
              f"{n_customers} customers affected.\n"
              "Keep all incident facts and discussion here, not in DMs, texts or other channels. Don't forward outside this channel.")
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        (inc_dir / "slack_channel.md").write_text(f"Channel: {channel} (private)\n\nPinned message:\n\n{banner}\n")
        print(f"  {green('✓')} Slack (mock): {channel}, banner saved to {(inc_dir / 'slack_channel.md').relative_to(ROOT)}")
        print(dim("    Set SLACK_BOT_TOKEN to create the channel for real."))
        return

    def call(method, payload):
        req = urllib.request.Request(f"https://slack.com/api/{method}", data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json; charset=utf-8"})
        return json.load(urllib.request.urlopen(req))

    res = call("conversations.create", {"name": channel.lstrip("#"), "is_private": True})
    if not res.get("ok"):
        print(red(f"  Slack error: {res.get('error')}"))
        return
    cid = res["channel"]["id"]
    msg = call("chat.postMessage", {"channel": cid, "text": banner})
    if msg.get("ok"):
        call("pins.add", {"channel": cid, "timestamp": msg["ts"]})
    print(f"  {green('✓')} Slack: created {channel} and pinned the privilege banner")


def slug(s):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-")


# ---------- state ----------
def latest_incident():
    if not INCIDENTS.exists():
        return None
    dirs = sorted(p for p in INCIDENTS.iterdir() if (p / "state.json").exists())
    return dirs[-1] if dirs else None


def print_checklist(state):
    head(f"Checklist  {state['incident_id']}")
    now = datetime.now()
    for s in state["steps"]:
        due = datetime.fromisoformat(s["due"])
        if s.get("done"):
            mark, when = green("✓"), dim(f"done {fmt_dt(datetime.fromisoformat(s['done']))}")
        else:
            mark = red("!") if now > due else "○"
            when = (red if now > due else yellow)(f"due {fmt_dt(due)}")
        print(f"  {mark} {s['id']}. {s['title']:<38} {dim(s['owner']):<44} {when}")
    cust_clock = state.get("customer_clock")
    clock_step = next((s["id"] for s in state["steps"] if s.get("starts_customer_clock")), 7)
    if cust_clock:
        print(f"\n  {bold('Customer’s 72-hour regulator window')} ends {fmt_dt(datetime.fromisoformat(cust_clock))}"
              f" {dim('(started when we notified them)')}")
    else:
        print(dim(f"\n  The customer’s 72-hour regulator window starts when step {clock_step} is marked done."))


# ---------- commands ----------
def cmd_start(args):
    discovered = datetime.fromisoformat(args.discovered) if args.discovered else datetime.now()
    facts = gather_facts(args.vendor)
    vendors = {v["name"]: v for v in load("subprocessors.yaml")}
    customers = {c["name"]: c for c in load("customers.yaml")}
    vendor_rec = vendors.get(args.vendor, {"name": args.vendor, "transfer_mechanism": "none", "dpa_signed": False})
    plan = load("plan.yaml")

    incident_id = f"INC-{discovered:%Y%m%d}-{slug(args.vendor)}"
    inc_dir = INCIDENTS / incident_id
    inc_dir.mkdir(parents=True, exist_ok=True)

    print(bold(f"\n{incident_id}  {args.vendor}  discovered {fmt_dt(discovered)}"))
    flags = evaluate_flags(facts, vendor_rec, customers)

    channel = step1_channel(incident_id, facts, inc_dir)
    step2_confirm(facts)
    switch_off = step3_stop(args.vendor, args.regions.split(","), inc_dir)
    step4_size(facts)
    step5_transfer(vendor_rec)
    step6_delete(args.vendor)
    step7_emails(facts, vendor_rec, customers, switch_off, discovered, inc_dir)
    step8_plan(facts, vendor_rec, customers, discovered, inc_dir)

    steps = [{"id": s["id"], "key": s.get("key"), "title": s["title"], "owner": s["owner"],
              "due": due_at(discovered, s["due"]).isoformat(), "done": None, "notes": [],
              "starts_customer_clock": bool(s.get("starts_customer_clock"))} for s in plan]
    for s in steps:  # the runbook already did these
        if s["key"] == "stop":
            s["done"] = switch_off.isoformat()
            s["notes"].append("Kill switch applied by runbook")
    deadlines = [{"title": s["title"], "owner": s["owner"], "due": fmt_dt(datetime.fromisoformat(s["due"]))} for s in steps]
    step9_privilege(incident_id, channel, facts, vendor_rec, flags, deadlines, discovered, inc_dir)

    head("Flags for counsel")
    for fl in flags:
        print(f"  {yellow('▲')} {fl['text']}")

    state = {"incident_id": incident_id, "vendor": args.vendor, "discovered": discovered.isoformat(),
             "channel": channel, "flags": flags, "steps": steps, "customer_clock": None}
    (inc_dir / "state.json").write_text(json.dumps(state, indent=2))
    print_checklist(state)
    print(dim(f"\n  Everything is in {inc_dir.relative_to(ROOT)}/. Mark steps with: python runbook.py done <step>\n"))


def cmd_status(args):
    d = INCIDENTS / args.incident if args.incident else latest_incident()
    if not d or not (d / "state.json").exists():
        sys.exit("No incident found. Run: python runbook.py start --vendor NewAI")
    print_checklist(json.loads((d / "state.json").read_text()))
    print()


def cmd_done(args):
    d = INCIDENTS / args.incident if args.incident else latest_incident()
    if not d:
        sys.exit("No incident found.")
    state = json.loads((d / "state.json").read_text())
    step = next((s for s in state["steps"] if s["id"] == args.step), None)
    if not step:
        sys.exit(f"No step {args.step}.")
    now = datetime.now()
    step["done"] = now.isoformat()
    if args.note:
        step["notes"].append(args.note)
    if step.get("starts_customer_clock"):
        state["customer_clock"] = (now + timedelta(hours=72)).isoformat()
    (d / "state.json").write_text(json.dumps(state, indent=2))
    print(green(f"✓ Step {args.step} marked done") + (f" — {args.note}" if args.note else ""))
    print_checklist(state)
    print()


def cmd_reset(args):
    import shutil
    shutil.copy(DATA / "feature_flags.reset.yaml", DATA / "feature_flags.yaml")
    shutil.rmtree(INCIDENTS, ignore_errors=True)
    print(green("✓ Feature flags restored and incidents cleared. Ready to demo again."))


def main():
    ap = argparse.ArgumentParser(description="Run the incident remediation plan as a checklist.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="Open an incident and run the automated steps")
    s.add_argument("--vendor", required=True)
    s.add_argument("--discovered", help="When we learned of it, e.g. 2026-10-05T09:00 (default: now)")
    s.add_argument("--regions", default="uk,eu", help="Regions to switch off (default: uk,eu)")
    s.set_defaults(func=cmd_start)
    st = sub.add_parser("status", help="Show the checklist")
    st.add_argument("--incident")
    st.set_defaults(func=cmd_status)
    dn = sub.add_parser("done", help="Mark a step done")
    dn.add_argument("step", type=int)
    dn.add_argument("--note")
    dn.add_argument("--incident")
    dn.set_defaults(func=cmd_done)
    rs = sub.add_parser("reset", help="Restore feature flags and clear incidents (for re-running the demo)")
    rs.set_defaults(func=cmd_reset)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
