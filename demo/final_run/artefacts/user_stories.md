# User stories

_Run 20261125-193937-4995e9 · generated 2026-11-25 20:37 · model llama3.2:3b_

> Generated from human-approved requirements.

### US-FR-01: The system shall validate applicant age, identity, and minimum monthly income against the policy.

**As a** user of the system, **I want** the system to validate applicant age, identity, and minimum monthly income against the policy, **so that** it ensures applicant eligibility.

Priority: High · Source: “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] · Approval: approved by auto-approve (non-interactive run) (auto)

- Acceptance: Given The system receives an applicant age, identity, and minimum monthly income information., when The system checks the information against the Northbridge Bank sample policy., then The system indicates whether the applicant is eligible for a loan.
- Acceptance: Given The system receives an invalid or missing information., when The system checks the information against the Northbridge Bank sample policy., then The system displays an error message.

### US-FR-02: The system shall perform credit assessments and provide credit score bands against the policy.

**As a** user of the system, **I want** the system to perform credit assessments and provide credit score bands against the policy, **so that** it ensures accurate credit decision-making.

Priority: High · Source: “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] · Approval: approved by auto-approve (non-interactive run) (auto)

- Acceptance: Given The system receives an applicant credit information., when The system performs a credit assessment against the Northbridge Bank sample policy., then The system provides a credit score band.
- Acceptance: Given The system receives an invalid or missing credit information., when The system performs a credit assessment against the Northbridge Bank sample policy., then The system displays an error message.

### US-FR-03: The system shall provide decisions and communicate with applicants against the policy.

**As a** user of the system, **I want** the system to provide decisions and communicate with applicants against the policy, **so that** it ensures timely and transparent communication.

Priority: High · Source: “## 4. Controls and Audit - Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision. - All decisions, overrides and data changes are lo…” [C3] · Approval: approved by auto-approve (non-interactive run) (auto)

- Acceptance: Given The system receives an applicant decision information., when The system communicates the decision against the Northbridge Bank sample policy., then The system provides the decision to the applicant.
- Acceptance: Given The system receives an invalid or missing decision information., when The system communicates the decision against the Northbridge Bank sample policy., then The system displays an error message.

### US-FR-04: The system shall validate and process loan applications, including credit assessments and decision-making, against the Northbridge Bank retail loan approval policy.

**As a** user of the system, **I want** the system to validate and process loan applications, including credit assessments and decision-making, against the Northbridge Bank retail loan approval policy, **so that** it ensures compliance with regulatory requirements and reduces risk of incorrect decisions.

Priority: High · Source: “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] · Approval: approved by auto-approve (non-interactive run) (auto)

- Acceptance: Given A loan application is submitted with required information, when The system processes the application, then The system provides a valid decision based on the Northbridge Bank retail loan approval policy
- Acceptance: Given A loan application is submitted with missing or incorrect information, when The system processes the application, then The system indicates the reason for rejection or request for additional information

### US-FR-05: The system shall provide secure and auditable storage and retrieval of loan application data, including credit reports and decision records.

**As a** user of the system, **I want** the system to provide secure and auditable storage and retrieval of loan application data, including credit reports and decision records, **so that** it ensures data protection and compliance with regulatory requirements.

Priority: Medium · Source: “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] · Approval: approved by auto-approve (non-interactive run) (auto)

- Acceptance: Given A loan application is submitted and processed by the system, when The system stores the application data, then The data is encrypted in transit and at rest
- Acceptance: Given A loan application is submitted and processed by the system, when The system retrieves the application data, then The data is accessible only to authorized users with the necessary permissions
