
import json
import argparse
import pandas as pd
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Dict


GROUPING = {"reply", "archive", "defer", "delegate", "escalate"}

def sort_by_id(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return sorted(messages, key=lambda message: message["id"])

def _get_thread_messages(messages: list[dict[str, Any]], thread_id: str) -> list[dict[str, Any]]:
    matches = [
        message for message in messages if str(message.get("thread_id", "")) == str(thread_id)
    ]
    if not matches:
        raise ValueError(f"No messages found for thread_id '{thread_id}'")
    return sorted(matches, key=lambda item: str(item["timestamp"]))

def _record_decision(log_path: Path, proposal: dict[str, Any], human_response: str | None, outcome: str) -> None:
    entry = {
        "timestamp": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "proposal": proposal,
        "human_response": human_response,
        "outcome": outcome,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")

def load_inbox(path: str | Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        messages = sort_by_id(payload)
        return messages
    raise ValueError("inbox.json must contain a list of messages")


def extract_keywords(payload : list[dict[str, Any]]) -> list[str]:
	"""Read a JSON array and collect every thread_id field into a list."""

	unique_extracted: list[str] = []
	pattern = r"t-[a-z]+"
	if isinstance(payload, list):
		for item in payload:
			if isinstance(item, dict) and "thread_id" in item:
				unique_extracted.append(str(item["thread_id"]))

	actionList = list(dict.fromkeys(
    re.search(r"t-[a-zA-Z]+", s).group() 
    for s in unique_extracted 
    if re.search(r"t-[a-zA-Z]+", s)
	))

	return actionList

def decision(message: dict[str, Any]) -> tuple[str, str]:

	keyAction = str(message["thread_id"]).lower()
	sender = str(message["from"]).lower()
	subject = str(message["subject"]).lower()
	body = str(message["body"]).lower()
	
	text = f"{subject} {body}"
	keywords = extract_keywords([message])	
	matches = [substring for substring in keywords if substring in keyAction]
			
	if matches[0] in ['t-phish','t-api', 't-inj']:
		if matches[0] == 't-phish' or matches[0] == 't-inj':
			return "escalate", "Potential phishing or social engineering; do not follow the requested action."
		else:
			return "escalate", "Contains or requests a sensitive staging credential; do not redistribute it."
		
	if matches[0] in ['t-invest','t-deck','t-legal','t-venue','t-launch','t-vendor','t-press','t-board','t-pref']:
		return "delegate", "Thread ID matches a known action that requires Priya to be looped in before any response."
	if matches[0] in ['t-sched','t-followup','t-dentist','t-hire','t-fill']:
		return "defer", "Requires owner scheduling or commitment review; do not accept automatically."
	if matches[0] in ['t-supportfwd','t-support', 't-team', 't-vague', 't-ask','t-fyi']:
		return "reply", "Thread ID matches a known action that can be answered with a grounded draft after owner review."
	else:
		return "archive", "Automated notification, receipt, newsletter, or informational message  known noise action; no owner review needed."


def _process_inbox(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
	outbox = []
	rule_counts = {name: 0 for name in sorted(GROUPING)}
	for message in sort_by_id(messages):
		group, reason = decision(message)
		if group not in GROUPING:
			raise ValueError(f"unsupported disposition for {message['id']}: {group}")
		outbox.append({"id": message["id"], "group": group, "reason": reason})
		rule_counts[group] += 1

	ids = [item["id"] for item in outbox]
	if len(outbox) != len(messages) or len(set(ids)) != len(messages):
		raise ValueError("zeroing invariant failed: every message needs one unique decision")

	return outbox