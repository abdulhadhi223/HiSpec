# NMDB Test Data Seeding

Generation and Database Insertion — Design Spike

Design task: NEWSC-647 | Related requirement: NEWSC-557

Target environments: Development and SI&T staging | Status: Proposed design

## 1 Objective

Define a common approach to generate representative sample data and insert it into the databases used by the identified NMDB features. The solution should prepare usable test scenarios through one centralized execution process, reducing manual record creation, repeated API calls and individual file uploads.

This spike establishes the input format, generation approach, insertion strategy, dependency handling and validation expectations. It provides a shared design that can be applied feature by feature. Detailed source code, class structures and implementation instructions belong to the subsequent implementation work.

## 2 Scope and expected outcome

The proposed solution covers configurable sample-data generation, insertion of related records, reuse of existing prerequisites and verification of the resulting feature scenarios. It uses the factory_boy library for data generation and existing application capabilities for persistence and business operations.

The outcome is a repeatable way to prepare selected NMDB features for development, demonstrations and integration testing. Each supported feature can define its own scenarios while using the same execution and reporting approach.

### Design decisions

| Area | Proposed approach |
| --- | --- |
| Input | A version-controlled JSON dataset describes selected features, quantities, scenario variations and references. |
| Generation | Use factory_boy to produce sample objects from reusable definitions with valid defaults. |
| Insertion | Prefer existing application services where business behavior is required; allow ORM insertion where it preserves the required behavior. |
| Execution | Provide a common backend command-line entry point; automation can invoke the same process. |
| Dependencies | Resolve existing prerequisite records or prepare them before dependent scenarios. |
| Validation | Check both data constraints and whether the resulting feature scenario is usable. |
| Extension | Add feature-specific generation and insertion behavior within the common design. |

### Boundaries

Database provisioning and schema migrations remain part of environment setup. Production data loading, automatic discovery of business rules and a new user interface are outside this spike. XML import, export and other generated files are included only when explicitly required by a selected scenario.

<!--page-->
## 3 Proposed solution

The solution separates scenario configuration, data generation and database insertion. This allows quantities and supported variations to change without redefining the overall execution process.

| Component | Design responsibility |
| --- | --- |
| Dataset configuration | Describes what data is required for each selected feature. |
| Central execution | Reads the dataset, validates the selection and coordinates feature processing in dependency order. |
| Data generation | Uses factory_boy definitions to produce valid, representative sample objects. |
| Reference resolution | Finds existing prerequisite data and supplies real identifiers for related records. |
| Feature insertion | Applies the selected scenario through existing application services or the appropriate ORM persistence path. |
| Verification and summary | Checks stored records and relationships, then reports the result for each feature. |

### Role of factory_boy

factory_boy is a Python library for creating reusable sample-data definitions. It supports configurable values, sequences, related objects and integration with SQLAlchemy. These capabilities reduce the need to maintain a separate static record for every sample variation.

Within this design, factory_boy generates the data required by a scenario. Application-specific definitions provide valid defaults and supported variations. The library does not determine NMDB business rules or decide which application workflow must run. Those responsibilities remain with the feature design and existing application behavior.

### Generation and insertion approach

Generation prepares the values and relationships requested by the dataset. Insertion persists that data through the appropriate application path. An object generated successfully is not considered a completed scenario until the required records and relationships are stored and verified.

| Insertion route | When it applies |
| --- | --- |
| Existing application services | Creation or assignment requires validation, workflow transitions, derived records or other business behavior. |
| ORM database insertion | Sample records can be stored directly without bypassing required application behavior. |
| Existing import workflow | The scenario specifically needs to exercise file ingestion or import processing. |

The chosen route is documented for each feature. A common execution process may use different routes for different features. Existing services are invoked within the backend; the design does not require a manual sequence of external API calls.

<!--page-->
## 4 Dataset and execution design

### Dataset contents

JSON is the proposed configuration format. It describes scenarios and generation settings rather than listing every database row. The dataset remains separate from environment credentials and database connection settings.

| Configuration item | Meaning |
| --- | --- |
| Dataset identity | Identifies the agreed sample-data collection. |
| Selected features | Determines which supported feature scenarios are requested. |
| Quantities | Defines the number of main records and related records required. |
| Scenario variations | Selects supported types, states and other feature-specific options. |
| Relationships | Describes intended associations and prerequisite references. |
| Generation controls | Defines stable naming and reproducible variation where required. |
| Optional operations | Requests supported import, export or other workflow operations when relevant. |

For example, a dataset may request a set of missions with platform assignments, tracks with associated points, or reports linked to existing records. These are scenario descriptions; their detailed fields and allowed values follow the actual feature contracts.

### End-to-end execution

1. Select the dataset and use the application's configured target environment.
2. Validate requested features, quantities, supported values and available prerequisites.
3. Determine the execution order from the dependencies between selected scenarios.
4. Resolve reusable reference records and prepare required prerequisite data.
5. Generate sample objects using factory_boy and the selected scenario settings.
6. Insert the data through each feature's designated application or ORM path.
7. Verify stored records, relationships and required application behavior.
8. Return a summary of completed scenarios, created or reused records and any unsuccessful work.

### Relationships and data consistency

Related records use identifiers returned from creation or resolved from existing data. Prerequisites are prepared before records that depend on them. Application-generated associations are reused rather than inserted again by the seeding process.

Repeated runs should recognize previously seeded records using a documented feature-specific matching rule. Unrelated data must remain unchanged. Validation and transaction handling follow the selected persistence path, and the summary must distinguish completed work from incomplete work.

### Environment and execution model

The process runs against an already prepared development or SI&T staging environment using existing application configuration. Features with separate databases use their appropriate connections. A future Jenkins integration invokes the same entry point and retains its execution summary; it does not introduce a different data-generation approach.

<!--page-->
## 5 NMDB feature coverage

The following scope identifies the feature areas to support through the common approach. Exact scenarios, quantities and valid states are agreed for each feature before implementation. Inclusion in this table does not indicate that all scenarios have already been implemented.

| Feature | Intended sample-data coverage |
| --- | --- |
| NRD | Representative reference and domain data with valid relationships for the selected scenarios. |
| Update Nominations | Nominations covering agreed types, states and related proposal information. |
| Sensor Status | Sensor and platform relationships with the status variations required for testing. |
| Mission Management | Mission metadata, platform assignments and application-managed sensor associations; additional supported operations as required. |
| Intercept Correlation | Reference data and configuration needed to exercise agreed correlation scenarios. |
| EW Tracks | Tracks, track points and supported emitter or sensor associations. |
| Activity Reports | Representative reports linked to the records required by the reporting scenario. |
| NEC | Representative cache data and agreed synchronization scenarios in its configured environment. |

### Applying the design to another feature

Each feature follows the same design activities. These activities define the information needed for implementation without prescribing source-code structure.

| Activity | Required outcome |
| --- | --- |
| Define the scenario | Agree the records, supported variations, relationships and expected quantities. |
| Identify dependencies | Specify data to reuse and prerequisites that must be prepared. |
| Define generation rules | Establish valid defaults and configurable variations for factory_boy generation. |
| Select the insertion route | Identify the application behavior or ORM persistence path that preserves feature correctness. |
| Integrate with execution | Make the feature selectable through the dataset and establish its dependency order. |
| Define completion checks | Specify expected stored data and evidence that the scenario works through the application. |

### Optional file-based scenarios

Database population is the primary objective. XML is not a mandatory intermediate format for inserting sample data. Where a scenario specifically tests import or export, the process uses the application's existing file handling and validation capabilities.

Seeding records alone does not demonstrate that an import, export or MDF generation workflow works. Such scenarios require the actual operation and validation of its result. Optional operations are enabled only when supported by the feature implementation.

### Quality expectations

Generated data must satisfy required fields, allowed values, uniqueness constraints and valid relationships. Completion checks should include application usability as well as database presence. Representative quantities should be measured during implementation; the spike does not claim a throughput target or bulk-loading capability.

<!--page-->
## 6 Mission Management POC overview

The Mission Management POC was carried out to demonstrate automated sample-data generation and database insertion through the proposed common execution approach. It focuses on creating missions and assigning existing platforms, with the application handling the associated sensor assignments automatically.

### Scope demonstrated

| Area | POC approach |
| --- | --- |
| Scenario configuration | A baseline dataset provides the mission count, mission types and status variations. |
| Sample-data generation | factory_boy provides reusable mission input definitions for the configured scenarios. |
| Mission creation | Missions are inserted through the existing application service. |
| Platform assignment | Available platform instances are resolved from existing data and assigned to the missions. |
| Sensor association | The platform assignment service automatically associates the relevant sensors with the mission. |
| Execution result | The process returns a summary of created or reused missions and their identifiers. |

### Observed outcome

Mission creation and platform assignment are working in the POC, including automatic sensor association. This demonstrates that sample-data preparation can reuse existing application behavior without manually creating every related record or calling multiple endpoints.

The POC uses existing platform and sensor data as prerequisites. Its demonstrated scope is mission creation and assignment; it does not establish completion of the other feature scenarios listed in this design.

### Relevance to the proposed design

The same approach can be applied to another feature by defining its sample-data requirements, generating suitable inputs with factory_boy, resolving its prerequisites and using the appropriate insertion path. Each feature retains its own business rules while sharing the configuration, execution and reporting approach.

Reference: factory_boy official documentation — https://factoryboy.readthedocs.io/en/stable/

<!--page-->
## 7 User story

### US1 — Automated sample-data generation and insertion for NMDB

Provide a centralized mechanism to generate and insert representative sample data for NMDB features in development and SI&T staging environments. Developers and testers should be able to prepare supported feature scenarios through a single execution process, without manually creating individual records, uploading multiple files or invoking a sequence of feature endpoints.

The solution will use a configurable dataset to describe the selected features, required quantities, supported variations and relationships. The factory_boy library will generate the sample data, while existing application services or appropriate ORM insertion will persist it and preserve the required business behavior. Prerequisite records will be resolved or prepared before dependent data is inserted.

Implementation will progress feature by feature across the coverage defined in section 5. For each feature, the agreed scenarios and completion checks will be recorded within this story. Shared execution and feature-specific generation and insertion are part of the same delivery scope. The Mission Management POC provides the initial working reference.

### Implementation tasks

1. Define the sample-data scenarios for each selected feature, including required records, supported states, quantities and relationships.
2. Establish the common dataset configuration and execution process, using the application's existing development and staging database settings.
3. Define reusable sample-data generation rules using factory_boy, with valid defaults and configurable scenario variations.
4. Identify prerequisite data and coordinate processing so that dependent records use valid existing or newly created references.
5. Integrate each feature's insertion behavior through existing application services or ORM persistence, preserving validation, workflow behavior and automatic associations.
6. Verify the generated records and relationships through database checks and relevant application functionality.
7. Provide an execution summary and document supported scenarios, prerequisites and usage for each completed feature increment.

### Acceptance criteria

- A single execution process prepares the selected supported features in development and SI&T staging using the configured dataset and application environment.
- The dataset controls required quantities, supported variations and relationships without requiring each sample record to be defined manually.
- factory_boy generates representative data that satisfies the selected feature's required fields, allowed values and data constraints.
- Prerequisite records are available before dependent data is inserted, and relationships use valid database identifiers.
- Existing application services are reused where business behavior is required; associations created automatically by the application are not duplicated.
- Inserted data is available through the relevant application functionality and matches the agreed scenario quantities, states and relationships.
- Previously seeded records are recognized according to the feature's matching rule, and unrelated records are not overwritten.
- The execution summary identifies created or reused records and clearly reports incomplete scenarios or validation failures.
- Each completed feature increment includes its configuration, documented prerequisites and verification evidence. Additional features use the same common approach.

### Deliverables

A working centralized seeding capability, configurable sample datasets, factory_boy generation definitions, feature-specific insertion and verification, execution summaries, and usage documentation. Delivery is tracked feature by feature against the agreed scenarios and acceptance criteria within this story.
