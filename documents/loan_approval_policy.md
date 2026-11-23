# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank")

Purpose: defines the business and control rules any loan-origination software must follow. For course testing only.

## 1. Eligibility
- Applicant must be 18 or older and a resident with a verified identity (KYC completed before a decision is made).
- Minimum monthly income: 2,000 (local currency), verified from payslips or bank statements covering the last 3 months.
- Maximum debt-to-income (DTI) ratio: 40%. Applications above 40% are declined or referred to manual review.

## 2. Credit Assessment
- A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed.
- Credit score bands: 750+ auto-approve eligible; 650-749 manual underwriting; below 650 decline.
- Loans above 50,000 always require a human underwriter, whatever the score.
- The scoring model and its thresholds must be versioned; every decision records which version was used.

## 3. Decision and Communication
- Decision target: 90% of auto-decisions within 5 minutes; manual reviews within 2 business days.
- Every decline must give the applicant the main reasons (adverse-action notice) within 30 days.
- Decisions must not use protected attributes (race, religion, gender, marital status, age beyond legal capacity). Fair-lending tests run quarterly.

## 4. Controls and Audit
- Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision.
- All decisions, overrides and data changes are logged with user, timestamp and reason; logs are retained for 7 years and cannot be edited.
- Interest rate and fee rules change several times a year following treasury and regulator updates; changes must be configurable without code releases.

## 5. Security and Data Protection
- Personal and financial data must be encrypted in transit (TLS 1.2+) and at rest (AES-256).
- Role-based access: applicants, loan officers, underwriters, auditors and administrators have separate permissions.
- Personal data is kept only as long as legally required and must be exportable/erasable on a valid customer request.

## 6. Availability
- Online application channel availability: 99.9% monthly. Planned maintenance only between 01:00 and 04:00.
