# NMDB Sample Data — Design and User Stories

| Item | Details |
| --- | --- |
| Design task | NEWSC-647 — NMDB Design: Generation/insertion |
| Related task | NEWSC-557 — Test data seeding for NMDB |
| Revision | 2 — simplified implementation strategy |
| Status | Proposed for team review |
| Targets | Development and SI&T staging |

## 1. Problem and Objective

Define the input format for NMDB sample data and a centralized mechanism to insert it into development or staging. Preparing a test environment must not require manually uploading multiple files to different feature endpoints.

The first implementation will provide one Python CLI command inside the existing NMDB backend. It reads a predefined sample dataset and calls feature-specific insertion functions in an explicitly configured order. It reuses the existing PostgreSQL connection setup, SQLAlchemy models, validation schemas and application services.

This revision replaces the earlier generic framework proposal with a smaller implementation. Actual model relationships, unique matching keys and service transaction behavior still require repository verification.

## 2. Design Decisions

| Question | Decision |
| --- | --- |
| What is the input format? | One baseline JSON file with sections for the scoped features; retain XML fixtures for NRD imports where the existing import service requires XML |
| How is insertion centralized? | One CLI command invokes all required feature insertion functions |
| How is dev/stage selected? | An explicit environment argument selects an approved connection profile containing the database and schema |
| How are dependencies handled? | A small explicit prerequisite mapping and verified fixed execution order |
| How are records inserted? | Existing service functions where business rules apply; SQLAlchemy ORM for approved simple records |
| Is a new API needed? | No endpoint in the first version; the CLI satisfies centralized execution |
| How can Jenkins use it? | Invoke the same CLI after the local flow works; no separate insertion implementation |

Centralized execution means one invocation. The runner may internally read JSON and XML files and call multiple service functions; the operator does not upload them separately.

## 3. Input Format

Store the baseline dataset in source control alongside the backend. Start with one `baseline.json`, grouped by feature, plus any NRD XML fixture. Split the JSON into feature files only if its size becomes difficult to maintain; the invocation remains unchanged.

JSON contains curated values, scenario selections, record counts and logical references. Small Python loops generate repetitive values such as track points. Generated inputs must use fixed rules, seeds and time anchors so the same baseline is reproducible. Do not infer valid workflows from database column types alone.

Illustrative seed format, not an existing NMDB API contract:

```json
{
  "dataset": "sit_baseline",
  "features": {
    "nrd": {"xml_file": "nrd_sample.xml"},
    "missions": {
      "records": [{"key": "mission-01", "name": "Sample mission"}]
    },
    "ew_tracks": {"count": 10, "points_per_track": 10},
    "activity_reports": {
      "records": [
        {
          "key": "report-01",
          "mission_ref": "mission-01",
          "track_refs": ["track-01"]
        }
      ]
    }
  }
}
```

The example shows the format only; it is not the complete ten-report dataset and omits real required domain fields. Feature functions map seed values to actual application schemas. Supported enum values and valid state transitions come from the repository. Database IDs and credentials are not stored in the dataset.

For NRD, the runner reads the referenced XML fixture from the packaged dataset and passes it to the existing import service. This preserves the import format and associated log behavior without a separate manual upload.

## 4. Centralized Execution

Proposed commands, to be implemented in the backend:

```bash
python -m app.seeding --environment dev --dataset baseline --features all
python -m app.seeding --environment stage --dataset baseline --features all
python -m app.seeding --environment stage --dataset baseline --features activity_reports
```

The CLI supports a named dataset and either all supported features or an explicit subset. Unknown datasets/features are rejected. Selecting a subset also includes its configured prerequisites and prints the effective feature list.

The command runs in an environment with the backend dependencies and access to the selected database, such as the application container or an approved execution host. FastAPI does not need to serve HTTP requests for the CLI to call service functions directly. Where services depend on user identity or other request context, the insertion function must supply an approved test actor/context explicitly.

## 5. Implementation Components

| Component | Responsibility |
| --- | --- |
| CLI | Read arguments and select the approved dev or stage connection profile |
| Runner | Read inputs, expand declared prerequisites, execute functions in order, manage transactions and print the summary |
| Feature insertion functions | Validate feature inputs, find or create records, apply required business logic and return logical-key-to-ID mappings |
| Sample dataset | Curated JSON inputs and required XML fixtures |

Suggested small structure:

| Path | Contents |
| --- | --- |
| `app/seeding/__main__.py` | CLI arguments |
| `app/seeding/runner.py` | Function registry, prerequisites, execution order and shared session |
| `app/seeding/features/` | One module per feature with insertion functions |
| `app/seeding/data/baseline.json` | Baseline sample data |
| `app/seeding/data/nrd_sample.xml` | NRD fixture where required |

The final placement follows repository conventions. No generic plugin system, automatic model discovery or ORM introspection is required.

## 6. Insertion Workflow

1. Read the environment, dataset and selected features.
2. Resolve the approved database/schema configuration. Reject production or unapproved targets; display the resolved non-secret target.
3. Confirm that required migrations have already run. The seeding command does not create application tables or enums.
4. Load JSON/XML inputs and validate required fields, known states and logical references that can be checked before writes.
5. Include configured prerequisites and run feature functions in the verified order.
6. For each record, check its stable matching key. Reuse a confirmed matching record or insert a new one through the approved service/ORM path.
7. Keep returned IDs in a shared dictionary so dependent features can create their relationships.
8. Check counts, required relationships and database consistency within the transaction, then commit.
9. Print created/skipped counts and the final result. Return a nonzero exit code on failure.

Example relationship flow: a mission function returns the ID for `mission-01`; a track function returns the ID for `track-01`; the activity report function uses both IDs to create `report-01`. This order is illustrative; the full order must be checked against actual models and business rules.

## 7. Repeat Execution and Failure Handling

Use existing unique business keys where suitable. Seed records must have stable identifiers that can be matched safely in both dev and stage. A name prefix alone is not proof of ownership or uniqueness. Reuse unrelated reference records only when explicitly allowed and unambiguously matched.

An unchanged rerun skips/reuses existing sample records, including their dependent records, without duplicating points, links, import logs or workflow history. Existing records that conflict with the requested sample are reported rather than overwritten. The first version does not update or reset scenarios.

If a feature has no safe persistent matching key, establish a minimal feature-specific identity mapping before enabling repeatable loading for that feature. An in-memory ID dictionary resolves references during a run but does not prevent duplicates across runs.

The preferred transaction boundary is one invocation using the existing SQLAlchemy session. Feature functions must not commit independently. On failure, roll back the active transaction and report that attempted inserts were not committed. Existing services that commit internally must be adapted or have an explicitly documented partial-commit/recovery behavior before use; do not claim full rollback for them.

Prevent live external synchronization or notifications from seeded scenarios. External effects cannot be undone by database rollback. API smoke checks and export/XSD checks that require committed data run after commit; failures there are reported as verification failures, not as rolled-back insertion.

## 8. Dev and Stage Configuration

| Control | Required behavior |
| --- | --- |
| Target selection | `dev` and `stage` resolve to explicitly approved host/database/schema combinations |
| Schema | Reuse the application's supported schema configuration; reject missing or mismatched targets without silently falling back to another schema |
| Credentials | Use existing secret/environment configuration; exclude credentials from sample files, commands and logs |
| Target validation | Check the resolved database/schema against approved configuration; an environment label alone is insufficient |
| Migration readiness | Run existing migrations before invoking the seeder |
| Execution | One operator/job at a time per target for the initial version; a later Jenkins wrapper should serialize runs for that target |

Dedicated concurrency infrastructure is deferred. This version is operated sequentially and relies on verified database uniqueness constraints as an additional safeguard.

## 9. Feature Coverage

| Feature | Required baseline coverage |
| --- | --- |
| NRD | Representative imported records and corresponding import logs |
| Update Nominations | Supported states, locks, multiple users and dirty proposals |
| Sensor Status | Supported statuses, platform links and multiple sensors on a platform |
| Mission Management | Supported mission states and threat export scenarios compatible with the applicable XSD |
| Intercept Correlation | Emitter/platform selections, initial configuration and Bruno matching request examples |
| EW Tracks | 10 tracks with approximately 10 points each; varied emitter and sensor associations |
| Activity Reports | 10 reports associated with EW tracks, with most linked to missions; agree the exact distribution with SI&T |
| NEC | Representative synchronization states and logs using controlled test behavior |

Deliver a first working slice using EW Tracks and Activity Reports plus their required prerequisites. Add the remaining feature functions incrementally. This delivery sequence does not remove the eight-feature requirement from the completed scope.

## 10. First-Version Scope and Deferred Work

| Included now | Deferred |
| --- | --- |
| One CLI for dev and stage | New administrative API endpoint |
| Baseline JSON and required XML fixtures | General-purpose dataset/bundle framework |
| Explicit feature functions and dependency order | Automatic model discovery and dependency inference |
| Existing validation, services and ORM | Universal model-driven data generation |
| Stable-key checks and skip/reuse behavior | Generic upsert, update and reset |
| Transaction/error handling and console summary | Full dry-run change preview and rich report artifacts |
| Basic scenario verification | Automated cleanup and generic ownership framework |
| Local/container execution | Jenkins wrapper after the CLI works; automatic post-deployment seeding |

Basic pre-insertion validation is included even though a full dry-run preview is deferred. The CLI and business logic are shared if an API endpoint is added later.

## 11. Acceptance Criteria

- One documented command loads the selected sample dataset into an approved dev or stage target.
- Users do not manually upload feature files to separate endpoints.
- JSON is the primary input format; required NRD XML is consumed by the same invocation.
- Selecting a feature also handles its declared prerequisites in the verified order.
- Inserted data follows actual application constraints and required service workflows.
- Logical references resolve correctly without hardcoded database-generated IDs.
- Repeating an unchanged dataset creates no duplicate sample records or dependent data.
- Invalid inputs, unresolved references and conflicting existing data produce actionable errors.
- Transaction failures follow the documented rollback boundary, and failed commands return a nonzero exit code.
- The resolved target is checked before writes, and production targets are rejected.
- The completed baseline meets the eight-feature coverage above; the first slice demonstrates linked track/report insertion.

## 12. Implementation Work Items and Review

1. **Centralized runner and configuration:** CLI, dev/stage profiles, baseline input parsing, explicit prerequisites/order, shared session and basic summary.
2. **Feature sample-data insertion:** real feature functions, curated scenarios, repeat-run identity checks, linked records and verification. Deliver the first linked slice, then extend to all eight groups.
3. **Optional follow-up — Jenkins:** parameterize the working CLI, supply environment credentials, serialize target runs and retain console output.

Before implementation, confirm the existing NRD import path, the approved dev/stage targets, per-feature matching keys, actual prerequisites and service commit behavior. Nominate dataset maintainers and review the baseline scenarios with SI&T. Record team agreement in a short design review.

The implementation decision is a single backend CLI reading JSON/XML fixtures and invoking feature-specific insertion functions through existing application logic.

## 13. User Stories

### US 1 — Implement Centralized Sample-Data Insertion for Dev and Staging

**User story:** As an NMDB developer or tester, I want to load sample data through one CLI command so that I can prepare dev or staging without manually uploading files to multiple endpoints.

**Acceptance criteria:**

- The command accepts the environment (`dev` or `stage`), dataset and selected features.
- Sample inputs are read from JSON, with NRD XML supported where required.
- Selected features and their prerequisites run in an explicitly defined order.
- The command uses the existing database configuration and SQLAlchemy session.
- Unapproved or production targets are rejected before insertion.
- Execution reports created, skipped and failed records.
- Errors follow the documented transaction rollback boundary and return a nonzero exit code.

### US 2 — Implement Feature-Specific Sample Datasets and Insertion Functions

**User story:** As an SI&T tester, I want representative, linked sample data for NMDB features so that I can test supported scenarios consistently.

**Acceptance criteria:**

- Sample datasets and insertion functions cover NRD, Update Nominations, Sensor Status, Mission Management, Intercept Correlation, EW Tracks, Activity Reports and NEC.
- Existing validation schemas and services are reused where business rules apply.
- Logical references resolve to actual database IDs.
- EW Tracks includes ten tracks with approximately ten points each.
- Activity Reports includes ten reports with track associations and most linked to missions.
- Required states, logs and relationships match the agreed scenarios.
- An unchanged rerun reuses or skips existing sample records without duplicating dependent data.
- Conflicting existing records are reported without being overwritten.
- Inserted scenarios are verified, including mission threat exports against the applicable XSD.

**Dependency:** US 1.

**Delivery approach:** Start with EW Tracks and Activity Reports plus prerequisites, then complete the remaining features.

### US 3 — Execute Sample-Data Insertion Through Jenkins — Optional Follow-Up

**User story:** As an NMDB developer or tester, I want to trigger the sample-data command through Jenkins so that I can prepare dev or staging without running commands directly on the server.

**Acceptance criteria:**

- The job accepts an approved environment, dataset and feature selection.
- The job invokes the same CLI after required migrations have completed.
- Credentials are supplied through existing Jenkins credential management.
- Runs against the same target are serialized.
- A nonzero CLI exit code fails the job.
- Execution output is retained for troubleshooting.

**Dependencies:** US 1 and the relevant feature insertion functions from US 2.

US 1 and US 2 cover the first working delivery. US 3 adds an optional execution interface without changing the insertion logic.
