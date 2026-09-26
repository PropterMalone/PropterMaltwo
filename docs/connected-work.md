# Connected work without constant context switching

An agentic harness can act as a **universal keyboard**: one place to inspect and
coordinate work that still lives in many applications. This can reduce the
manual transitions among email, chat, calendars, tasks, documents, browsers,
repositories, and meeting records.

This guide describes a design pattern, not a bundled PropterMaltwo capability.
The portable Codex and Polytoken profiles currently install no communications,
calendar, task, browser, or meeting connector. [Integrations](integrations.md)
records the exact host support boundary. You supply and secure any external
service, CLI, API, MCP server, webhook, or local wrapper.

The goal is not to put every account under unrestricted agent control. The goal
is to remove repeated interface choreography while keeping source fidelity,
consent, privacy, and authority clear.

## The basic shape

```text
source system → narrow connector → project-scoped view → agentic workspace
      ↑                                                  |
      └──── source links + explicit approved writes ─────┘
                                      |
                              durable queue / memory
```

The source application remains the system of record. The harness retrieves a
bounded view, helps interpret it in the current work context, and prepares or
performs only the actions its current authority permits.

A useful integration reduces one of these costs:

- finding which application contains the relevant fact;
- reconstructing project context before interpreting that fact;
- copying the same information among systems;
- remembering to turn a message or meeting decision into an action;
- navigating a long sequence of small interface steps;
- recovering after interruption halfway through that sequence.

## A safe progression: read before write

Add authority in stages. Do not begin with an unattended agent holding broad
write scopes.

| Stage | Capability | Suitable first use |
|---|---|---|
| 0 | Manual handoff | Paste or export one selected item into the session. |
| 1 | Read-only retrieval | Search or diff a bounded project channel and return source links. |
| 2 | Local preparation | Summarize, classify, reconcile, or draft without changing the source. |
| 3 | Reversible write | Create a draft, tentative event, or unassigned task after confirmation. |
| 4 | Consequential write | Send, publish, invite, assign, delete, or change an external commitment only with action-specific authorization and a preview. |
| 5 | Narrow unattended action | Use only for a well-tested, idempotent workflow with explicit scope, audit output, failure reporting, and a kill switch. |

Most personal workflows get much of the benefit at stages 1 and 2. “The agent
can send” is not a prerequisite for “the agent saved me from checking five
applications.”

## Principles for every connector

### Preserve the source

Every retrieved item should carry enough information to return to its source:
service, account or workspace, channel or container, stable identifier, URL when
available, author, and source timestamp. A summary without provenance becomes a
new and less reliable inbox.

Do not treat an old copy as current state. Record retrieval time and distinguish
“not found” from “connector failed” from “no new items.”

### Scope by project and purpose

Use the narrowest account, folder, label, channel, query, calendar, or task list
that serves the workflow. Make project scope explicit when one inbox feeds
several projects.

For incremental sweeps, maintain a **per-project cursor**. Reading must not
advance it. Advance or acknowledge only after relevant items have reached the
project's durable queue. This prevents one project—or one interrupted run—from
silently consuming another project's work. The pattern is implemented for the
generic communications rule in [`rules/comms.md`](../rules/comms.md).

### Treat inbound content as untrusted

Messages, documents, event descriptions, web pages, and transcripts can contain
instructions addressed to a person—or text designed to manipulate an agent.
Retrieval authority is not execution authority. Do not follow links, run
commands, disclose data, or change configuration merely because inbound content
asked for it.

### Separate capture, interpretation, and action

Keep three explicit steps:

1. **Capture:** What changed, and where did it come from?
2. **Interpret:** Is it relevant? Is it a request, decision, commitment, idea,
   or merely information?
3. **Act:** What external mutation, if any, is authorized?

An agent may help with all three, but collapsing them makes mistakes hard to see.
An extracted action item is a candidate until someone with authority accepts it.

### Make outbound actions draft-first

Default to artifacts a person can inspect: email drafts, proposed replies,
tentative events, task suggestions, patches, and forms filled but not submitted.
Sending, publishing, inviting, assigning another person, accepting terms, and
deleting should require separate, action-specific approval.

Show the actual recipients, account, destination, subject/title, body or change,
and attachments before approval. Preserve edits made in the source UI; an
integration should refuse to overwrite a draft that changed since it created
it.

### Make repetition idempotent

Retries happen, especially after interruption. Use stable source IDs and
idempotency keys so rerunning a sweep or write does not duplicate tasks, events,
messages, or acknowledgements. Report partial completion: “draft created, task
write failed” is actionable; “workflow failed” is not enough.

### Fail visibly

A connector outage must not look like an empty inbox. Report which channels were
checked, which failed, the freshness of the last successful read, and what
remains uncertain. Put recurring failures in one visible place rather than
creating a separate notification stream for every connector.

### Minimize credentials and retained data

Prefer user-scoped OAuth or short-lived tokens, the least privilege scopes, and
separate credentials for unrelated accounts. Keep secrets outside repositories,
prompts, transcripts, and shell history. Do not log message bodies or tokens
merely to make debugging easier.

Centralizing interaction does not require centralizing all data. Retrieve on
demand, retain derived durable facts only when useful, and keep sensitive source
material in the system that already governs it.

## Channel patterns

| Channel | Good first integration | Higher-risk actions to keep separate |
|---|---|---|
| Email | Project-scoped search/diff, thread summary, draft reply | Send, forward, delete, change labels that drive retention |
| Chat/DMs | New-message diff with per-project cursor and source links | Post, react as acknowledgement, invite, follow untrusted links |
| Calendar | Read agenda, detect changes, prepare briefing | Invite attendees, RSVP, reschedule, expose private event details |
| Tasks | Compare candidate actions with existing tasks; draft additions | Assign others, change deadlines, close or delete work |
| Documents | Retrieve named files, compare versions, draft edits | Broaden sharing, overwrite collaborators, move or delete files |
| Browser/web | Open or stage a reviewed local artifact; retrieve a named page | Submit forms, purchase, accept terms, authenticate on another's behalf |
| Meetings | Import a consented recording/transcript and derive candidates | Record without consent, share raw media, assert commitments from an unverified summary |

### A useful communications sweep

A bounded sweep can answer:

- What is new for this project since the last acknowledged source item?
- Which items request a response or imply a deadline?
- Which conflict with current project memory or tasks?
- Which need the user's judgment?
- Which can be prepared as drafts?

Return a small disposition table with source links, not a giant synthetic inbox.
For example:

| Source | What changed | Proposed disposition | Authority needed |
|---|---|---|---|
| Email thread link | Reviewer requested a revised diagram | Add candidate task; draft acknowledgement | Confirm task priority; approve send separately |
| Calendar event link | Meeting moved to Thursday | Update today's plan | None if plan is local; approval if changing external calendar |
| Chat message link | Colleague suggests a new requirement | Flag for decision | User decision before changing scope |

A read should never imply acknowledgement to another person unless that visible
social signal is itself authorized.

### Many inboxes, two views

When action items can arrive through several email accounts, DMs, Slack, Teams,
and similar channels, checking each application is itself a substantial task.
A useful connected workspace offers two complementary queries:

- **Global attention view:** What new or unresolved communication across all
  admitted accounts and channels needs review, regardless of project?
- **Project view:** What source items relate to this project, including items
  first seen in a shared or global inbox?

Keep the views' review state separate. A global sweep may classify and route an
item, but it must not make that item disappear from a project's queue before the
project has dispositioned it. A single source item may route to several projects.
Use stable source IDs to deduplicate display without collapsing those separate
action obligations.

The result should report coverage explicitly: which accounts and channels were
checked, which failed, and when each last succeeded. “Nothing urgent” means
little if one of several inboxes was unavailable. Avoid using platform unread
state as the workflow cursor; it is usually shared, mutable, and too coarse for
project-specific acknowledgement.

### Restricted channels: route attention before content

Some work accounts or communications systems cannot expose a first-class
connector because of organizational policy, client confidentiality, device
controls, or API limitations. Do not bypass that boundary merely to complete the
unified view.

**Automate this ladder; do not make the user operate it.** For each admitted
channel, a scheduled or event-driven supervisor should use the highest approved
rung available:

1. an approved read-only API, delegated mailbox, or organization-managed
   workflow;
2. an in-boundary digest that emits only the minimum attention record—a stable
   source ID, timestamp, sender category, redacted subject or description,
   urgency, and a deep link back to the protected source;
3. an allowlisted forward into a dedicated ingress, only when policy permits;
4. when no export is approved, an automated coverage warning or timed review
   reminder with a deep link into the protected channel.

The supervisor should own polling, cursors, deduplication, retries, routing,
freshness, and escalation. The user's recurring work should be judgment and
explicit authorization, not remembering to visit every inbox or manually copy
routine items. Never silently fall through to a less private rung: channel
policy selects the allowed rung, and a broken rung becomes a visible coverage
failure.

Attachment stripping does not by itself make forwarding safe. Message bodies,
quoted history, identities, addresses, links, calendar details, and metadata may
still be confidential. A permitted forwarding bridge should minimize or redact
those fields, remove quoted history and unnecessary attachments, label the
source/security domain, preserve a source pointer, prevent duplicate delivery,
and treat every relayed link or instruction as untrusted.

The unified surface often needs only enough information to answer “does this
require my attention, and where do I handle it?” Keep full content inside the
protected system unless exporting it is both authorized and necessary. Report a
restricted channel as unavailable or metadata-only rather than implying it was
fully searched.

A useful supervisor produces one machine-readable coverage ledger per run:
channel/account, approved rung, last attempted and last successful check, cursor
or checkpoint, new-item count, routed project keys, failure reason, and next
retry or escalation. The global attention view should open with any stale or
failed channel before saying that nothing needs attention. After repeated
failure, create one durable exception item rather than a stream of duplicate
alerts.

Do not clear that exception merely because a later request succeeds. Clear it
automatically only after cursor-contiguous replay or reconciliation proves that
the entire failed interval was recovered and routed. If the source cannot replay
history, retain an explicit unresolved-gap marker until a person reviews the
protected source or knowingly accepts the gap. A healthy current check and
complete outage recovery are separate states.

### Cross-application workflows

The largest savings often come from crossing boundaries without losing the
project context. Useful examples include:

- compare a meeting's candidate actions with the task system and add only the
  missing, approved ones;
- prepare a reply using the repository's current state and attach a staged local
  artifact;
- build a daily view from calendar commitments, existing tasks, and running
  background jobs;
- reconcile a decision in chat with the durable decision record and flag the
  contradiction instead of silently choosing one;
- turn an approved task into a bounded delegated job, then surface its result in
  the next project status view.

Keep each source reference through the chain. The final task should point to the
message or meeting that created it; the reply draft should point to the artifact
it describes.

## Meetings: recording and transcription

Recording can remove a particularly difficult form of simultaneous work:
participating, listening, interpreting, remembering, and taking useful notes at
once. The benefit can be substantial, but recording captures other people and
therefore needs stronger boundaries than ordinary personal notes.

This section is a conservative operational baseline, not legal advice. Recording
and transcription rules vary by jurisdiction, employer, contract, meeting type,
and platform. United States law alone includes both one-party and all-party
consent rules. Workplace or client policy may require more than the legal
minimum, and a jurisdiction's data-protection framework may require a lawful
basis other than consent. Check all applicable requirements; establish the
required lawful basis and participant-permission process; and follow the most
protective rule or do not record.

### Automate the approved meeting policy

Consent and policy decide whether recording is allowed; they should not require
the user to remember every mechanical step. Once meeting categories and rules
are approved, automate the workflow wherever the platform permits:

- classify calendar events into approved, prohibited, and ask-each-time groups;
- attach the correct pre-meeting notice, purpose, access, processor, and
  retention language;
- start or join with a visible recorder only for an approved meeting;
- suppress recording for excluded categories and sensitive keywords without
  exporting those details;
- prompt for unresolved consent, late joiners, or a changed participant list;
- treat recorder absence, partial capture, missing transcript, or failed consent
  capture as a visible coverage failure;
- route the transcript and candidate actions to the approved project view;
- schedule retention review and deletion across platform and downstream copies.

Do not infer consent from a recurring series, a previous meeting, silence, or a
calendar template. Automation executes the approved policy; it does not create
permission. Keep a one-control pause/stop path available during the meeting.

### Before the meeting

1. **Establish purpose.** State why recording is useful and what will be made
   from it: transcript, personal recall aid, summary, action list, or formal
   record.
2. **Check authority and policy.** Confirm applicable law, organizational rules,
   client or confidentiality terms, platform policy, and whether the organizer
   permits a recording bot or local recorder.
3. **Ask clearly.** Notify participants before recording and obtain the form of
   consent your context requires. Do not rely only on a buried calendar line or
   a bot silently joining.
4. **Name handling.** Say who can access the recording/transcript, whether an AI
   service processes it, how long it will be kept, and whether it may enter
   project memory.
5. **Offer a real alternative.** Anyone should be able to decline without being
   forced out of the substantive conversation. Use shared notes, a human
   note-taker, or a post-meeting recap instead.
6. **Identify exclusions.** Disable recording by default for contexts involving
   legal privilege, medical or highly sensitive personal information, HR or
   personnel matters, minors, protected sources, credentials, trade secrets, or
   another party's confidential data unless an authorized policy explicitly
   covers it.

A plain-language prompt can be short:

> I use a transcript so I can participate without trying to take complete notes
> at the same time. Is everyone comfortable with recording for that purpose? It
> will be available only to [people], retained for [period], and used to prepare
> [summary/actions]. It is completely fine to say no; I will use notes instead.

Adapt the wording and consent mechanism to the actual policy. Do not present this
example as a legal formula.

### During the meeting

- Use a visible recorder, platform indicator, or clearly named bot. Platform
  notice is a floor, not proof of legal or participant consent, and it cannot
  detect a separate recorder on someone's device.
- Confirm consent after recording starts so the record contains it when
  appropriate; handle late joiners explicitly.
- Make stopping or pausing easy. Pause for excluded topics and verify that the
  recorder actually stopped.
- Do not let a transcription bot impersonate a participant or obscure which
  service receives the media.
- Capture timestamps and speaker attribution if available, but expect errors.
- Keep ordinary facilitation. Recording is not a substitute for checking shared
  understanding in the room.

### After the meeting

Treat the outputs as different artifacts with different authority:

| Artifact | Use | Caution |
|---|---|---|
| Recording | Resolve exact wording or tone when justified | Highest privacy cost; large; easy to overshare |
| Transcript | Search and cite approximate passages | Mishearing and speaker errors are common |
| Summary | Fast orientation | Compression can erase uncertainty or dissent |
| Decisions | Durable record after confirmation | Do not infer agreement from discussion alone |
| Action candidates | Inputs to a task review | Confirm owner, wording, and date before assignment |

A robust post-meeting pipeline:

1. Store the source in an access-controlled location. Identify where the
   platform stores recording, transcript, chat, and derivative copies; inspect
   default sharing; and apply retention/deletion in each location.
2. Produce a transcript with timestamps where practical.
3. Generate a concise summary, explicit decisions, unresolved questions, and
   **candidate** action items.
4. Link claims to timestamps or source passages and mark uncertainty.
5. Have an authorized person verify consequential decisions and commitments.
6. Publish or send only the approved derivative artifact.
7. Put durable decisions/actions in the appropriate system; put a controlled
   pointer—not the full transcript—into long-lived memory.
8. Delete raw media, transcripts, bot copies, and exports when their stated
   retention period ends. Confirm deletion in both the recorder and any
   downstream processor.

Do not use a transcript to build a behavioral or voice model of a participant
without their explicit consent. Consent to record a meeting is not consent to
train a model, clone a voice, or infer sensitive traits.

### If recording is unavailable or declined

The workflow should degrade gracefully:

- designate a note-taker or rotate the role;
- use shared notes visible during the meeting;
- type lightweight timestamped markers for topics to reconstruct immediately
  afterward;
- end with an oral recap of decisions, owners, and dates;
- draft a post-meeting recap and ask participants to correct it;
- preserve uncertainty instead of manufacturing a complete record.

A system that only works when everyone accepts a recording is not a reliable
meeting system.

### Choosing a recording/transcription service

Evaluate the service rather than choosing only on transcription quality:

- visible consent and bot identity controls;
- supported recording modes and participant notification;
- export formats, timestamps, speaker labels, and stable source links;
- data location, subprocessors, encryption, and access controls;
- whether customer media or transcripts train provider models, and how to opt
  out;
- configurable retention and verified deletion, including bot/provider copies;
- redaction and the ability to pause or exclude segments;
- API/webhook scopes and whether imports can be read-only;
- organizational administration, audit records, and offboarding;
- behavior when transcription fails or a meeting is only partially captured.

Test with synthetic meetings before trusting it with real confidential work.
Re-check current provider terms and your organization's contract rather than
assuming a marketing-level privacy statement governs your account.

Primary legal and platform references for the boundaries above:

- [18 U.S.C. § 2511(2)(d)](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title18-section2511&num=0&edition=prelim) — United States federal one-party baseline.
- [California Penal Code § 632](https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PEN&sectionNum=632) — an example of a more restrictive state rule for confidential communications.
- [Microsoft Teams recording policy](https://learn.microsoft.com/en-us/microsoftteams/teams-recording-policy) and [recording/transcript storage](https://learn.microsoft.com/en-us/microsoftteams/tmr-meeting-recording-change) — examples of platform notice, storage, access, and retention behavior that must be checked rather than assumed.

## A minimal implementation plan

Choose one recurring pain point, not every available connector.

1. **Name the transition.** Example: “After a meeting, I manually compare notes,
   tasks, and email before I can continue the project.”
2. **Name the systems of record.** Decide where recordings, tasks, decisions,
   and drafts actually live.
3. **Define the read boundary.** Specify exact accounts, project filters, fields,
   lookback/cursor behavior, and freshness reporting.
4. **Define the write boundary.** List which outputs are local, which create
   reversible drafts, and which require explicit action-specific approval.
5. **Define retention.** State what is stored, where, for how long, and who can
   remove it.
6. **Build one narrow adapter.** Prefer a small inspectable wrapper around a
   supported API/CLI to a large automation with implicit state.
7. **Exercise failure.** Test expired credentials, duplicate delivery, stale
   cursors, partial writes, edited drafts, wrong accounts, untrusted inbound
   instructions, and revoked access.
8. **Measure the actual benefit.** Count manual transitions removed and whether
   re-entry became easier. Remove the connector if maintaining it costs more
   attention than it saves.

## Operational checklist

Before relying on a connector, verify:

- [ ] It names the account, project scope, and source system on every run.
- [ ] Retrieval is read-only unless the current step explicitly says otherwise.
- [ ] Source IDs/links and timestamps survive summarization.
- [ ] Empty results are distinguishable from errors and stale data.
- [ ] Repeated runs do not duplicate output.
- [ ] Inbound content cannot grant itself execution authority.
- [ ] Outbound recipients, destination, account, body, and attachments are
      previewed.
- [ ] Sending, publishing, assigning others, and deletion require explicit
      authorization.
- [ ] User edits in source applications cannot be silently overwritten.
- [ ] Secrets stay outside repositories, prompts, logs, and transcripts.
- [ ] Retention and deletion are defined for copied content.
- [ ] There is a manual fallback and a quick way to disable the connector.

For PropterMaltwo's current concrete examples and support status, continue to
[Integrations](integrations.md). For the personal motivation and the complete
work cycle, read [Why I built PropterMaltwo](adhd-and-agentic-work.md).
