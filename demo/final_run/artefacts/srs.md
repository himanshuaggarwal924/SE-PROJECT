# Software Requirements Specification

_Run 20261125-193937-4995e9 · generated 2026-11-25 20:37 · model llama3.2:3b_

> Generated from human-approved requirements.

## 1 Introduction

### 1.1 Purpose

This document specifies the software requirements for: Loan approval module for a retail bank (Northbridge Bank sample policy)

### 1.2 Scope

The system shall validate loan applications against the Northbridge Bank sample policy.

### 1.3 Definitions

- **functional** – requirement category
- **security** – requirement category
- **regulatory** – requirement category
- **data-management** – requirement category
- **audit/reporting** – requirement category
- **operational/maintenance** – requirement category
- **FR / NFR / SEC** – functional / non-functional / accepted suggested security requirement
- **C-n / KB-n** – citation of a source-document excerpt / knowledge-base excerpt

### 1.4 References

- loan_approval_policy.md
- Customer data protection standard (SAMPLE) v1.0 (KB-SEC-001)
- Retail loan credit policy (SAMPLE) v2.0 (KB-POL-LOAN-001)

> Knowledge-base items marked SAMPLE are illustrative, not authoritative.

## 2 Overall description

### 2.1 Product perspective

The system shall validate loan applications against the Northbridge Bank sample policy.

### 2.2 Product functions

- FR-01: The system shall validate applicant age, identity, and minimum monthly income against the policy.
- FR-02: The system shall perform credit assessments and provide credit score bands against the policy.
- FR-03: The system shall provide decisions and communicate with applicants against the policy.
- FR-04: The system shall validate and process loan applications, including credit assessments and decision-making, against the Northbridge Bank retail loan approval policy.
- FR-05: The system shall provide secure and auditable storage and retrieval of loan application data, including credit reports and decision records.

### 2.3 User characteristics

- auditors and administrators

### 2.4 Constraints

- KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control)
- KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority)
- KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption)
- Delivery model: DevSecOps (approved)

### 2.5 Assumptions and dependencies

- FR-03

## 3 Specific requirements

### 3.1 External interface requirements

No interface requirements were identified.

### 3.2 Functional requirements

#### FR-01: The system shall validate applicant age, identity, and minimum monthly income against the policy.

| Attribute | Value |
|---|---|
| Categories | functional, regulatory |
| Priority / risk | High / High |
| Rationale | Ensures applicant eligibility |
| Source | “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] |
| Citations | C1 (loan_approval_policy.md, part 1); KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Applicable rules | KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Dependencies | — |
| Confidence | 0.81 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-FR-01-1: Given The system receives an applicant age, identity, and minimum monthly income information., when The system checks the information against the Northbridge Bank sample policy., then The system indicates whether the applicant is eligible for a loan.
- TC-FR-01-2: Given The system receives an invalid or missing information., when The system checks the information against the Northbridge Bank sample policy., then The system displays an error message.

#### FR-02: The system shall perform credit assessments and provide credit score bands against the policy.

| Attribute | Value |
|---|---|
| Categories | functional, regulatory |
| Priority / risk | High / High |
| Rationale | Ensures accurate credit decision-making |
| Source | “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] |
| Citations | C2 (loan_approval_policy.md, part 2); KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Applicable rules | KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Dependencies | — |
| Confidence | 0.85 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-FR-02-1: Given The system receives an applicant credit information., when The system performs a credit assessment against the Northbridge Bank sample policy., then The system provides a credit score band.
- TC-FR-02-2: Given The system receives an invalid or missing credit information., when The system performs a credit assessment against the Northbridge Bank sample policy., then The system displays an error message.

#### FR-03: The system shall provide decisions and communicate with applicants against the policy.

| Attribute | Value |
|---|---|
| Categories | functional, regulatory |
| Priority / risk | High / High |
| Rationale | Ensures timely and transparent communication |
| Source | “## 4. Controls and Audit - Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision. - All decisions, overrides and data changes are lo…” [C3] |
| Citations | C3 (loan_approval_policy.md, part 3); KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption) |
| Applicable rules | KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption) |
| Dependencies | — |
| Confidence | 0.71 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-FR-03-1: Given The system receives an applicant decision information., when The system communicates the decision against the Northbridge Bank sample policy., then The system provides the decision to the applicant.
- TC-FR-03-2: Given The system receives an invalid or missing decision information., when The system communicates the decision against the Northbridge Bank sample policy., then The system displays an error message.

#### FR-04: The system shall validate and process loan applications, including credit assessments and decision-making, against the Northbridge Bank retail loan approval policy.

| Attribute | Value |
|---|---|
| Categories | functional, regulatory, security |
| Priority / risk | High / High |
| Rationale | Ensures compliance with regulatory requirements and reduces risk of incorrect decisions. |
| Source | “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] |
| Citations | C2 (loan_approval_policy.md, part 2); C3 (loan_approval_policy.md, part 3); KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control); KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Applicable rules | KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control); KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Dependencies | FR-01, FR-02 |
| Confidence | 0.83 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-FR-04-1: Given A loan application is submitted with required information, when The system processes the application, then The system provides a valid decision based on the Northbridge Bank retail loan approval policy
- TC-FR-04-2: Given A loan application is submitted with missing or incorrect information, when The system processes the application, then The system indicates the reason for rejection or request for additional information

#### FR-05: The system shall provide secure and auditable storage and retrieval of loan application data, including credit reports and decision records.

| Attribute | Value |
|---|---|
| Categories | security, data-management, audit/reporting |
| Priority / risk | Medium / Medium |
| Rationale | Ensures data protection and compliance with regulatory requirements. |
| Source | “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] |
| Citations | C1 (loan_approval_policy.md, part 1); C4 (loan_approval_policy.md, part 4); KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption); KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Applicable rules | KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption); KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Dependencies | FR-04 |
| Confidence | 0.78 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-FR-05-1: Given A loan application is submitted and processed by the system, when The system stores the application data, then The data is encrypted in transit and at rest
- TC-FR-05-2: Given A loan application is submitted and processed by the system, when The system retrieves the application data, then The data is accessible only to authorized users with the necessary permissions

### 3.3 Performance requirements

None.

### 3.4 Security and privacy requirements

#### NFR-01: The system shall ensure personal and financial data is encrypted in transit and at rest.

| Attribute | Value |
|---|---|
| Categories | security, data-management |
| Priority / risk | High / High |
| Rationale | Protection of sensitive customer data |
| Source | Functionality description: “Loan approval module for a retail bank (Northbridge Bank sample policy)” |
| Citations | KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption) |
| Applicable rules | KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption) |
| Dependencies | — |
| Confidence | 0.97 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-NFR-01-1: Given The system receives untrusted input data, when The system processes the data, then The data is encrypted in transit and at rest

#### NFR-02: The system shall provide secure access controls and logging for all users.

| Attribute | Value |
|---|---|
| Categories | security, audit/reporting |
| Priority / risk | High / High |
| Rationale | Prevention of unauthorized access and data breaches |
| Source | Functionality description: “Loan approval module for a retail bank (Northbridge Bank sample policy)” |
| Citations | KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Applicable rules | KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Dependencies | — |
| Confidence | 0.90 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-NFR-02-1: Given A user attempts to access sensitive data, when The system checks the user's credentials, then Access is denied to unauthorized users

#### NFR-03: The system shall ensure that all decisions and actions are logged and auditable.

| Attribute | Value |
|---|---|
| Categories | audit/reporting, security |
| Priority / risk | High / High |
| Rationale | Compliance with regulatory requirements and transparency |
| Source | Functionality description: “Loan approval module for a retail bank (Northbridge Bank sample policy)” |
| Citations | KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Applicable rules | KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Dependencies | — |
| Confidence | 0.76 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-NFR-03-1: Given A decision is made by the system, when The system logs the decision, then The decision is recorded and retrievable

### 3.5 Software system attributes (availability, reliability, maintainability, usability)

#### NFR-04: The system shall maintain a comprehensive audit log of all decisions, actions, and data changes.

| Attribute | Value |
|---|---|
| Categories | audit/reporting, operational/maintenance |
| Priority / risk | High / High |
| Rationale | Compliance with regulatory requirements and internal audit standards. |
| Source | auditors and administrators – “## 4. Controls and Audit - Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision. - All decisions, overrides and data changes are lo…” [C3] |
| Citations | C3 (loan_approval_policy.md, part 3); KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Applicable rules | KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Dependencies | FR-03 |
| Confidence | 0.66 |
| Approval | approved by auto-approve (non-interactive run) (auto) |
| Version | 1 |

- TC-NFR-04-1: Given The system has been configured to record all decisions and actions., when Within 2 business days of the decision or action., then The recorded data is available for audit and review.

### 3.6 Regulatory, audit and reporting requirements

None.

### 3.7 Data requirements

None.

## Appendix A – Traceability summary

| Requirement | Source | Citations | Tests |
|---|---|---|---|
| FR-01 | “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] | C1; KB-2 | 2 |
| FR-02 | “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] | C2; KB-3 | 2 |
| FR-03 | “## 4. Controls and Audit - Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision. - All decisions, overrides and data changes are lo…” [C3] | C3; KB-1 | 2 |
| FR-04 | “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] | C2; C3; KB-2; KB-3 | 2 |
| FR-05 | “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] | C1; C4; KB-1; KB-2 | 2 |
| NFR-01 | Functionality description: “Loan approval module for a retail bank (Northbridge Bank sample policy)” | KB-1 | 1 |
| NFR-02 | Functionality description: “Loan approval module for a retail bank (Northbridge Bank sample policy)” | KB-2 | 1 |
| NFR-03 | Functionality description: “Loan approval module for a retail bank (Northbridge Bank sample policy)” | KB-3 | 1 |
| NFR-04 | auditors and administrators – “## 4. Controls and Audit - Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision. - All decisions, overrides and data changes are lo…” [C3] | C3; KB-3 | 1 |

## Appendix B – Development approach

Recommended: DevSecOps; chosen: DevSecOps (approved). Based on 8 of 13 factors - factors without evidence are left out of the score.

DevSecOps ranks first due to its alignment with high security risk, regulatory criticality, and continuous delivery needs. This approach ensures security is integrated into the development pipeline, mitigating the risk of failure consequences. With a high score of 98%, DevSecOps is the top choice for the loan approval module.

- Plan: gates – Policy approval; Joint approval of the SDLC choice (project manager, architect, security, compliance)
- Code and build: gates – Peer review before merge
- Test: gates – none
- Release and deploy: gates – Change approval for high-risk releases
- Operate and monitor: gates – none
