# Digital Payments Platform - Business Requirements Specification (Sample - fictional "Northbridge Bank")

Version 0.9 (draft). For course testing only. This document is intentionally longer than the prompt limit so that the retrieval (RAG) path is used.

## 1. Introduction

### 1.1 Purpose
This specification describes the business needs for Northbridge Bank's new Digital Payments Platform (DPP). The DPP will replace the legacy batch payment engine and let retail and small-business customers send domestic transfers, instant payments, scheduled and recurring payments, and card-to-account payouts through the mobile app, internet banking and a partner API.

### 1.2 Scope
In scope: payment initiation, validation, fraud screening, sanctions screening, limits, authorisation, execution through the national instant-payment scheme, notifications, reconciliation and reporting. Out of scope: cross-border SWIFT payments (planned for release 2), cash handling, cheque processing and merchant acquiring.

### 1.3 Stakeholders
Retail customers, small-business customers, the Payments Operations team, the Fraud team, Compliance (AML and sanctions), Treasury, Internal Audit, the Customer Support centre, and third-party providers connecting through the partner API.

### 1.4 Background
The legacy engine processes payments in four daily batches. Customers complain that transfers take up to a day, and the fraud team can only review payments after they are sent. Competitors already offer instant payments around the clock. The regulator has also asked the bank to strengthen transaction monitoring after an industry-wide rise in authorised push-payment (APP) scams.

## 2. Payment Initiation

### 2.1 Channels
Customers can initiate payments from the mobile app, internet banking and the partner API. All channels call the same payment service so that rules and limits are applied consistently.

### 2.2 Payment types
The DPP supports: (a) instant domestic payments, settled within 10 seconds, 24 hours a day, 7 days a week; (b) standard next-day transfers; (c) scheduled payments for a future date; (d) recurring payments (weekly, monthly, quarterly); and (e) bulk payments of up to 500 payees for business customers, uploaded as a CSV file.

### 2.3 Payee management
Customers can save up to 200 payees. Before the first payment to a new payee, the system performs a Confirmation of Payee check that compares the payee name with the name held by the receiving bank and shows the result (match, close match or no match) to the customer. A no-match result requires the customer to confirm that they want to continue, and the warning and the customer's choice are recorded.

### 2.4 Validation
Every payment is validated before it is accepted: account number and sort code format, sufficient available balance, account status (not blocked, closed or dormant), payment reference length (maximum 18 characters) and the cut-off time for next-day transfers (17:30). Invalid payments are rejected with a clear message that tells the customer how to fix the problem.

## 3. Limits and Authorisation

### 3.1 Payment limits
Default daily limits: 10,000 for retail customers and 50,000 for business customers. A single instant payment cannot exceed 25,000. Customers may lower their limits at any time in the app; raising a limit requires a call to the support centre and identity re-verification.

### 3.2 Strong customer authentication
Every payment to a new payee, and every payment above 1,000, requires strong customer authentication (SCA) with two independent factors, for example the device-bound app plus biometrics or a one-time passcode. The authentication must be bound to the amount and the payee, so that a code cannot be reused for a different payment.

### 3.3 Dual authorisation for business customers
Business customers can configure dual authorisation: payments above a threshold that the business chooses must be approved by a second authorised user before execution. A user cannot approve a payment that they created.

## 4. Fraud and Financial-Crime Controls

### 4.1 Real-time fraud scoring
Every payment is scored by the fraud engine before execution. The score uses device data, behaviour (typing speed, navigation), payment history, payee risk and known mule-account lists. The scoring decision must be returned within 300 milliseconds so that instant payments still meet the 10-second settlement target.

### 4.2 Actions on high-risk payments
Low-risk payments are executed immediately. Medium-risk payments trigger an in-app scam warning tailored to the payment purpose the customer selected (for example "buying goods", "investment", "paying a tradesperson") and require the customer to confirm. High-risk payments are held for review by the fraud team, who must decide within 4 hours during business hours; the customer is told that the payment is under review but not why.

### 4.3 Sanctions screening
All payments are screened against the bank's sanctions lists and the payee name is screened against watch lists before execution. Potential matches are held and routed to Compliance. The system must never release a payment with an unresolved potential sanctions match. Sanctions list updates must be applied within 1 hour of publication.

### 4.4 Transaction monitoring and reporting
Executed payments are sent to the anti-money-laundering (AML) transaction-monitoring system in near real time (within 5 minutes). Suspicious activity is escalated to the Money Laundering Reporting Officer. The customer must not be informed that a suspicious activity report has been filed.

### 4.5 APP scam reimbursement
When a customer reports an authorised push-payment scam, the case must be logged with all evidence (warnings shown, customer confirmations, fraud score) so that the bank can decide on reimbursement within 5 business days, as required by the regulator's reimbursement rules.

## 5. Execution, Notifications and Reconciliation

### 5.1 Execution
Instant payments are submitted to the national instant-payment scheme and must be confirmed or rejected by the scheme within 10 seconds. If no response arrives, the payment status becomes "pending" and the system checks the status with the scheme automatically every 30 seconds for up to 15 minutes before raising an operations alert. A payment must never be sent twice (idempotency): every request carries a unique identifier and duplicates are rejected.

### 5.2 Notifications
Customers receive a push notification and an in-app message when a payment is sent, received, held for review or rejected. Business customers can also receive notifications by email. Notifications must never include full account numbers.

### 5.3 Reconciliation
At the end of each day the DPP reconciles its payment records with the scheme settlement reports and the core banking ledger. Any mismatch is reported to Payments Operations by 07:00 the next morning.

## 6. Non-Functional Requirements

### 6.1 Availability
The instant-payment service must be available 99.95% of the time, measured monthly, 24x7. Planned maintenance must not interrupt instant payments; releases use rolling or blue-green deployment.

### 6.2 Performance and capacity
The platform must handle a peak of 400 payments per second (month-end salary day) with 95% of instant payments completing end to end in under 5 seconds. It must scale to three times the current volume within three years without redesign.

### 6.3 Security
All data is encrypted in transit (TLS 1.2 or higher) and at rest (AES-256). Card data follows PCI-DSS; full card numbers are never stored by the DPP. Secrets and keys are kept in a hardware security module. Administrative access requires multi-factor authentication and is reviewed quarterly. The partner API uses OAuth 2.0 with mutual TLS.

### 6.4 Audit and record keeping
Every payment, status change, authorisation, warning shown to the customer and staff action is recorded in an immutable audit log with a timestamp, user or system identity and reason. Payment records are retained for 7 years. Auditors need read-only access with search by customer, payment id and date range.

### 6.5 Data protection
Personal data is processed only for payment purposes, is minimised in logs, and must be exportable and erasable on a valid customer request, subject to the legal retention period for payment records.

### 6.6 Resilience
The platform runs in two data centres in active-active mode. If one data centre fails, the other takes over within 2 minutes with no loss of accepted payments (recovery point objective of zero).

## 7. Change Drivers and Delivery Constraints

The payment scheme rulebook is updated twice a year, fraud typologies change monthly, and the regulator issues new scam-prevention guidance several times a year. Fraud rules, warning texts and limits must therefore be configurable by business users without a code release, with changes approved by a second person and fully audited. The bank wants a first release with instant payments and fraud scoring within 9 months, followed by quarterly releases.

## 8. Glossary

- APP scam: authorised push-payment scam, where a customer is tricked into sending money to a fraudster.
- SCA: strong customer authentication with at least two independent factors.
- Confirmation of Payee: a check that the payee name matches the account holder's name.
- Idempotency: the property that repeating the same request does not create a second payment.
- RPO: recovery point objective, the maximum acceptable data loss after a failure.
