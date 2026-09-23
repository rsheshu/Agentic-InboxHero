from __future__ import annotations

import os,json,sys,re,argparse
import pandas as pd
from typing import TYPE_CHECKING, Any, Dict
from dataclasses import dataclass, field ,asdict
from pathlib import Path

from crewai import Agent, Crew, LLM, Process, Task
from rich.console import Console
from rich.markdown import Markdown

from tabulate import tabulate
from utility import _get_thread_messages, _record_decision,extract_keywords,decision ,_process_inbox,sort_by_id,load_inbox,GROUPING
from config import get_llm

llm = get_llm()


DEFAULT_PREFERENCES = {
    "do_not_accept_meetings_before": "11:00",
    "always_cc": ["priya@paperjet.io"],
    "preserve_preferences_across_restarts": True,
}



@dataclass
class TaggedMessage:
    id: str
    thread_id: str
    sender: str
    recipient: str
    subject: str
    timestamp: str
    unread: bool
    body: str
    tags: list[str] = field(default_factory=list)
    rule_route: str = "unknown"
    disposition: str = "pending"
    reason: str = ""
    action: str = "dry_run"


@dataclass
class OutputBundle:
    outbox: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    dashboard: dict[str, Any]


def persist_preferences(path: str | Path, preferences: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(preferences, handle, indent=2)

def load_preferences(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.exists():
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            merged = DEFAULT_PREFERENCES.copy()
            merged.update(data)
            return merged
    return DEFAULT_PREFERENCES.copy()

def ingest_and_tag(messages: list[dict[str, Any]], outbox: list[dict[str, Any]]) -> list[TaggedMessage]:
    tagged: list[TaggedMessage] = []

    for item,routing in zip(messages, outbox):
        keyAction = str(item["thread_id"]).lower()
        body = (item.get("body") or "").strip()
        subject = (item.get("subject") or "").lower()
        full_text = f"{subject} {body}".lower()
        tags: list[str] = []
        tags.append(routing["group"])
        tagged.append(
            TaggedMessage(
                id=str(item.get("id", "unknown")),
                thread_id=str(item.get("thread_id", "unknown")),
                sender=str(item.get("from", "")),
                recipient=str(item.get("to", "")),
                subject=str(item.get("subject", "")),
                timestamp=str(item.get("timestamp", "")),
                unread=bool(item.get("unread", False)),
                body=body,
                tags=tags,
            )
        )
    return tagged

def rule_router(messages: list[TaggedMessage]) -> list[TaggedMessage]:
    for message in messages:
        body = f"{message.subject} {message.body}".lower()
        
        if "reply" in message.tags:
            message.rule_route = "reply"
            message.disposition = "route to draft email"
            message.reason = "Operational incident requiring context review."

            continue
        if "archive" in message.tags:
            message.rule_route = "archive"
            message.disposition = "no model call"
            message.reason = "Low-value notification noise."
            message.action = "ignore"            
            continue
        if "defer" in message.tags:
            message.rule_route = "defer"
            message.disposition = "rule: no model call"
            message.reason = "Persisted user preference; no LLM inference needed."
            message.action = "dry_run"            
            continue
        if "delegate" in message.tags:
            message.rule_route = "delegate"
            message.disposition = "route to draft email"
            message.reason = "Message requires delegation to appropriate team."
            continue
        if "escalate" in message.tags:
            message.rule_route = "escalate"
            message.disposition = "route to draft email"
            message.reason = "Message requires escalation to management."
            continue
        message.rule_route = "general"
        message.disposition = "route to draft email"
        message.reason = "General actionable message requiring triage."
    return messages

def normalize_agent_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None

def capability(prompt: str, expected_output: str = "Return a JSON payload only.", agent_role: str = "inbox_hero_agent") -> Any:
    """Run a natural-language inbox capability and return the payload as structured JSON when possible."""
    messages = load_inbox("inbox.json")
    prompt = prompt +  f"Messages:\n{json.dumps(messages, ensure_ascii=False, indent=2)}"
    crew = build_crew()
    if crew is None:
        return {"error": "No capable crew available."}

    try:
        response = run_agent_task(crew, agent_role, prompt, expected_output)
        payload = _safe_json_loads(response)
        if payload is not None:
            return payload
        return {"raw_response": response}
    except Exception:
        return {"error": "Capability execution failed.", "prompt": prompt}

def unread_from_sender(messages: list[dict[str, Any]] | None = None, sender: str="") -> list[dict[str, Any]]:
    """List all unread mail from a Sender"""
    source = messages if messages is not None else load_inbox("inbox.json")
    return [
        item for item in source
        if str(item.get("from", "")).lower() == sender
        and bool(item.get("unread", False))
    ]

def extract_commitments_and_deadlines(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract concrete commitments and deadlines from message threads."""
    if not messages:
        return []

    prompt = (
        "Review the thread messages and extract every concrete commitment and deadline for sam@paperjet.io into a JSON list. "
        "Each item must include: message_id, owner, commitment, deadline. "
        "Use only facts stated in the messages.\n\n"
        f"Messages:\n{json.dumps(messages, ensure_ascii=False, indent=2)}"
    )
    payload = capability(prompt, "Return a JSON list of objects with keys: message_id, owner, commitment, deadline and action."
                                  "Return JSON with keys: thread_id, summary, reply,subject as per preferences if any for the message which is disposition to route to draft email")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("items") if isinstance(payload.get("items"), list) else payload.get("commitments")
        if isinstance(items, list):
            return items

def summarize_thread_to_open_question(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a thread to its status and the decisive open question."""
    if not messages:
        return {"thread_id": None, "summary": "No messages available.", "open_question": "No open question."}

    prompt = (
        "Summarise this thread down to a crisp status summary and the single open question still blocking progress. "
        "Return JSON with keys: summary, open_question, thread_id. "
        "Use only what appears in the messages.\n\n"
        f"Messages:\n{json.dumps(messages, ensure_ascii=False, indent=2)}"
    )
    payload = capability(prompt, "Return JSON with keys: thread_id, summary, open_question.")
    if isinstance(payload, dict):
        if not payload.get("open_question"):
            payload["open_question"] = "No open question identified."
        return payload

    ordered = sorted(messages, key=lambda item: str(item.get("timestamp", "")))
    latest = ordered[-1]
    thread_id = str(latest.get("thread_id", ""))
    subject = str(latest.get("subject") or "")
    bodies = [str(item.get("body") or "") for item in ordered]
    summary = (
        f"Thread {thread_id or 'unknown'} is about {subject or 'ongoing follow-up'}. "
        f"It covers the current status and the immediate decision or approval needed."
    )

    question_candidates = []
    for body in reversed(bodies):
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            if "?" in sentence:
                question_candidates.append(sentence.strip())
    open_question = question_candidates[-1] if question_candidates else (
        "What is the next decision needed to unblock the thread?"
    )

    if not any(phrase in open_question.lower() for phrase in ["can", "could", "should", "will", "need", "approve", "confirm", "when", "what", "who", "where", "why"]):
        open_question = f"What is the next step needed to resolve the outstanding issue in thread {thread_id}?"

    return {
        "thread_id": thread_id,
        "summary": summary,
        "open_question": open_question,
    }

def find_unanswered_sent_messages(messages: list[dict[str, Any]], sender: str | None = None, waiting_days: int = 3) -> list[dict[str, Any]]:
    """Find messages that were sent and never answered after the requested wait period and draft a chase for each."""
    if not messages:
        return []

    candidates = [
        message for message in messages
        if sender is None or str(message.get("from", "")).lower() == str(sender).lower()
    ]
    thread_map: dict[str, list[dict[str, Any]]] = {}
    for item in messages:
        thread_map.setdefault(str(item.get("thread_id", "")), []).append(item)

    results: list[dict[str, Any]] = []
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    for message in candidates:
        thread_id = str(message.get("thread_id", ""))
        thread = thread_map.get(thread_id, [])
        sent_at = message.get("timestamp")
        if not sent_at:
            continue

        has_reply = False
        for candidate in thread:
            if candidate is message:
                continue
            if str(candidate.get("from", "")).lower() == str(message.get("from", "")).lower():
                continue
            candidate_ts = candidate.get("timestamp")
            if candidate_ts and str(candidate_ts) > str(sent_at):
                has_reply = True
                break

        if has_reply:
            continue

        try:
            sent_dt = __import__("datetime").datetime.fromisoformat(str(sent_at).replace("Z", "+00:00"))
            days_waiting = max(0, (now - sent_dt.astimezone(__import__("datetime").timezone.utc)).days)
        except ValueError:
            days_waiting = 0

        if days_waiting < waiting_days:
            continue

        results.append({
            "message_id": str(message.get("id", "unknown")),
            "thread_id": thread_id,
            "days_waiting": days_waiting,
            "chase": (
                f"Follow up on message {message.get('id', 'unknown')} to confirm the next step. "
                f"This thread has been waiting {days_waiting} days without a reply."
            ),
        })

    return sorted(results, key=lambda item: (item.get("days_waiting", 0), item.get("message_id", "")), reverse=True)

def capability_execution(category: str="A" , prompt: str="", expected_output: str = "Return a JSON payload only.",agent_role: str = "inbox_hero_agent") -> Any:
    responses: list[dict[str, Any]] = []
    messages = load_inbox("inbox.json")
    if category  == "A" :
        print("\n One lookup, one output")
        responses = unread_from_sender(messages,"priya@paperjet.io")
        print(json.dumps(responses, indent=2, ensure_ascii=False))
        return responses
    if category == "B" :
        print("\n Multi-step with reasoning")
        responses = find_unanswered_sent_messages(messages)
        print(json.dumps(responses, indent=2, ensure_ascii=False))
        return responses
    if category == "C" :
        print("\n Agentic capability")
        responses = extract_commitments_and_deadlines(messages)
        print(json.dumps(responses, indent=2, ensure_ascii=False))
        return   responses 

def run_agent_task(crew: Crew, agent_role: str, prompt: str, expected_output: str) -> str:
    agent_map = {
        normalize_agent_name(agent.role): agent
        for agent in getattr(crew, "agents", [])
        if getattr(agent, "role", None)
    }
    key = normalize_agent_name(agent_role)
    if key not in agent_map:
        raise ValueError(f"agent {agent_role} not found in crew")

    task = Task(
        description=prompt,
        agent=agent_map[key],
        expected_output=expected_output,
    )
    crew.tasks = [task]
    return str(crew.kickoff()).strip()

def build_crew() -> Crew | None:
    if Agent is None or Crew is None or Task is None:
        return None

    llm = LLM(model="ollama/llama3.2", base_url="http://localhost:11434")

    drafting_agent = Agent(
        role="drafting_agent",
        goal="Draft a concise and safe response or follow-up based on the triage outcome.",
        backstory="You create actionable drafts that cite the relevant source items and respect policy constraints.",
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    action_agent = Agent(
        role="action_agent",
        goal="Approve, dry-run, or refuse each decision according to policy and saved preferences.",
        backstory="You act as the final gate before an email is routed into an outbox or ignored.",
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    inbox_hero_agent = Agent(
        role="inbox_hero_agent",
        goal="Handle inbox capabilities through natural language, including extracting commitments and summarising long threads to the decisive open question.",
        backstory="You are the inbox hero. Transform thread context into structured commitments and distill long email threads to the one question that matters next.",
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    return Crew(
        agents=[drafting_agent, action_agent, inbox_hero_agent],
        tasks=[],
        process=Process.sequential,
    )

def retrieve_and_draft(inbox: list[dict[str, Any]], messages: list[TaggedMessage], preferences: dict[str, Any]) -> list[TaggedMessage]:
    crew = build_crew()

    for message in messages:
        message.thread_id
        thread_id = str(message.thread_id)
        if message.action == "refuse":
            message.disposition = "archive"
            continue

        if "meeting" in f"{message.subject} {message.body}".lower() and "before 11" in json.dumps(preferences):
            message.action = "dry_run"
            message.reason = f"Override applied: {preferences.get('do_not_accept_meetings_before')} cutoff."

        if "term sheet" in f"{message.subject} {message.body}".lower() and "always_cc" in json.dumps(preferences):
            message.action = "dry_run"
            message.reason = f"CC to be: {preferences.get('always_cc')} mailed."            

        if crew is not None:
            thread_messages = _get_thread_messages(inbox,thread_id)
            latest = thread_messages[-1]
            earlier = thread_messages[:-1]        
            earlier_context = "\n\n".join(
                (
                    f"Message ID: {item.get('id', 'unknown')}\n"
                    f"From: {item.get('from', '')}\n"
                    f"To: {item.get('to', '')}\n"
                    f"Subject: {item.get('subject', '')}\n"
                    f"Body: {item.get('body', '')}\n"
                )
                for item in earlier
            )             
            if message.disposition == "route to draft email":            
                draft_text = run_agent_task(
                    crew,
                    "drafting_agent",
                    (
                        "Write a brief email reply to the latest message in this thread. "
                        "Use the earlier messages in this same thread as evidence and reference the details already agreed in the thread. "
                        "Do not invent facts, do not disclose secrets, and do not resend sensitive credentials over email. "
                        "If credentials are involved, say they must be delivered through the approved secure channel. "
                        "The latest message is:\n"
                        f"Message ID: {latest.get('id', 'unknown')}\n"
                        f"From: {latest.get('from', '')}\n"
                        f"To: {latest.get('to', '')}\n"
                        f"Subject: {latest.get('subject', '')}\n"
                        f"Body: {latest.get('body', '')}\n\n"
                        "Earlier thread context:\n"
                        f"{earlier_context}"
                    ),
                    (
                        "Return JSON only with keys: thread_id, message_id, reply_to, body, evidence_message_ids." 
                        "The body should be plain email text with salutation and closing." 
                    ),
                )
                try:
                    payload = json.loads(draft_text)
                    draft = payload.get("draft") or payload.get("note") or draft_text
                except json.JSONDecodeError:
                    draft = draft_text
                message.reason = f"{message.reason} Draft: {draft}"
                

            if message.rule_route == "escalate":
                message.reason = (
                    f"{message.reason} Recommended next step: confirm worker queue credentials and validate the staging broker URL."
                )
            elif message.rule_route == "delegate":
                message.reason = (
                    f"{message.reason} Recommended next step: obtain approval and route to the finance tool for payment processing."
                )
            elif message.rule_route == "defer":
                message.reason = (
                    f"{message.reason} Preference preserved for future routing: no meetings before {preferences.get('do_not_accept_meetings_before')}."
                )
                
        return messages

def action_gate(messages: list[TaggedMessage], preferences: dict[str, Any]) -> list[TaggedMessage]:
    crew = build_crew()
    for message in messages:
        if message.action == "refuse":
            continue
        if crew is not None and message.rule_route != "archive" and message.rule_route != "defer":
            action_text = run_agent_task(
                crew,
                "action_agent",
                (
                    "Review the message decision and decide whether to approve, dry-run, or refuse.\n"
                    f"Thread: {message.thread_id}\n"
                    f"Route: {message.rule_route}\n"
                    f"Disposition: {message.disposition}\n"
                    f"Reason: {message.reason}\n"
                ),
                "JSON with fields: action, reason",
            )
            try:
                payload = json.loads(action_text)
                candidate_action = str(payload.get("action", message.action)).lower()
                if candidate_action in {"approve", "dry_run", "refuse", "ignore", "store_preference"}:
                    message.action = candidate_action
                    if payload.get("reason"):
                        message.reason = payload["reason"]
                write_outbox_messages("inbox.json","outbox",message,True)                
            except json.JSONDecodeError:
                pass

        if message.rule_route == "archive":
            message.action = "ignore"
            continue
        if message.rule_route == "defer":
            message.action = "store_preference"
            continue
        if message.rule_route == "delegate":
            message.action = "approve"
            continue
        if preferences.get("do_not_accept_meetings_before") and "meeting" in (message.subject + " " + message.body).lower():
            message.action = "dry_run"
            message.reason = "Meeting request respects the saved user preference."
    return messages

def build_outputs(messages: list[TaggedMessage]) -> OutputBundle:
    outbox: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for message in messages:
        outbox.append(
            {
                "id": message.id,
                "thread_id": message.thread_id,
                "rule_route": message.rule_route,
                "disposition": message.disposition,
                "action": message.action,
                "reason": message.reason,
            }
        )
        trace.append(
            {
                "message_id": message.id,
                "tags": message.tags,
                "route": message.rule_route,
                "decision": message.disposition,
                "summary": message.reason,
            }
        )
        counts[message.rule_route] = counts.get(message.rule_route, 0) + 1

    dashboard = {
        "total_messages": len(messages),
        "routes": counts,
        "approved_actions": sum(1 for item in outbox if item["action"] == "approve"),
        "ignored_messages": sum(1 for item in outbox if item["action"] == "ignore"),
        "refused_messages": sum(1 for item in outbox if item["action"] == "refuse"),
    }
    return OutputBundle(outbox=outbox, trace=trace, dashboard=dashboard)

def write_outbox_messages(
    inbox_file_path: str | Path,
    outbox_dir: str | Path,
    draft: TaggedMessage,
    dry_run: bool = True,
    approvals: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write one draft file per message to the outbox directory and log gated actions.

    Design: reversible actions include save/rewrite/archive/delete_draft because they are
    non-destructive local operations that can be undone by keeping a local backup or by
    restoring the draft from the log. Irreversible actions include send_message because a
    sent email cannot be unsent; therefore every send must be approved or dry-run only.
    """
    inbox_file_path = Path(inbox_file_path)
    outbox_dir = Path(outbox_dir)
    outbox_dir.mkdir(parents=True, exist_ok=True)

    messages = load_inbox(inbox_file_path)
    approvals = approvals or {}

    reversible_actions = [
        "save_draft",
        "rewrite_draft",
        "archive_draft",
        "delete_draft",
    ]
    irreversible_actions = ["send_message"]
    design_notes = (
        "deleting_is_reversible: Deleting a draft is reversible in this design because the system keeps the draft payload "
        "in the outbox history and decision log until a human explicitly approves permanent removal. "
        "A sent message is irreversible because it has already left the local system and cannot be unsent."
    )

    manifest = {
        "outbox_directory": str(outbox_dir),
        "dry_run": dry_run,
        "reversible_actions": reversible_actions,
        "irreversible_actions": irreversible_actions,
        "design_notes": design_notes,
        "writes": [],
        "approval_required_for": ["send_message"],
    }
    log_path = outbox_dir / "decision_log.jsonl"
    if not log_path.exists():
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write("")


    thread_id = draft.thread_id
    message_id = draft.id
    file_path = outbox_dir / f"{message_id}.json"
    record = {
        "message_id": message_id,
        "thread_id": thread_id,
        "reply_to": draft.sender,
        "draft_path": str(file_path),
        "body": draft.body,
        "evidence_message_ids": draft.reason
    }
    manifest["writes"].append({
        "message_id": message_id,
        "path": str(file_path),
        "action": "save_draft",

    })

    proposal = {
        "action": "send_message",
        "message_id": message_id,
        "target": draft.sender,
        "thread_id": thread_id,
        "body_preview": (draft.body, "" or "")[:200],
        "path": str(file_path),
    }
    human_response = approvals.get(message_id)
    if dry_run:
        outcome = "dry_run_only"
        _record_decision(log_path, proposal, "dry_run=true", outcome)
        record["status"] = "dry_run_only"
    else:
        if not human_response:
            raise PermissionError(
                f"Irreversible action send_message for {message_id} requires explicit human approval or dry_run mode."
            )
        outcome = f"approved:{human_response}"
        _record_decision(log_path, proposal, human_response, outcome)
        record["status"] = "approved_and_written"

    file_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    manifest_path = outbox_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return manifest

def run_pipeline(inbox_path: str | Path, preferences_path: str | Path | None = None) -> dict[str, Any]:
    inbox_file = Path(inbox_path)
    prefs_file = Path(preferences_path) if preferences_path is not None else inbox_file.parent / "state" / "preferences.json"
    preferences = load_preferences(prefs_file)
    outbox = _process_inbox(load_inbox(inbox_file))  # for manifest counts, even if not used
    print("Processed the inbox message")
    routed = rule_router(ingest_and_tag(load_inbox(inbox_file),outbox))
    gated = action_gate(retrieve_and_draft(load_inbox(inbox_file),routed, preferences), preferences)
    if preferences.get("preserve_preferences_across_restarts"):
        persist_preferences(prefs_file, {
            "do_not_accept_meetings_before": "11:00",
            "always_cc": ["priya@paperjet.io"],
            "preserve_preferences_across_restarts": True,
        })

    outputs = build_outputs(gated)
    return {
        "preferences": preferences,
        "outbox": outputs.outbox,
        "trace": outputs.trace,
        "dashboard": outputs.dashboard,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Assign one disposition to every inbox message or run the generic inbox capability directly.")
    parser.add_argument("--input", type=Path, default=Path("inbox.json"))
    parser.add_argument("--routing", type=Path, default=Path("inbox.json"))    
    parser.add_argument("--output", type=Path, default=Path("outbox.json"))
    parser.add_argument("--dry-run", type=Path, default=Path("inbox.json"))
    parser.add_argument("--gated-action", type=Path, default=Path("inbox.json"))    
    parser.add_argument("--manifest", type=Path, default=Path("manifest.json"))
    parser.add_argument("--prompt", type=str, help="Natural-language prompt to send to the generic inbox capability agent.")
    parser.add_argument("--expected-output", type=str, default="Return a JSON payload only.", help="Expected JSON shape for the capability response.")
    parser.add_argument("--agent-role", type=str, default="inbox_hero_agent", help="Agent role to use for the generic capability call.")
    parser.add_argument("--cap", type=str, default="AC1", help="To execute the capability AC1 or BC1 or CC1.")
    parser.add_argument("--dashboard", type=Path, default=Path("details.html"))
    args = parser.parse_args()

    if "--input" in sys.argv:
        outbox = _process_inbox(load_inbox(args.input))
        with open("output.json", "w", encoding="utf-8") as f:
            json.dump(outbox, f, indent=4)
        return

    if "--routing" in sys.argv:
        preferences = load_preferences(args.manifest)
        outbox = _process_inbox(load_inbox(args.input))
        routing_messages = rule_router(ingest_and_tag(load_inbox(args.input),outbox))
        with open("routing.json", "w", encoding="utf-8") as f:
            list_json = json.dumps([asdict(m) for m in routing_messages], indent=4)
            print(list_json)            
        return                

    if "--dry-run" in sys.argv:
        preferences = load_preferences(args.manifest)
        outbox = _process_inbox(load_inbox(args.input))
        data = rule_router(ingest_and_tag(load_inbox(args.input),outbox))
        retrieve_and_draft(load_inbox(args.input),data, preferences)

    if "--gated-action" in sys.argv:
        preferences = load_preferences(args.manifest)
        outbox = _process_inbox(load_inbox(args.input))
        routed = rule_router(ingest_and_tag(load_inbox(args.input),outbox))
        gated_message = action_gate(retrieve_and_draft(load_inbox(args.input),routed, preferences), preferences)
        list_json = json.dumps([asdict(m) for m in routing_messages], indent=4)
        print(list_json)            
        return        

    if "--dashboard" in sys.argv:
        
        result = run_pipeline(args.input, args.manifest)
        df = pd.json_normalize(result["dashboard"])
        df.to_html(args.dashboard, index=False)
        return

    if args.cap == "AC1":
        capability_execution("A")
        return

    if args.cap == "BC1":
        capability_execution("B")
        return
        
    if args.cap == "CC1":
        capability_execution("C")
        return
    


if __name__ == "__main__":
    main()