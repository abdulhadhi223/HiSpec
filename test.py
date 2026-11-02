# NMDB Sample Data Seeding — Solution Design and User Stories

| Item | Details |
| --- | --- |
| Design task | NEWSC-647 — NMDB Design: Generation/insertion |
| Related requirement | NEWSC-557 — Test data seeding for NMDB |
| Target environments | Development and SI&T staging |
| Delivery | Two user stories |
| Status | Final proposal for team review; application integration remains to be implemented |

## 1. Objective

Provide one centralized way to insert representative sample data for the eight listed NMDB feature groups into dev or staging. Testers must not need to upload separate files to multiple endpoints.

**Proposed solution:** one Python command inside the existing backend reads a baseline JSON dataset and the required NRD XML fixture, then runs feature-specific insertion functions in the correct order. These functions reuse the existing models, validation schemas and application services. Jenkins runs the same command.

The work answers two questions:

| Question | Answer |
| --- | --- |
| What is the input format? | JSON for feature scenarios, values and references; existing XML format for NRD import data |
| How is the data inserted? | A single CLI invokes the feature functions using the selected environment's database connections |

## 2. What we will implement

| Component | Purpose |
| --- | --- |
| Baseline dataset | Defines which sample records and scenarios to create |
| CLI | Accepts environment, dataset and selected features |
| Runner | Validates inputs, includes prerequisites, calls feature functions and reports results |
| Feature functions | Find or create valid records and return their database IDs |
| Jenkins job | Runs the same CLI using selected parameters and configured credentials |

The baseline and insertion code are version-controlled with the backend. The first version uses explicit functions and a small prerequisite map. It does not discover models automatically or generate business workflows from table definitions.

No new HTTP endpoint, generic seed-tracking tables, database-locking framework, dry-run preview, update/upsert engine or cleanup/reset command is part of this delivery. Production seeding and live external synchronization are excluded. Existing application migrations are a prerequisite, not an operation performed by the seeder.

## 3. Input format

### Files

| File | Contents |
| --- | --- |
| `app/seeding/data/baseline.json` | Sample records, scenario values, logical references and generation settings |
| `app/seeding/data/nrd_sample.xml` | Representative data in the existing NRD import format |

Multiple files may exist internally, but they are consumed automatically by one execution. No separate manual upload is required.

### JSON example

The following illustrates the seed structure. It is not a complete NMDB API payload; required domain fields and valid states will be taken from the actual schemas during implementation.

```json
{
  "dataset": "baseline",
  "features": {
    "nrd": {
      "xml_file": "nrd_sample.xml"
    },
    "missions": {
      "records": [
        {
          "key": "mission-01",
          "values": {"name": "Sample mission 01"}
        }
      ]
    },
    "ew_tracks": {
      "count": 10,
      "points_per_track": 10
    },
    "activity_reports": {
      "records": [
        {
          "key": "report-01",
          "values": {"title": "Sample activity report 01"},
          "mission_ref": "mission-01",
          "track_refs": ["track-01"]
        }
      ]
    }
  }
}
```

- `key` identifies a sample record within the dataset.
- `values` contains fields mapped to the existing application schema.
- References such as `mission_ref` identify related sample records without hardcoding database-generated IDs.
- Counts allow simple Python loops to generate repetitive data such as track points.

Use curated values for states, locks, nominations and other workflow scenarios. Use fixed generation inputs and timestamps for repetitive records so the same dataset produces the same intended data. The complete baseline includes all required records, including ten reports; the example above shows only one.

NRD XML is passed directly to the existing import business logic. The seeder does not create a new XML import implementation. Credentials and database connection strings are not stored in the fixtures.

## 4. Centralized command and environment selection

Proposed command interface:

```bash
python -m app.seeding --environment dev --dataset baseline --features all
python -m app.seeding --environment stage --dataset baseline --features all
python -m app.seeding --environment dev --dataset baseline --features ew_tracks activity_reports
```

| Parameter | Behavior |
| --- | --- |
| `environment` | Selects the approved dev or stage connection configuration |
| `dataset` | Selects the packaged sample dataset |
| `features` | Selects all supported features or a named subset |

The selected profile resolves the actual database and schema using existing application configuration. Unknown or production targets are rejected. Missing configuration must not silently fall back to another database or schema.

Where NEC uses its own database, its function uses the configured NEC connection for the same environment. One command can coordinate more than one database connection; it does not promise a transaction spanning databases.

The command runs in the backend container or another approved environment with the application dependencies and database access. It calls Python service functions directly. There is no requirement to send HTTP requests to every feature endpoint.

The Jenkins job accepts the same parameters, supplies existing credentials, invokes the CLI and retains console output. Jenkins seeding jobs for the same target run sequentially. Direct CLI execution is coordinated so it does not overlap another seeding operation or migrations. The first version assumes one operator/job at a time; it does not claim database-enforced concurrency protection.

## 5. How insertion works

### End-to-end workflow

1. Read the environment, dataset and feature selection.
2. Resolve and display the non-secret target database/schema details; check migration readiness.
3. Load the JSON dataset and any required XML fixture.
4. Validate input structure, required values and references before writing wherever possible.
5. Include the selected features' prerequisites and establish execution order.
6. Call each feature function with the appropriate database session, its input data and the previously resolved references.
7. Find matching sample records or create new records through the approved application path.
8. Verify the feature's records and relationships, then commit that feature.
9. Run the relevant checks requiring committed data and print the final execution summary.

A prerequisite is included once. Unknown features, missing prerequisite data and dependency cycles produce clear errors. During development, `all` must fail if a required loader is not yet implemented; it must not silently skip a feature.

### What each feature function does

| Step | Responsibility |
| --- | --- |
| Validate | Map inputs through existing schemas and applicable business validation |
| Find | Use a verified database lookup to identify existing sample records |
| Resolve | Convert logical references to actual database IDs |
| Insert | Call existing services, or use ORM for reviewed simple fixture inserts |
| Verify | Check expected records, states and relationships |
| Return | Return a dictionary of logical keys and database IDs, plus created/reused counts |

Workflow-sensitive data must follow application rules. Setting a status column directly is not sufficient when that status requires history, ownership or other associated records. Existing service functions needing a user identity must receive an explicit test user/context.

### Concrete example: tracks and activity reports

The runner loads the required shared reference data and mission records, then creates ten EW tracks with ten points each. It stores their returned IDs in memory:

| Logical key | Resolved value |
| --- | --- |
| `mission-01` | Actual mission database ID |
| `track-01` | Actual first track database ID |
| `track-02` | Actual second track database ID |

The activity-report function reads `mission_ref` and `track_refs` from the JSON, looks up the corresponding IDs and creates the report associations.

The exact shared-reference prerequisites must be read from the actual models and services. Loading a platform or sensor prerequisite does not automatically mean loading every scenario in the Sensor Status feature.

## 6. Repeat execution and failures

### Finding existing sample data

Repeat detection belongs to each feature function. It uses an existing unique identifier or verified unique combination of fields in the application database. Record the exact lookup while implementing that feature. Do not assume a display name is unique.

The JSON `key` is a reference label; it does not automatically become a database column. On every execution, the feature function reconstructs the in-memory key-to-ID dictionary from its database lookup.

| Existing data | Behavior |
| --- | --- |
| No matching record | Create the record and its required children/relationships |
| Exactly one matching record with the expected scenario intact | Reuse it and return its ID |
| Ambiguous match or conflicting values | Stop with a clear conflict; do not overwrite |
| Parent exists but required children, relationships or scenario state differ | Report the inconsistency; do not silently claim success or create duplicates |

NRD repeat detection must also identify the completed import and its expected records/logs. Do not re-run an import simply because the XML file is present. Time-sensitive scenarios, such as expiring locks, must be checked for current validity; unchanged fixture input does not mean the scenario is still usable.

**Implementation gate:** each feature must demonstrate a reliable lookup and unchanged rerun before it is marked complete. If the current model provides no reliable way to identify its sample records, record that as a concrete implementation blocker. This document does not assume every unseen model already has a suitable key. No generic tracking-table project is introduced in advance.

### Transactions and failure behavior

Use one transaction per feature. The insertion function and reused service logic participate in that transaction; they must not commit individual child records independently.

If an existing service commits internally, adapt its reusable insertion logic to accept the caller's transaction before using it in the seeder. Preserve existing API behavior when making that adaptation.

| Failure point | Result |
| --- | --- |
| Target/input validation before insertion | Stop without starting feature writes |
| During a feature's insertion or database verification | Roll back that feature and stop; previously committed features remain |
| During API/export checks after commit | Report verification failure; committed records remain |

After correcting the cause, rerun the command. Earlier valid records are found and reused; the incomplete feature is attempted again. The runner does not automatically reset data modified during testing.

Logs distinguish committed, reused, rolled-back and not-run features. A failed insertion or required verification returns a nonzero exit code. Rolled-back rows are not reported as successful inserts.

## 7. Required feature coverage

| Feature | Sample data to prepare | Completion check |
| --- | --- | --- |
| NRD | Representative XML input and import logs | Imported records and logs are available; reruns do not duplicate the import |
| Update Nominations | Supported states, locks, multiple users and dirty proposals | Workflow state, ownership and locking behavior match the scenarios |
| Sensor Status | Platforms, linked sensors, supported statuses and multiple sensors on a platform | Correct associations and status coverage |
| Mission Management | Supported mission states, required assignments and threat-export scenarios | Mission relationships are valid; exported threat XML passes the applicable XSD |
| Intercept Correlation | Emitter/platform selections and initial administration configuration | Bruno matching examples work with the seeded selections/configuration |
| EW Tracks | Ten tracks with ten points each and varied emitter/sensor associations | Ten baseline tracks, one hundred points and valid associations |
| Activity Reports | Ten reports linked to EW tracks, with most linked to missions | Expected counts and valid track/mission relationships |
| NEC | Controlled synchronization states and logs in the NEC target | States and logs are inspectable without triggering live synchronization |

Supported states and field values come from the repository. For Activity Reports, the baseline records explicitly list which reports have mission references; the loader verifies that this satisfies both the requirement and the actual model constraints.

Mission platform assignment must reuse the application logic that creates the required sensor associations. The seeder must not duplicate sensors already inserted by that workflow.

Sample data can support existing ELT testing. Implementing new ELT/MDF generation is outside this sample-data task.

## 8. Implementation priority

Start with a real linked example, then extend the same mechanism.

| Priority | Action | Tangible result |
| --- | --- | --- |
| 1 | Inspect models, schemas and services for EW Tracks, Activity Reports and the minimum required references/missions | Identify required fields, lookups, service calls, prerequisites and transaction behavior |
| 2 | Implement the US 1 core: CLI, environment resolution, JSON reading, function registry and execution loop | One command can invoke selected feature functions |
| 3 | Implement the first US 2 functions for the linked tracks/reports example and prerequisites | One dev execution creates usable linked data |
| 4 | Prove repeat execution, valid relationships and rollback of a failing feature | A tested first milestone, not just a framework demonstration |
| 5 | Add the remaining feature scenarios and complete their checks | All eight features supported |
| 6 | Finish Jenkins wiring and run the completed baseline in stage | The same command available to the testing team through Jenkins |

The two stories have separate responsibilities but can be developed together. US 2 analysis begins immediately; its functions integrate once the US 1 runner is available. Completing tracks/reports is the first milestone, not completion of all feature coverage.

Suggested implementation files:

| Location | Purpose |
| --- | --- |
| `app/seeding/__main__.py` | CLI entry point |
| `app/seeding/runner.py` | Feature registry, prerequisites, execution and results |
| `app/seeding/features/` | Feature-specific insertion and verification functions |
| `app/seeding/data/` | Baseline JSON and NRD XML |
| `tests/seeding/` | Runner and real feature integration tests |

Follow existing repository conventions and reuse application configuration. The earlier SQLite prototype is a demonstration of the idea; it is not the NMDB integration implementation.

## 9. User Story 1 — Centralized execution for dev and staging

**As an NMDB developer or SI&T tester, I want to load a sample dataset through one command, also callable from Jenkins, so that environment preparation does not require manual uploads to multiple endpoints.**

### Implementation tasks

1. Add the CLI arguments for environment, dataset and features.
2. Reuse existing dev/stage database configuration and check the resolved targets.
3. Read the baseline JSON and referenced XML fixtures.
4. Add a simple registry of feature functions and their explicit prerequisites.
5. Execute functions in order, provide database sessions and share returned IDs.
6. Implement feature transaction handling, stop-on-failure and console results.
7. Add a Jenkins job that calls the same command and retains its output.

### Acceptance criteria

- One CLI supports dev and staging, `all`, and selected feature subsets.
- All required input files are consumed automatically by that invocation.
- Required prerequisites run before dependent features and are not executed twice.
- Unknown features, invalid targets and missing configuration fail clearly before feature insertion begins.
- Existing configured connections and sessions are used, including the NEC connection when required.
- A failure rolls back the current feature, stops subsequent execution and returns a nonzero exit code.
- Results accurately show committed, reused, failed and not-run work.
- Jenkins accepts approved parameters, uses existing credentials, runs seeding sequentially for a target and fails on nonzero exit status.
- Jenkins retains execution output without exposing credentials.

**Deliverable:** the working centralized runner, documented command and Jenkins invocation. US 1 does not own the creation rules or complete datasets for all eight features.

## 10. User Story 2 — Feature sample data and insertion functions

**As an SI&T tester, I want representative, correctly linked sample data for the listed NMDB features so that I can test supported states and workflows consistently.**

### Implementation tasks

1. Map each feature's actual models, schemas, service methods, lookup keys and prerequisites.
2. Prepare the baseline JSON sections and representative NRD XML.
3. Implement each feature's validation, existing-record lookup, insertion and verification.
4. Return logical-key-to-ID dictionaries for dependent features.
5. Deliver the linked EW Tracks and Activity Reports example first.
6. Extend to all eight feature groups and supply the required Bruno examples.
7. Verify first-run behavior, unchanged reruns, conflicts and dev/stage results.

### Acceptance criteria

- All eight feature groups have the required data and checks listed in section 7.
- Inputs use actual supported fields, enum values and business states.
- Required workflow logic is reused; simple ORM insertion is used only where it preserves application rules.
- References resolve to actual database IDs without environment-specific generated IDs in the fixtures.
- The baseline contains ten tracks, one hundred points and ten activity reports with the required associations.
- Reliable per-feature lookups are implemented and tested; reruns do not duplicate parents, children, links or logs.
- Ambiguous, incomplete or changed existing data produces a clear error without overwriting unrelated records.
- Mission threat exports validate against the applicable XSD and correlation examples return the expected results.
- NEC scenarios use the correct target and do not trigger live synchronization.
- The completed baseline is verified in both approved dev and stage environments.

**Dependency:** the US 1 core runner. Repository analysis and fixture preparation can start before the runner is complete.

**Deliverable:** the complete reviewed baseline, feature functions and verification evidence. A working tracks/reports example alone does not close US 2.

## 11. Presentation guide

### Start with this explanation

“We need to agree on the sample-data format and how to load it without manually uploading files to several endpoints. I propose one backend command. It reads a JSON baseline and the NRD XML fixture, calls the feature insertion functions in the required order, and loads the selected dev or staging database. Jenkins runs the same command.”

### Explain the work in five steps

1. **Input:** show the JSON example and explain that references such as `mission-01` are logical names, not database IDs.
2. **Execution:** show one CLI command and explain environment selection and automatic prerequisites.
3. **Example:** explain how track and mission functions return IDs, which the report function uses to create links.
4. **Delivery:** US 1 builds the runner; US 2 implements the feature datasets and insertion rules. Start by making tracks/reports work end to end.
5. **Proof:** show created records, rerun without duplication, and demonstrate clear failure/rollback behavior before extending to every feature.

### Questions the team may ask

| Question | Answer |
| --- | --- |
| Why JSON and XML? | JSON represents the feature scenarios. NRD already has an XML import contract, so we reuse it. Both are read by one command. |
| Why a function per feature? | Each feature has different required fields, relationships and business rules. A shared runner avoids repeating execution logic. |
| Does it require a new API? | No. The CLI calls application functions directly; Jenkins provides the shared execution interface. |
| How do we avoid duplicates? | Each function queries using its verified existing identifier and checks the expected related data before reusing it. JSON keys alone are not sufficient. |
| Does a failure undo everything? | It rolls back the current feature. Earlier committed features remain and are verified/reused on a subsequent run. |
| Can we start now? | Yes. First inspect the real tracks/reports creation paths and prerequisites, then connect them through the small runner. |

## 12. Definition of completion

The solution is complete when one command, invoked directly or through Jenkins, prepares the full eight-feature baseline in dev or stage without individual uploads; the data is usable through existing application functionality; unchanged reruns do not duplicate it; and failures clearly identify what was committed and what was rolled back.

This is a final proposed approach, not a claim that unseen source code has already been validated. Recording actual fields, supported states, matching keys and service transaction boundaries is part of the two implementation stories.
