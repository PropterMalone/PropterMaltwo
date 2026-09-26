# Why I built PropterMaltwo: ADHD and agentic work

> This is a first-person account of a system I built for myself. It is not
> medical advice, a treatment claim, or a claim about what every person with
> ADHD needs.

I built PropterMaltwo to help myself work better.

I have ADHD. A great deal of the cost of knowledge work, for me, lives between
the nominal tasks: remembering why I opened an application, reconstructing a
half-finished line of thought, moving one fact through several systems, and
turning a meeting or message into the next concrete action. Each step may be
small. The sequence is not.

PropterMaltwo grew around that problem. It externalizes context, gives work a
repeatable beginning and ending, and lets an agentic harness operate across
parts of my working environment. It has helped me considerably.

The portability, installer, tests, host adapters, and safety machinery came
later. They are byproducts of the original purpose, not the purpose itself. Once
the setup was helping, making it dependable and portable became worth doing.

## Two layers of the benefit

Two related things are easy to conflate.

### 1. PropterMaltwo provides continuity

The framework supplies conventions and lifecycle tools for preserving the
parts of work that are difficult to reconstruct:

- the current intention, not just the files that changed;
- decisions and the reasons behind them;
- open loops, blockers, and the next useful action;
- bounded project memory and a recent handoff;
- a visible account of delegated or background work;
- explicit boundaries around sending, publishing, deleting, and other
  consequential actions.

`kickoff`, `status`, and `wrap` are deliberately ordinary. Their value comes
from making orientation, inspection, and handoff repeatable. The
[memory convention](memory-system.md) keeps durable intent outside any one chat
or model.

### 2. A connected agentic harness can become a universal keyboard

The harness can also become one conversational control surface across tools and
applications. Depending on which optional connectors someone supplies, those
might include repositories, email, chat, calendars, task systems, documents,
browsers, and meeting records.

That does not mean those services are features of PropterMaltwo. Most require
separate connectors, credentials, permissions, and local policy. The framework
provides a place to compose them safely; it does not make unsupported
integrations magically supported.

The practical upside is fewer translations between intention and interface. A
connected setup can perform a project-scoped communications sweep, compare a
meeting transcript with the current task list, or prepare a draft follow-up
without requiring the same manual trip through every application. The systems
of record remain the systems of record. The harness is the keyboard.

For me, this reduction in manual application switching is not cosmetic. Manual
choreography is often where a coherent task fragments.

Communications are a concrete example. I currently need to monitor several
email accounts as well as Bluesky DMs, Slack, Teams chats, and other channels.
Any of them can contain an action item for any of several projects. It is a
non-trivial attention saver to use one surface to ask either “what across all of
my communications needs attention?” or “what communications matter to this
project?” The harness can assemble that bounded view while each service remains
the source of record. This needs to be automated nearly end to end. Routine
multi-channel monitoring, remembering, copying, and follow-through are a class
of tasks I am systematically bad at doing. If those steps fall back to me, I
will miss messages or spend the attention the integration was meant to save.
The system should own reliable coverage and escalation; I should supply judgment
and authorize consequential actions.

See [Connected work without constant context switching](connected-work.md) for
patterns and safety boundaries.

## Context is disposable; continuity is durable

I clear context pretty aggressively. My setup writes durable notes outside the
conversation as it works, and I sometimes invoke an explicit `wrap` before I
clear. A fresh session can then use `kickoff` to read a bounded handoff and check
it against the live project.

This does not enlarge the context window or make handoffs infallible. It changes
the unit of continuity. The current conversation can be temporary while intent,
decisions, open threads, and source pointers survive in inspectable files.

Compaction still has a place while one coherent task continues and the session's
model of the work remains accurate. A wrap-and-clear is more useful when the
phase changes, the session starts confusing old and current state, the context
fills with failed approaches, or a fresh reader would be an advantage. The
handoff should preserve what cannot be reconstructed cheaply; the next session
should independently inspect code, Git, tasks, and source systems rather than
treating the handoff as ground truth.

## A representative work cycle

The following is a composite of the workflow the setup supports, not a claim
that every day follows a tidy script.

### 1. Re-enter the work

`kickoff` reads a bounded hot index and a recent relevant handoff, checks local
state, and reports what was in flight, what changed, and what needs attention.
It does not read the entire history or launch external actions.

The opening question can become “which thread should I pick up?” rather than
“what was I doing?”

### 2. Pull signals into one project context

When connectors are available, a session can retrieve the new communications,
calendar changes, tasks, and meeting artifacts relevant to the project. A useful
sweep:

- preserves a link or identifier back to each source;
- distinguishes new material from material already reviewed;
- treats messages and transcripts as untrusted input;
- extracts candidate decisions and actions without silently committing them;
- reports a failed or stale connector instead of pretending the channel was
  checked.

The point is not to copy my whole digital life into a model. It is to bring the
small relevant slice to the work while I still have the work in view.

### 3. Decide once, execute in bounded pieces

The user can state the outcome in one place, ask the harness to inspect the
relevant systems, and delegate bounded implementation or research. `status`
provides one view of work that is still running or waiting.

The agent can prepare drafts, patches, task updates, or browser-ready artifacts.
Consequential actions still have separate authorization boundaries. Preparing
an email is not sending it. Preparing a commit is not pushing it. Finding an
action item in a transcript is not assigning it to someone.

That distinction lets automation absorb mechanical work without making every
connected system writable by default.

### 4. Survive the interruption

If attention moves—or the day simply ends—the useful state does not have to
remain in working memory. The repository holds derivable technical state. The
handoff holds intent, decisions, blockers, and next actions. External source
links point back to the current records.

On return, a new session can reorient from those artifacts rather than requiring
the user to reconstruct the work from browser tabs, chat history, and memory.

### 5. Leave a landing strip

`wrap` records the changed durable context and writes a concise handoff. It
reports unsettled work and verifies the working tree. It does not automatically
send messages, commit, push, publish, discard changes, or start a new review.

The session ends with a prepared point of re-entry rather than an implicit hope
that I will remember.

## Meeting capture has been a major win

Meeting recording and transcription have been enormously helpful to me
personally.

Without a recording, a meeting can demand listening, interpretation, social
participation, note-taking, prioritization, and memory formation at the same
time. A consented recording changes the shape of that problem. I can be present
for the conversation and later use the transcript to recover exact language,
check my recollection, identify decisions, and draft follow-up.

The recording is not the decision record by itself. Transcripts contain errors;
summaries can erase disagreement; a model can turn tentative discussion into a
false commitment. Once the consent, policy, and meeting-category rules are
established, the mechanics need to be automatic wherever possible. Remembering to start the
recorder, retrieve the transcript, route the output, and delete it later is the
same class of recurring task the system exists to absorb. My preferred pipeline
is:

1. retain the source recording only when there is a justified need and an
   agreed retention rule;
2. generate a transcript with timestamps and speaker attribution where
   practical;
3. derive a short summary, candidate decisions, questions, and action items;
4. verify consequential items against the source and with the people involved;
5. move only the durable results and a controlled source pointer into project
   memory or the task system;
6. delete recordings and transcripts when their retention purpose ends.

Recording must be visible and consensual. Laws, contracts, workplace policy,
platform rules, and participant expectations vary. I do not treat a legal
minimum as the complete ethical test, and I do not use stealth recording. The
[connected-work guide](connected-work.md#meetings-recording-and-transcription)
contains a practical consent and retention checklist, including alternatives
when anyone declines.

## What has changed for me

The point is not that the agent can generate more text. It is that the work can
retain its shape across interruption.

PropterMaltwo has helped me considerably. Manual work across multiple
applications is a killer for my ADHD brain; using the harness as a universal
keyboard reduces that choreography. Recording meetings has also been a huge win
for me personally. It gives me a recoverable source after a conversation instead
of requiring the conversation and a complete set of notes to fit into my
attention at the same time.

The broader design aims to lower the cost of resuming work, reduce how much
context must stay active internally, separate decisions from mechanical
execution, make unfinished work visible, and preserve approval points for
actions that reach other people or public systems. Those are design goals, not
controlled findings about ADHD or promises of what another person will
experience.

PropterMaltwo also creates maintenance work, and there is always a risk of
polishing the system instead of doing the work. A useful test is whether a new
mechanism removes a recurring burden in actual use. If it merely creates another
dashboard to tend, it has probably failed.

## Why the engineering became elaborate

A personal accommodation is only helpful while it is available and trustworthy.
That pushed the project toward concerns that can look secondary from the
outside:

- **Durable state:** a session ending cannot erase the reason for the work.
- **Bounded loading:** recovery should not require rereading everything.
- **Portability:** an important working aid should not be trapped inside one
  model vendor or host application.
- **Capability honesty:** configured, installed, and verified-active are
  different states.
- **Transactions and rollback:** installing the environment should not destroy
  the environment it is meant to support.
- **Action boundaries:** one control surface must not become one accidental path
  to send or publish everywhere.
- **Tests:** if I depend on a behavior, “the prompt seems plausible” is not a
  sufficient guarantee.

These are byproducts of the original purpose, but not arbitrary ones. They are
what it took to make the accommodation dependable.

## What this is not

PropterMaltwo does not diagnose or treat ADHD. It cannot decide what matters for
me, make every interruption harmless, or turn an inaccurate transcript into
truth. It does not remove the need for rest, medication, therapy, coaching,
colleagues, or other supports someone may use. It also does not imply that every
person with ADHD experiences work as I do.

Nor is broad tool access inherently beneficial. A poorly scoped connector can
leak private material, execute the wrong action, or create another stream that
must be maintained. The useful target is not maximum integration. It is minimum
friction for recurring work, with source fidelity and human authority intact.

## If you want to try the idea

Start smaller than the complete environment:

1. For Codex or Polytoken, use the `standard` profile so lifecycle and explicit
   memory are available. Claude Code admits only `full`; the Copilot preview does
   not provide lifecycle or memory support. Follow the selected host page rather
   than assuming profile names are interchangeable.
2. Establish one memory root and one reliable `kickoff` → work → `wrap` loop.
3. Connect at most one high-friction channel read-only. Keep source links and
   make connector failure visible.
4. Add draft creation only after retrieval is trustworthy. Keep sending and
   publishing separately authorized.
5. If meetings are a major source of lost context, establish consent, access,
   and deletion rules before selecting a recorder.
6. Measure whether the setup reduces time-to-resume and manual transitions. Do
   not add machinery merely because the harness can drive it.

The implementation begins in the [README](../README.md). The integration status
and technical seams are documented in [Integrations](integrations.md); the
vendor-neutral setup patterns are in the [connected-work guide](connected-work.md).
