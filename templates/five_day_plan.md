**DRAFT — Remediation plan for {customer}**
**Due:** {due}  **Owners:** Legal, Engineering and Product

## 1. What happened

Between {first_date} and {last_date}, our AI payroll feature sent documents to {vendor}, a provider that wasn't yet approved or notified to you.

## 2. Affected data

- {people} people ({by_country})
- {documents} documents
- Fields: {fields}

## 3. Transfer safeguards

{transfer_safeguards}

## 4. Deletion and retention

- [ ] Scope of data {vendor} holds confirmed
- [ ] Metadata captured to answer your questions
- [ ] {vendor} deletes content and logs
- [ ] Deletion certificate received and shared with you

## 5. Root cause

[Product to draft, with Legal review: how {vendor} went live without review or notice, and which control failed. Include whether our SOC 2 and ISO 27001/42001 controls should have flagged this.]

## 6. What we're changing

- **New-subprocessor control:** [If no control already exists under our SOC 2 and ISO 27001/42001 programs] a compliance control for new subprocessors, built into procurement and deployment, so no provider goes live without review and the notice our contracts require.
- **Re-enabling for your data:** {reenable}
- **EU-hosted provider:** [timeline, about four weeks].
