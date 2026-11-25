# Loan – process workflow

> Generated from human-approved requirements.

Every box is a requirement (its ID is in the label); diamonds are decisions with an exception path to human handling; boxes in *Cross-cutting controls* are non-functional requirements linked to the steps they protect.

```mermaid
flowchart TD
    START(["Loan application starts"])
    FR_01{"FR-01: Validate applicant age, identity, and minimum monthly income against…"}
    FR_02["FR-02: Perform credit assessments and provide credit score bands against the…"]
    FR_03["FR-03: Provide decisions and communicate with applicants against the policy"]
    FR_04{"FR-04: Validate and process loan applications, including credit assessments…"}
    FR_05["FR-05: Provide secure and auditable storage and retrieval of loan applicatio…"]
    END(["Loan application complete"])
    EXCEPTION[/"Exception: human review / manual handling"/]
    subgraph Controls["Cross-cutting controls (non-functional requirements)"]
        NFR_01[["NFR-01: Ensure personal and financial data is encrypted in transit…"]]
        NFR_02[["NFR-02: Provide secure access controls and logging for all users"]]
        NFR_03[["NFR-03: Ensure that all decisions and actions are logged and audita…"]]
        NFR_04[["NFR-04: Maintain a comprehensive audit log of all decisions, action…"]]
    end
    START --> FR_01
    FR_01 -->|exception| EXCEPTION
    FR_01 -->|meets rule| FR_02
    FR_02 --> FR_03
    FR_03 --> FR_04
    FR_04 -->|exception| EXCEPTION
    FR_04 -->|meets rule| FR_05
    FR_05 --> END
    EXCEPTION -->|decided| END
    FR_01 -.->|depends on| FR_04
    FR_02 -.->|depends on| FR_04
    FR_04 -.->|depends on| FR_05
    NFR_01 -.- FR_04
    NFR_01 -.- FR_05
    NFR_02 -.- FR_04
    NFR_02 -.- FR_05
    NFR_03 -.- FR_04
    NFR_03 -.- FR_05
    NFR_04 -.- FR_05
    classDef decision fill:#fff4e5,stroke:#d97706
    classDef control fill:#eef2ff,stroke:#4f46e5
    class FR_01,FR_04 decision
    class NFR_01,NFR_02,NFR_03,NFR_04 control
```

| Requirement | Node | Text |
|---|---|---|
| FR-01 | decision | Validate applicant age, identity, and minimum monthly income against… |
| FR-02 | step | Perform credit assessments and provide credit score bands against the… |
| FR-03 | step | Provide decisions and communicate with applicants against the policy |
| FR-04 | decision | Validate and process loan applications, including credit assessments… |
| FR-05 | step | Provide secure and auditable storage and retrieval of loan applicatio… |
| NFR-01 | control | Ensure personal and financial data is encrypted in transit… |
| NFR-02 | control | Provide secure access controls and logging for all users |
| NFR-03 | control | Ensure that all decisions and actions are logged and audita… |
| NFR-04 | control | Maintain a comprehensive audit log of all decisions, action… |
