# KYC / AML Customer Onboarding Standard (Sample - fictional "Northbridge Bank")

Purpose: minimum Know-Your-Customer (KYC) and Anti-Money-Laundering (AML) controls for any system that onboards customers or approves credit. For course testing only.

## 1. Customer Identification
- Collect full legal name, date of birth, residential address, nationality and a government ID number.
- Verify identity documents electronically (document authenticity + liveness/selfie check) or in branch.
- Verify address with a document dated within the last 3 months.

## 2. Screening
- Screen every new customer against sanctions lists and Politically Exposed Person (PEP) lists before the account or loan is activated.
- Re-screen the whole customer base whenever the sanctions lists are updated (at least daily).
- Potential matches go to a compliance analyst; the system must never auto-clear a potential sanctions match.

## 3. Risk Rating
- Assign each customer a risk rating (Low / Medium / High) based on country, occupation, product and transaction profile.
- High-risk customers require Enhanced Due Diligence (source of funds and source of wealth) and senior-management approval.
- Periodic review: High risk yearly, Medium every 3 years, Low every 5 years.

## 4. Monitoring and Reporting
- Suspicious activity must be escalated to the Money Laundering Reporting Officer; suspicious activity reports are filed with the regulator within the legal deadline.
- The customer must not be told that a suspicious activity report was filed ("tipping-off" is prohibited).

## 5. Record Keeping
- KYC records, screening results and decisions are kept for at least 5 years after the relationship ends.
- Every KYC decision must be traceable to the evidence, the rules version and the analyst who made it.

## 6. Change Drivers
- Sanctions lists change daily; AML typologies and regulator guidance are updated several times a year, so screening and risk rules must be easy to update and re-test.
