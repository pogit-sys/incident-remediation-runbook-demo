# Remediation Runbook

**One command turns an incident into a checklist with owners, deadlines and first drafts.**

This is a working demo of how to automate the incident remediation plan from a fictional scenario. The scenario: an AI payroll feature sent UK and German payroll documents to a new U.S. provider ("NewAI") for two weeks before anyone approved the vendor or told customers.

Run `start`, and the runbook works through the memo's nine-step plan of action, using the memo's numbering, owners and deadlines. It does the mechanical work (opening the locked channel, finding who's affected, switching off the vendor for UK/EU data, drafting emails, starting the clocks) so the team can spend its time on judgment calls.

> Demo with fictional data. Nothing is sent to customers. Slack is mocked unless you add a token.

---

## The plan, automated

| Memo step | Owner | Due | What the runbook does |
|---|---|---|---|
| 1. Create a locked incident channel | Legal | Today | Opens a private Slack channel for the remediation team and pins the privilege banner |
| 2. Confirm what the provider received | Engineering/Ops | First thing today | Reads the processing log: which customers, how many documents, which dates, which data fields |
| 3. Stop the processing | Engineering | Today | Turns the vendor off for all UK and EU data, for every customer. U.S. routing and the rest of the product stay live |
| 4. Size the population | Security + Engineering | 24 hours | Counts people by customer and country, and flags special category fields (church tax, sick pay, union dues) |
| 5. Confirm the transfer mechanism | Product + Legal | 24 hours | Checks the vendor registry for DPF certification or SCCs with the UK Addendum, and shows what's missing |
| 6. Secure, then delete | Product + Legal | Five business days | Lays out the order: confirm what the vendor holds, capture metadata, then deletion and a certificate |
| 7. Respond to the customer | TBD: Senior RM, Legal, security lead or CEO | 24 hours | Drafts the Appendix A email for each affected UK/EU customer. Where the transfer mechanism or contract terms aren't confirmed, the draft says so instead of implying coverage |
| 8. Five-business-day plan | Legal + Engineering + Product | Five business days | Drafts a remediation plan for each customer: root cause (Product, with Legal review), deletion status, new-subprocessor control, and written approval before re-enabling where the contract requires it |
| 9. Privilege and insurers | Legal + Finance | Today | Writes the privileged incident report and flags outside counsel and insurer notice |

It also gives counsel a list of **flags**, short prompts tied to the facts (for example, "No transfer mechanism on file. Possible unlawful transfer, not just a notice miss."). They're prompts for judgment, not legal conclusions.

---

## Run it

```bash
pip install -r requirements.txt

python runbook.py start --vendor NewAI     # open the incident and run the automated steps
python runbook.py status                   # see the checklist
python runbook.py done 7 --note "Sent to both DPOs"   # mark a step done
python runbook.py reset                    # put everything back for another run
```

Everything the runbook produces lands in `incidents/<incident-id>/`:

```
incident_report.md     # privileged, with flags, deadlines and timeline
emails/<customer>.md   # draft customer emails (not sent)
plans/<customer>.md    # draft five-business-day plans
slack_channel.md       # the channel and pinned privilege banner (mock)
state.json             # checklist state
```

## Demo script (about 3 minutes)

1. **"A customer just told us about NewAI."** Run `start`. Walk through the output: two UK/EU customers affected, 395 people, special category fields flagged, no DPA or transfer mechanism on file, a German tax-adviser customer, a U.S. customer who'll expect notice, and the kill switch already applied.
2. **Show the drafts.** Open `emails/thames-payroll-ltd.md`. It's the Appendix A email, with their numbers filled in and the open items stated plainly. Then open `incident_report.md`, which has the privilege header.
3. **Show the clocks.** Run `done 7`. The customer's 72-hour window to regulators now shows on the checklist, because it starts when *we* tell *them*.
4. **Show it's editable.** Open `data/rules.yaml`, change a rule or a deadline, `reset`, and run again.

---

## Tinker with it

All of the logic lives in plain files under `data/`:

| File | What it controls |
|---|---|
| `plan.yaml` | The nine steps, owners and deadlines |
| `rules.yaml` | The flags for counsel and when they fire |
| `subprocessors.yaml` | Vendor registry: DPA, transfer mechanism, regions, training, retention |
| `customers.yaml` | Customer contacts, notice periods, whether approval is required |
| `processing_log.csv` | Fake log of what was sent to the vendor (rebuild with `python make_sample_log.py`) |

Some things to try:

- Set NewAI's `transfer_mechanism: dpf` and the "possible unlawful transfer" flag goes away, and the email says the transfer was covered.
- Change Brightline CPA to 600 people in `make_sample_log.py` and the FTC 500-consumer flag appears.
- Set Thames Payroll's `approval_required: false` and the approval flag drops, and its plan only requires notice before re-enabling.

Run the scenario tests with `python -m unittest discover tests`. They double as a readable record of how the rules are meant to behave.

## Real Slack (optional)

Create a Slack app with the `groups:write`, `chat:write` and `pins:write` scopes, install it, then:

```bash
export SLACK_BOT_TOKEN=xoxb-...
python runbook.py start --vendor NewAI
```

It creates the private channel and pins the privilege banner. Invite people manually.

---

## Preventing the next one

Step 8 calls for a compliance control for new subprocessors, if one doesn't already exist under our SOC 2 and ISO 27001/42001 programs, built into procurement and deployment. The registry in `subprocessors.yaml` is a starting point for that control and for the vendor inventory in the longer-term plan: every vendor that touches customer data, what it receives, where it processes it, and what controls it maintains.
