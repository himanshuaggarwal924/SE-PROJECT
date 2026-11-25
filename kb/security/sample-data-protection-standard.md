---
id: KB-SEC-001
title: Customer data protection standard (SAMPLE)
type: security_standard
source: SAMPLE security standard
jurisdiction: SAMPLE
effective_date: 2026-01-01
version: "1.0"
applicability: [all]
status: active
---

> SAMPLE – illustrative, not authoritative. Replace with your approved information-security standard.

## Encryption
Personal and financial data must be encrypted in transit and at rest using
algorithms approved by the information-security team. Encryption keys must be
managed in a dedicated key-management service with access logging.

## Access control
Access to customer data follows least privilege and role-based access control.
Privileged and remote access requires multi-factor authentication. Access
rights are reviewed periodically and revoked promptly when no longer needed.

## Audit logging
Security-relevant events - logins, privilege changes, access to customer
records and configuration changes - must be logged with user, time and action,
and the logs must be protected against tampering.

## Data minimisation
Systems must collect only the personal data needed for the stated purpose,
mask sensitive identifiers in user interfaces and logs, and delete or
anonymise data when its retention period ends.
