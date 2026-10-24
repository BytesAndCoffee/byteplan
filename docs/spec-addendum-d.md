# BytePlan Specification — Addendum D
## Assignments, Artifact Provenance, and Relay Development Cycles

**Status:** Proposal / normative design candidate  
**Target:** BytePlan Python reference implementation  
**Relationship to prior specifications:** Extends the BytePlan core specification and Addenda A–C. Where existing task terminology overlaps with *assignment*, this addendum proposes an explicit canonical abstraction; it does not assert that a migration is implemented.  
**Scope:** Core data model, provenance, verification semantics, optional workflows, and a GitHub Relay reference implementation.

**Release boundary update:** [Addendum E](spec-addendum-e.md) defers Assignment/Relay and graph
implementation beyond 1.0. Its persistent-ID/schema compatibility requirements supersede the
four-character and schema-v2 assumptions below; schema v2 now protects expanded task IDs.
See the [1.0 compatibility policy](compatibility-policy.md) for current public guarantees.

---

## D.1 Executive intent

**An assignment is BytePlan's fundamental unit of development work.** It describes an obligation, question, improvement, or defect to be addressed; preserves its identity through changes of location, executor, and workflow; and records the evidence and artifacts involved in its fulfillment.

An assignment **can consume and produce commits, pull requests, issues, tests, and other assignments**. Its relationship to those artifacts is explicit, typed, and potentially many-to-many.

BytePlan is to the *history of development intent and obligations* what Git is to the *history of code changes*. These are complementary histories, not competing versions of the same history.

**BytePlan supplies primitives; development cycles compose them.** Relay is one such cycle, not a compulsory BytePlan workflow. In the same way Git's distributed version-control primitives support email-patch workflows while GitHub popularized pull-request workflows, BytePlan assignments can underpin solo, team, issue-driven, or human/agent relay workflows without privileging one in the core.

Guiding statements:

- **Git records what changed. BytePlan records what those changes were intended to accomplish.**
- **An assignment may have an assignee, but does not require one.**
- **An artifact relationship is not proof of completion.**
- **A passing test is revision-bound evidence, not automatic permission to merge or resolve.**
- **The work moves forward; the context stays.**

## D.2 Terminology and invariants

### D.2.1 Assignment

An **assignment** is a durable, project-scoped identity for a unit of development intent. Existing BytePlan *tasks* map conceptually to assignments. The project may retain `task` in CLI/API names for compatibility; the underlying conceptual model is assignment.

An assignment MAY be created from any of the following:

1. A source comment such as `# TODO:` or `# FIXME:`.
2. A runtime-inert `@todo(...)` declaration.
3. An AST-detected implementation stub.
4. An external issue, request, review finding, or incident.
5. A human or AI agent explicitly creating an assignment.
6. An assignment decomposition or newly discovered regression.

Creation does **not** require a source binding, assignee, branch, commit, PR, or acceptance test.

Assignment invariants:

- Each assignment has a **permanent, non-reused project-local ID**. [Addendum E A1–A2](spec-addendum-e.md#track-a--pre-10-compatibility-and-reliability) defines the separate pre-RC1 persistent-ID compatibility migration: preserve existing four-character identities, allocate six-character IDs, and resolve exact identities before unambiguous abbreviations.
- An assignment is **not** equivalent to an external issue, a Git branch, a commit, a PR, or a source annotation. These have their own identities and lifecycles.
- Moving or removing source code does not silently close an assignment.
- A merged PR or matching commit message does not silently close an assignment.
- Ownership and workflow approval policy are orthogonal to source binding and resolution status.
- The registry remains Git-versioned and usable locally without GitHub or a live service.

### D.2.2 Artifact

An **artifact** is a development object that can be linked to an assignment: Git commit, GitHub/GitLab issue, PR, branch, release, test case, execution result, CI run, document, incident, or another assignment.

Artifact references SHOULD be qualified by provider, repository/project, object kind, and immutable identifier when possible. A mutable name such as `main` or `fix/142` MAY be recorded as contextual metadata but MUST NOT stand alone as immutable verification evidence.

Examples (illustrative, not prescribed serialization):

- `git:sha256-or-sha1:<full-object-id>` together with repository identity and algorithm.
- `github:BytesAndCoffee/bytesim:issue:142`.
- `github:BytesAndCoffee/bytesim:pull:151`.
- `python:test:tests/test_routing.py::test_withdrawals`.
- `byteplan:assignment:a83f`.

### D.2.3 Relationship

A **relationship** is a typed, directed connection between an assignment and an artifact, or between two assignments. It records *why* the artifact matters. Its existence does not imply that an outcome has been established.

Initial proposed verbs:

| Relation | Meaning | Caveat |
|---|---|---|
| `originated_from` | Report or observation caused creation | Source may be wrong or incomplete |
| `investigates` | Artifact contains investigation or causal evidence | Not necessarily the root cause |
| `consumes` | Assignment uses an artifact as an input | Does not transfer artifact ownership |
| `produces` | Assignment contributed to creating an artifact | Not exclusive ownership |
| `delivered_by` | PR/release conveys proposed implementation | Delivery is not acceptance |
| `verified_by` | Test execution/check supplies evidence | Bound to a particular revision and criteria |
| `blocked_by` | Another assignment/artifact prevents progress | Must avoid dependency cycles in schedulers |
| `supersedes` | Assignment replaces another obligation | Explicit transition required |
| `reverted_by` | Commit/PR reverses a related change | May invalidate prior evidence |
| `related_to` | General contextual association | No implied workflow semantics |

Providers MAY add namespaced relations. Unknown relations MUST round-trip without data loss. Link discovery MUST NOT imply authorization to modify the linked resource.

### D.2.4 Creation versus consumption

The terms **produce** and **consume** describe provenance and workflow inputs, not necessarily strict linear causation. An assignment may consume one PR, produce multiple commits, be delivered by another PR, and later consume a regression report. One commit or PR may contribute to multiple assignments; one assignment may span multiple PRs. Avoid a one-task-one-PR assumption throughout the system.

## D.3 Orthogonal assignment state

A single status field is insufficient for external issue intake and code-bound work. BytePlan SHOULD represent separate axes:

| Axis | Example values | Meaning |
|---|---|---|
| `lifecycle` | `open`, `in_progress`, `blocked`, `ready_for_review`, `resolved`, `cancelled` | Progress of the obligation |
| `binding` | `unbound`, `proposed`, `bound`, `stale`, `stripped` | Relationship to source declarations/symbols |
| `verification` | `not_configured`, `unverified`, `failing`, `passing`, `stale`, `needs_review` | Evidence state, not task status |
| `approval` | `not_required`, `pending`, `approved`, `changes_requested` | Policy-defined review gate |

These value names are **proposed API vocabulary**, not an assertion about existing code. Maintain compatibility with previously specified states, particularly `stripped` and `ready_for_review`, through an explicit schema migration.

Rules:

1. Intake of an external issue MAY create an **unbound** assignment in `open` lifecycle state.
2. Investigation MAY record candidate symbol locations and confidence as **proposed** binding, without claiming a verified root cause.
3. A source comment/decorator plus registry reconciliation MAY transition to **bound** after validation of identity and location.
4. A missing annotation is diagnostic; it is not resolution. Release-time decorator stripping retains intentional `stripped` binding semantics.
5. A revision-changing source edit or acceptance-criteria edit SHOULD invalidate affected verification evidence (`stale`) rather than erase history.
6. A regression-test scaffold using `pytest.fail(...)` is expected to fail and MUST NOT be counted as passing acceptance evidence.
7. A PR merge, check success, or agent declaration MUST NOT override a required manual approval.
8. Resolution MUST be an explicit, policy-permitted transition with recorded actor, evidence, and applicable revision.

### D.3.1 Acceptance tests versus evidence freshness

Do not conflate **test staleness** with **stale results**:

- **Stale execution evidence** means an earlier passing run is not authoritative for the current revision.
- **Inadequate acceptance coverage** means the test suite does not yet demonstrate the reported defect or required behavior.
- **Scaffolded regression test** means a real failing test skeleton exists but needs implementation and a meaningful red/green demonstration.

Each is independently representable. Reporting one must not automatically assert the others.

## D.4 Registry model and event history

The Git-tracked registry is the canonical persisted BytePlan record for assignments in the Python reference implementation. It SHALL preserve assignment identity, links, source bindings, acceptance criteria, and state history. The event stream MAY initially be embedded or maintained in a separate append-only file, provided atomicity and deterministic reconciliation are preserved.

Illustrative conceptual record (not an already-implemented schema):

```json
{
  "schema_version": "PROPOSED",
  "id": "a83f",
  "kind": "assignment",
  "title": "Fix withdrawn route advertisements",
  "lifecycle": "in_progress",
  "binding": {
    "state": "bound",
    "locations": [{
      "language": "python",
      "path": "src/bytesim/routing/rip.py",
      "symbol": "RIPRouter.advertise_routes"
    }]
  },
  "external_ids": [{
    "provider": "github",
    "repository": "BytesAndCoffee/bytesim",
    "kind": "issue",
    "number": 142
  }],
  "relationships": [
    {"relation": "originated_from", "ref": "github:BytesAndCoffee/bytesim:issue:142"},
    {"relation": "investigates", "ref": "git:commit:<full-original-sha>"},
    {"relation": "produces", "ref": "git:commit:<full-fix-sha>"},
    {"relation": "delivered_by", "ref": "github:BytesAndCoffee/bytesim:pull:151"}
  ],
  "acceptance": {
    "tests": ["tests/test_routing.py::test_withdrawals"],
    "coverage_review": "needs_review"
  },
  "verification": {
    "state": "stale",
    "last_evidence_id": "ev-0007"
  },
  "approval": {
    "required": true,
    "state": "pending"
  }
}
```

**Events** SHOULD capture actor type (`human`, `agent`, `ci`, `integration`), time, action, idempotency key, previous/current state, input references, relevant repository revision, and evidence references. Each event SHOULD be reproducibly ordered and traceable without depending on a particular hosted provider.

Git's history records the registry's file revisions, but an application-level event log can preserve *why* state changed and enable reliable queries. Do not describe this as a cryptographically tamper-proof audit trail merely because it is stored in Git.

## D.5 Bidirectional queries

BytePlan MUST eventually support navigation in both directions:

- **Assignment → artifacts:** What commits, PRs, issues, tests, reviews, and releases are related, and how?
- **Artifact → assignments:** What work did this commit/PR/test run investigate, contribute to, verify, invalidate, or deliver?
- **Assignment → assignments:** What work is dependent, blocking, superseding, or otherwise related?

Suggested future commands (subject to CLI compatibility and implementation planning):

```bash
byteplan show a83f
byteplan links a83f
byteplan commits a83f
byteplan prs a83f
byteplan impact HEAD
byteplan verify a83f
byteplan history a83f
```

`impact HEAD` SHOULD distinguish *explicit relationships*, *source-overlap candidates*, and *verified effects*; it MUST NOT assert that a commit completed an assignment simply because files overlap or a message mentions the ID.

Where practical, a Git trailer such as `BytePlan-Assignment: a83f` MAY facilitate discovery, but SHALL NOT be the sole authority for completion. Avoid requiring rewriting existing commit history or inserting metadata into third-party commits.

## D.6 Development cycles are composable, not canonical

**BytePlan core SHALL not mandate Relay.** A *development cycle* is an optional convention describing how actors and integrations operate over assignments.

Illustrative cycles:

- **Local/solo:** `TODO → assignment → implementation → verification → explicit resolution`.
- **Patch distribution:** `assignment → patches by email → review → integrated commits → verification`.
- **Team backlog:** `assignment ↔ Jira/GitHub issue → owner → implementation → approval`.
- **Agent handoff:** `assignment → agent investigation → durable registry state → another agent → tests → resolution`.
- **Relay:** `external issue → triage → candidate source → bound assignment → regression specification → implementation → revision-bound verification → required approval → merge/synchronize`.

Just as Git supports both patch-distribution and GitHub pull-request workflows, BytePlan supports multiple development cycles using the same underlying assignments and history. **The platform workflow must not be mistaken for the core protocol.**

### D.6.1 BytePlan Relay Development Cycle (BRDC)

Relay is a proposed, opinionated *reference workflow*, potentially branded **Relay for GitHub — Powered by BytePlan** for independent distribution, and **GitHub Relay** only as a clearly identified proposal for a potential first-party GitHub experience.

Stages, with valid backward transitions:

1. **Intake:** Register external report with deduplicated provider identity; no source binding required.
2. **Investigate:** Human or agent examines reproducibility, probable root cause, implicated history, and source symbols. Candidate diagnosis remains provisional.
3. **Propose binding:** Create an isolated branch and source FIXME or decorator linked to the same assignment ID; open PR as required by policy.
4. **Reconcile:** BytePlan checks the annotation, symbol, ID, external issue reference, and registry; marks source binding when warranted.
5. **Specify:** Add acceptance criteria and meaningful regression tests, including initially failing scaffold when appropriate.
6. **Implement:** Human or agent makes source changes and produces one or more commits/PRs.
7. **Verify:** Run linked tests and checks on an exact commit; record evidence and check that the acceptance criteria are actually covered.
8. **Approve:** Enforce repository policy, branch protection, and any mandatory human review. Verification readiness is not merge authority.
9. **Deliver and resolve:** Merge or otherwise integrate changes; reconcile final artifact refs; explicitly resolve assignment only when policy permits; synchronize external issue state.

Investigation may revisit a wrong binding; verification may return to implementation; review may request changes; a revert may reopen the assignment or create a related regression assignment. Relay is a **cycle**, not a strictly one-directional conveyor belt.

## D.7 GitHub Relay reference implementation

**Suggested package:** `relay-for-github` as an independently labeled example/reference integration, without implying GitHub sponsorship or affiliation.

Initial building blocks:

1. **GitHub Actions:** `issues.opened`/`issues.reopened` and selected label events trigger intake or review; PR events trigger reconciliation and checks. Repeated delivery MUST be idempotent.
2. **Copilot custom triage agent:** Investigates source/history and proposes a branch/PR, without automatically treating its diagnosis as fact.
3. **BytePlan CLI:** Deterministic local scan, bind, scaffold, validate, verify and registry maintenance; the missing intake/binding commands are proposed additions.
4. **BytePlan MCP adapter:** Exposes narrowly scoped operations to authorized coding agents, with explicit read/write capabilities.
5. **GitHub Issues API:** Synchronizes managed labels, links, and a single updatable status comment or appropriate project fields; no uncontrolled comment spam.
6. **GitHub Actions checks; optionally Checks API:** Publishes registry synchronization and revision-bound verification status. An independently published Checks API integration may require a GitHub App.
7. **Rulesets and branch protection:** Enforce required CI and maintainer approval, independently of agent conclusions.
8. **Optional GitHub App:** Installable webhook/permission packaging once reusable workflows prove valuable; not a dependency of BytePlan core.

**No GitHub-side event is proof of semantic completion.** Closing an issue or merging a PR should supply evidence or trigger reconciliation, not force assignment resolution.

### D.7.1 Minimal agent/adapter contract (proposed)

```text
intake_issue(provider, repository, issue_id) -> assignment_id
propose_binding(assignment_id, candidates, diagnosis) -> proposal_id
bind_source(assignment_id, source_ref, annotation_ref) -> binding_result
link_artifact(assignment_id, artifact_ref, relation) -> link_id
scaffold_regression(assignment_id, criteria) -> generated_files
record_verification(assignment_id, revision, test_result_refs) -> evidence_id
get_assignment(assignment_id) -> record
get_handoff(assignment_id) -> context_summary
request_resolution(assignment_id, evidence_refs) -> policy_decision
```

All write operations require authorization, validation, stable idempotency keys, and suitable branch/repository scope. `request_resolution` is policy-checked and MUST NOT be equivalent to an unconditional `resolve` endpoint.

## D.8 Consistency, identity, and safety

### D.8.1 Identity and de-duplication

- The assignment ID and an external issue's provider-specific ID are separate.
- Multiple external issues MAY link to one assignment; one issue MAY require several assignments.
- Intake de-duplicates using a canonical provider/repository/object identity, not issue title or body text.
- A GitHub event redelivery, force-push, reopened issue, or concurrent agent attempt MUST NOT silently create duplicate IDs or overwrite conflicting source bindings.

### D.8.2 Branch awareness and authority

- A FIXME added on an unmerged agent branch is a **proposed** project change, not proof that default-branch code has that binding.
- Registry data found on different branches may diverge; reconciliation must detect and resolve conflicts and preserve append-only history where possible.
- A merge may squash or rebase commits; provenance SHOULD distinguish working-branch commits from final integrated commit(s) and preserve links when object IDs change.
- A PR may include unrelated changes; links MUST identify contribution, not assume total ownership of the PR.

### D.8.3 Verification freshness

Evidence SHOULD capture full commit ID, repository identity, test identifier(s), command/configuration, run environment if significant, result, time, and provenance (local/CI/provider). Changing source, test code, dependencies, or acceptance criteria MAY stale previous evidence according to a conservative, documented policy. CI success on a PR head is not necessarily success on a later merge commit.

### D.8.4 Trust boundaries

- Issue bodies, PR descriptions, commits, and external comments are **untrusted input** to AI agents and integrations. They must never override repository rules or tool authorization.
- Agent tools SHOULD default to read-only reconnaissance; granting write/merge/close privileges must be a distinct choice.
- Avoid executing issue-supplied scripts or accepting instructions embedded in reports as trusted system policy.
- Never let AI agents use automation to bypass protected branches, required reviews, or secrets policies.
- Audit significant mutations and provide dry-run/review modes.
- Use least-privilege GitHub tokens; token issuance, scopes, and MCP exposure require careful isolation.

## D.9 Compatibility and migration

Addendum E A2 takes precedence over the implementation plan's original reservation of schema
v2 for Assignments. RC1 may require that boundary for expanded persistent IDs. The later
Assignment migration must choose an appropriate subsequent compatibility boundary; it does not
bring Assignment functionality into 1.0. See [the active release plan](IMPLEMENTATION_PLAN.md#active-release-plan--addendum-e).

1. Existing BytePlan four-hex task IDs remain stable and never reused.
2. Current `# TODO`, `# FIXME`, decorators, AST stub discovery, `.byteplan/tasks.json`, and CLI operations continue to work.
3. `assignment` becomes a **conceptual** primitive first; a command/filename/schema rename is explicitly **not required** for the initial implementation.
4. Existing registry records may migrate by adding relationship arrays, orthogonal state fields, and external identities. Unknown extension fields must round-trip where possible.
5. New provenance operations must be optional. An offline Python project with no GitHub account remains fully supported.
6. Existing Addenda A–C decisions about test scaffolds, explicit resolution, release/restore, Hatch, pre-commit, and AI-agent continuity remain in force except where an explicit conflict resolution is documented.

## D.10 Suggested phased delivery

All Assignment implementation remains outside RC1. [Addendum E E7–E8](spec-addendum-e.md#e7-relationship-to-the-assignment-model)
distinguishes Assignment obligations from graph relationships and places graph-assisted
Assignment/specification traceability on the 2.0 roadmap.

**D0 — Semantics and schema:** Define assignment object, artifact-reference namespace, typed relations, and orthogonal states. Establish migration tests and round-trip guarantees.

**D1 — Local provenance:** Implement bidirectional links, assignment history, `impact` candidate queries, branch-aware reconciliation, and revision-bound test evidence without network dependencies.

**D2 — Issue intake:** Implement idempotent external issue import, unbound assignments, proposed binding, and transition to source-bound annotations.

**D3 — Relay for GitHub MVP:** GitHub Actions, documented Copilot custom triage agent, CLI bridge, PR checks, and required human review. Demonstrate with a genuine issue and regression test.

**D4 — Agent tools and synchronization:** Narrow MCP contract, optional GitHub API status synchronization, cross-agent handoff, and richer provenance checks.

**D5 — Installable integration:** Evaluate dedicated GitHub App/Checks API and GitHub-native workflow proposal only after evidence from real use.

## D.11 Acceptance criteria for this addendum

- [ ] Assignment can exist without a source binding, assignee, commit, or PR.
- [ ] An assignment created by a source TODO retains its pre-existing ID and registry compatibility.
- [ ] A source-bound assignment can reference an external issue without conflating the two IDs.
- [ ] One commit/PR can be linked to multiple assignments; one assignment can link to multiple commits/PRs.
- [ ] Links carry typed provenance and can be queried in both directions.
- [ ] Merge, test success, deletion of a TODO, or issue closure alone never silently resolves an assignment.
- [ ] Verification evidence is bound to a specific repository revision and can become stale.
- [ ] Proposed source locations are distinguishable from validated source bindings.
- [ ] GitHub event replays and parallel agents do not silently duplicate assignments or lose updates.
- [ ] Required human review remains enforceable independently of the agent or BytePlan check result.
- [ ] Relay operates as an optional extension; offline/local BytePlan remains usable.
- [ ] An end-to-end reference demo shows `issue → intake → investigation → binding PR → scaffolded failing regression → fix → verification → human approval → reconciliation` with a demonstrable retry/failure path.

## D.12 Open design questions

1. Should `assignment` be an alias for the current `task` entity, or ultimately replace the public noun in CLI, APIs, and registry fields? Default: **alias first**.
2. Should event history be stored per assignment, in a single event log, or reconstructed partly from Git revisions? Default: **schema-preserved registry plus append-only event records** where justified.
3. What is the minimum universal artifact URI convention that works across repositories and hosts without requiring provider SDKs?
4. How should one assignment's contributions be tracked across rebases, squash merges, cherry-picks, and reverts?
5. Can readiness to review be machine-derived while adequacy of acceptance criteria stays a separate human/agent-assessed status?
6. What is the narrowest permission set necessary for a GitHub Relay triage agent, and how are proposed versus approved source bindings represented in review?
7. How does BytePlan detect that an issue represents a duplicate, a feature request needing several assignments, or an invalid report without making unsupported certainty claims?

---

**Proposed central thesis:**

> **BytePlan models assignments as durable units of development intent. Assignments consume and produce development artifacts, including commits and pull requests, while retaining identity, history, and verification evidence. Relay is one collaboration cycle built on those primitives—not the BytePlan protocol itself.**
