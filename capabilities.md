# CAPABILITIES.md

**Student:** Sheshachalam Ratnala, cert-aai-2026-06-0019  
**Repository:** https://github.com/rsheshu/Agentic-InboxHero

---

## The system, in one paragraph

This project processes an inbox through a lightweight triage pipeline that tags messages, routes them to reply/archive/defer/delegate/escalate decisions, and applies saved user preferences before any irreversible action. The system uses a crew.ai-based actor pattern for drafting and action-gating while keeping retrieval anchored to message threads, so the decision logic stays grounded in the actual conversation context.
Generates outbox for the processed messages and dashboard.html for the stats of the messages processed.
- **output.json:** for the Grouping results
- **routing.json:** Deterministic routing
- **outbox/decision_log.jsonl:** The logger evidence for the runs
- **outbox/mxxx:** The processed messages

## Design choices

- **Framework:** crew.ai is used for the drafting and policy-gating steps, while the broader pipeline remains a simple sequencing pattern.
- **Retrieval:** thread-walk is the default retrieval strategy because `thread_id` already groups a conversation and keeps evidence local to the relevant context.
- **Reversible vs irreversible:** `send` and `delete` are treated as irreversible; `draft`, `label`, `archive`, and `defer` are reversible and can be executed without a live approval gate.
- **Where the gate sits:** the approval check sits before irreversible actions, so downstream drafting or routing may happen but cannot trigger a send/delete without a valid gate decision.
- **Preferences:** the system persists user preferences such as `do_not_accept_meetings_before` and `always_cc`, then reuses them across runs.

## Capability summary

| id | name | tier | one-line claim |
|----|------|------|----------------|
| input | pre-processing and tagging | A | Process inbox and extract the actionable group for each message |
| routing | Determinsitc routing | B | Route each message into the correct disposition pathway |
| gated-action | Gated action execution | C | Execute or dry-run actions only after policy checks are passed |
| dry-run | Dry-run pipeline | C | Run the pipeline without committing irreversible actions |
| dashboard | Execute the whole pipeline | C | Build the dashboard summary of processed messages |
| C1 | Unread mail from a sender | A | List unread mail from a specific sender |
| C2 | Unreplied emails | B | Find unanswered sent messages and prepare a chase |
| C3 | Commitments and deadline extraction | C | Extract concrete commitments and deadline items from a thread |

## Capability details

### input — pre-processing and tagging
- **Tier:** A
- **Claim:** Process inbox and extracts message to tag for the actionable group.
- **Command:** `python InboxHero.py --input "inbox.json"`
- **Observable:** Groups messages into the categories `reply`, `archive`, `defer`, `delegate`, and `escalate`.
- **Evidence:** `output.json`

### routing — Determinsitc routing
- **Tier:** B
- **Claim:** Reads a thread and extracts the routing action that best matches the message context.
- **Command:** `python InboxHero.py --routing "inbox.json"`
- **Observable:** Produces the appropriate disposition for each message.
- **Evidence:** `routing.json`

### gated-action — Gated action execution
- **Tier:** C
- **Claim:** Executes actions only after dry-run and approval checks have been completed.
- **Command:** `python InboxHero.py --gated-action "inbox.json"`
- **Observable:** Logs each message action in the trace and writes the result to the outbox directory.
- **Evidence:** Writes action decisions into the outbox directory and trace output.

### dry-run — Dry-run pipeline
- **Tier:** C
- **Claim:** Runs the processing pipeline without committing irreversible actions, preserving safety while still evaluating effects.
- **Command:** `python InboxHero.py --dry-run "inbox.json"`
- **Observable:** Evaluates the full message flow without sending or deleting anything.
- **Evidence:** Preview and routing output from the dry-run path.

### dashboard — Execute the whole pipeline
- **Tier:** C
- **Claim:** Generates the dashboard to summarize processed message outcomes and routing results.
- **Command:** `python InboxHero.py --dashboard "dashboard.html"`
- **Observable:** Executes the full InboxHero pipeline and produces the dashboard view for processed messages.
- **Evidence:** `decision_log.jsonl`

### C1 — Unread mail from a sender
- **Tier:** A
- **Claim:** Lists unread mail from a specific sender so the user can focus on incoming action items.
- **Command:** `python InboxHero.py --cap "AC1"`
- **Observable:** Returns only unread mail from the selected sender and filters out read messages or other senders.
- **Evidence:** List of unread messages from the given sender.

### C2 — Unreplied emails
- **Tier:** B
- **Claim:** Finds messages sent by the user that have gone unanswered beyond the requested wait period and drafts a follow-up.
- **Command:** `python InboxHero.py --cap "BC1"`
- **Observable:** Surfaces stale emails with waiting time and the corresponding follow-up action.
- **Evidence:** Output listing the waiting period for each unanswered message.

### C3 — Commitments and deadline extraction
- **Tier:** C
- **Claim:** Extracts concrete commitments and deadlines from a thread and prepares an action-oriented follow-up subject.
- **Command:** `python InboxHero.py --cap "CC1"`
- **Observable:** Prints the commitment list for `sam@paperjet.io` and generates a subject line based on the thread context.
- **Evidence:** Commitment list and generated subject derived from thread messages.

---

This file is the human-readable version of the project’s machine-readable capability definition. It reflects the current implementation in [capabilities.json](capabilities.json).
