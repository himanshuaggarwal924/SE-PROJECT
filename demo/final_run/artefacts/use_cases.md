# Use-case descriptions

_Run 20261125-193937-4995e9 · generated 2026-11-25 20:37 · model llama3.2:3b_

> Generated from human-approved requirements.

### UC-01: The system shall validate applicant age, identity, and minimum monthly income against the policy.

| Field | Description |
|---|---|
| Requirement | FR-01 |
| Primary actor | user of the system |
| Goal | The system shall validate applicant age, identity, and minimum monthly income against the policy. |
| Preconditions | The system receives an applicant age, identity, and minimum monthly income information.; The system receives an invalid or missing information. |
| Main flow | The system checks the information against the Northbridge Bank sample policy. → The system indicates whether the applicant is eligible for a loan. \| The system checks the information against the Northbridge Bank sample policy. → The system displays an error message. |
| Postconditions | The system indicates whether the applicant is eligible for a loan.; The system displays an error message. |
| Business rules | KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Source | “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] |
| Approval | approved by auto-approve (non-interactive run) (auto) |

### UC-02: The system shall perform credit assessments and provide credit score bands against the policy.

| Field | Description |
|---|---|
| Requirement | FR-02 |
| Primary actor | user of the system |
| Goal | The system shall perform credit assessments and provide credit score bands against the policy. |
| Preconditions | The system receives an applicant credit information.; The system receives an invalid or missing credit information. |
| Main flow | The system performs a credit assessment against the Northbridge Bank sample policy. → The system provides a credit score band. \| The system performs a credit assessment against the Northbridge Bank sample policy. → The system displays an error message. |
| Postconditions | The system provides a credit score band.; The system displays an error message. |
| Business rules | KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Source | “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] |
| Approval | approved by auto-approve (non-interactive run) (auto) |

### UC-03: The system shall provide decisions and communicate with applicants against the policy.

| Field | Description |
|---|---|
| Requirement | FR-03 |
| Primary actor | user of the system |
| Goal | The system shall provide decisions and communicate with applicants against the policy. |
| Preconditions | The system receives an applicant decision information.; The system receives an invalid or missing decision information. |
| Main flow | The system communicates the decision against the Northbridge Bank sample policy. → The system provides the decision to the applicant. \| The system communicates the decision against the Northbridge Bank sample policy. → The system displays an error message. |
| Postconditions | The system provides the decision to the applicant.; The system displays an error message. |
| Business rules | KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption) |
| Source | “## 4. Controls and Audit - Four-eyes principle: an underwriter cannot approve a loan they created or override their own decision. - All decisions, overrides and data changes are lo…” [C3] |
| Approval | approved by auto-approve (non-interactive run) (auto) |

### UC-04: The system shall validate and process loan applications, including credit assessments and decision-making, against the Northbridge Bank retail loan approval policy.

| Field | Description |
|---|---|
| Requirement | FR-04 |
| Primary actor | user of the system |
| Goal | The system shall validate and process loan applications, including credit assessments and decision-making, against the Northbridge Bank retail loan approval policy. |
| Preconditions | A loan application is submitted with required information; A loan application is submitted with missing or incorrect information |
| Main flow | The system processes the application → The system provides a valid decision based on the Northbridge Bank retail loan approval policy \| The system processes the application → The system indicates the reason for rejection or request for additional information |
| Postconditions | The system provides a valid decision based on the Northbridge Bank retail loan approval policy; The system indicates the reason for rejection or request for additional information |
| Business rules | KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control); KB-3 (Retail loan credit policy (SAMPLE) v2.0 – Credit decision authority) |
| Source | “## 2. Credit Assessment - A credit bureau report must be pulled for every application; reports older than 30 days must be refreshed. - Credit score bands: 750+ auto-approve eligibl…” [C2] |
| Approval | approved by auto-approve (non-interactive run) (auto) |

### UC-05: The system shall provide secure and auditable storage and retrieval of loan application data, including credit reports and decision records.

| Field | Description |
|---|---|
| Requirement | FR-05 |
| Primary actor | user of the system |
| Goal | The system shall provide secure and auditable storage and retrieval of loan application data, including credit reports and decision records. |
| Preconditions | A loan application is submitted and processed by the system; A loan application is submitted and processed by the system |
| Main flow | The system stores the application data → The data is encrypted in transit and at rest \| The system retrieves the application data → The data is accessible only to authorized users with the necessary permissions |
| Postconditions | The data is encrypted in transit and at rest; The data is accessible only to authorized users with the necessary permissions |
| Business rules | KB-1 (Customer data protection standard (SAMPLE) v1.0 – Encryption); KB-2 (Customer data protection standard (SAMPLE) v1.0 – Access control) |
| Source | “# Retail Loan Approval Policy (Sample - fictional "Northbridge Bank") Purpose: defines the business and control rules any loan-origination software must follow. For course testing …” [C1] |
| Approval | approved by auto-approve (non-interactive run) (auto) |
