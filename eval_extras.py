#!/usr/bin/env python3
"""
The parts of my five criteria that `run_eval.py` can't check by itself.
← UNIT 8, MILESTONE 3

    python app.py                                         # one terminal
    python run_eval.py --label before                     # criteria 1, 2, 3, 5
    python eval_extras.py --label before --report results/run_<stamp>_before.md

What this adds, three trials each:

  Criterion 4 — the appeal path. Submits 5 texts, appeals each, and checks:
      the appeal response is 200 with status under_review; GET /log has exactly
      one new appeal entry per content_id with the reasoning verbatim, after
      the original decision. Then appeals a made-up id and checks for a 404
      and no new under_review entry.

  Criterion 5 — the half of bad input that isn't a /submit status code: a
      JSON body that's a list (scenarios.py bodies must be dicts), that every
      refusal wrote a `rejected` log entry, that no decision was logged, and
      that /ping still answers afterwards.

  Criteria 1–3 — reads the run_eval report given with --report and counts,
      per trial: human texts labelled AI (C1), mean(AI) − mean(human) combined
      score (C2), and which labels appeared (C3).

Writes results/extras_<stamp>_<label>.md.
"""

import argparse
import datetime as dt
import json
import re
import statistics
import sys
import uuid

import requests

import audit
import config
import scenarios

URL = f"http://{config.HOST}:{config.PORT}"

APPEAL_TEXTS = [
    scenarios.HUMAN_TEN[0], scenarios.HUMAN_TEN[3], scenarios.HUMAN_FIVE[2],
    scenarios.AI_FIVE[1], scenarios.COVERAGE_NINE[8],
]


def trial_appeals(trial: int, run_tag: str) -> dict:
    checks = []
    for i, text in enumerate(APPEAL_TEXTS, 1):
        creator = f"eval_appeal_{run_tag}_t{trial}_{i}"
        sub = requests.post(f"{URL}/submit", json={"text": text, "creator_id": creator}, timeout=90)
        content_id = sub.json().get("content_id")
        reasoning = f"I wrote this myself ({creator}). Drafts available on request."
        app = requests.post(f"{URL}/appeal", json={"content_id": content_id, "reasoning": reasoning}, timeout=30)
        body = app.json()

        entries = audit.entries_for(content_id)
        decisions = [n for n, e in enumerate(entries) if e.get("status") == "decided"]
        appeals = [n for n, e in enumerate(entries) if e.get("event") == "appeal"]
        ok = (
            app.status_code == 200
            and body.get("status") == "under_review"
            and len(appeals) == 1
            and entries[appeals[0]].get("reasoning") == reasoning
            and len(decisions) == 1
            and decisions[0] < appeals[0]
        )
        checks.append({"content_id": content_id, "submit_status": sub.status_code,
                       "appeal_status": app.status_code, "appeal_body": body,
                       "appeal_entries": len(appeals), "decision_before_appeal": bool(decisions and appeals and decisions[0] < appeals[0]),
                       "reasoning_verbatim": bool(appeals) and entries[appeals[0]].get("reasoning") == reasoning,
                       "pass": ok})

    fake = f"fake-{uuid.uuid4()}"
    before = len(audit.read_entries())
    bad = requests.post(f"{URL}/appeal", json={"content_id": fake, "reasoning": "typo test"}, timeout=30)
    added = [e for e in audit.read_entries()[before:] if e.get("content_id") == fake]
    unknown_ok = bad.status_code == 404 and not added

    passed = sum(c["pass"] for c in checks)
    return {"appeals_passed": passed, "of": len(checks), "unknown_id_status": bad.status_code,
            "unknown_id_entries_added": len(added), "unknown_id_ok": unknown_ok,
            "met": passed == len(checks) and unknown_ok, "detail": checks}


def trial_bad_input(trial: int, run_tag: str) -> dict:
    # Same bodies as scenarios.BAD_BODIES, but with their own creator_ids so
    # these requests never share a rate-limit bucket with run_eval's — a 429
    # here would be a 4xx for the wrong reason.
    bodies = [{**b, "creator_id": f"{b['creator_id']}_x{run_tag}_t{trial}"} for b in scenarios.BAD_BODIES]
    bodies.append(["this", "is", "a", "list"])
    before = len(audit.read_entries())
    results = []
    for body in bodies:
        r = requests.post(f"{URL}/submit", json=body, timeout=90)
        try:
            payload = r.json()
        except ValueError:
            payload = None
        results.append({"sent": json.dumps(body)[:60], "status": r.status_code,
                        "error": (payload or {}).get("error") if isinstance(payload, dict) else None})
    new = audit.read_entries()[before:]
    rejected = sum(1 for e in new if e.get("status") == "rejected")
    decided = sum(1 for e in new if e.get("status") == "decided")
    ping = requests.post(f"{URL}/ping", json={"message": "still alive?"}, timeout=10)
    four_xx = sum(1 for r in results if 400 <= r["status"] < 500 and r["error"])
    fives = sum(1 for r in results if r["status"] >= 500)
    met = four_xx == len(bodies) and fives == 0 and decided == 0 and rejected == len(bodies) and ping.ok
    return {"four_xx_with_error": four_xx, "of": len(bodies), "five_hundreds": fives,
            "rejected_logged": rejected, "decisions_logged": decided, "ping_ok": ping.ok,
            "met": met, "detail": results}


def summarize_report(path: str) -> dict:
    """Per-trial numbers for criteria 1–3 from a run_eval report."""
    text = open(path, encoding="utf-8").read()
    sections = re.split(r"^### ", text, flags=re.M)[1:]
    data = {}
    for section in sections:
        name = section.splitlines()[0].strip()
        trials = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", section, flags=re.S)]
        data[name] = trials

    out = {}
    c1 = data.get("C1 human writing", [])
    out["C1 human labelled AI"] = [sum(r.get("guess") == "ai" for r in t) for t in c1]
    out["C1 max human score"] = [max(r.get("confidence") or 0 for r in t) for t in c1]
    ai, hu = data.get("C2 spread AI", []), data.get("C2 spread human", [])
    out["C2 gap"] = [round(statistics.mean(r["confidence"] for r in a) - statistics.mean(r["confidence"] for r in h), 3)
                     for a, h in zip(ai, hu)]
    out["C2 means (ai, human)"] = [(round(statistics.mean(r["confidence"] for r in a), 3),
                                    round(statistics.mean(r["confidence"] for r in h), 3)) for a, h in zip(ai, hu)]
    c3 = data.get("C3 label coverage", [])
    out["C3 labels seen"] = [sorted({r.get("guess") for r in t}) for t in c3]
    c5 = data.get("C5 bad input", [])
    out["C5 4xx (run_eval bodies)"] = [sum(1 for r in t if r.get("status") and 400 <= r["status"] < 500) for t in c5]
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--report", help="the run_eval results file to summarise")
    args = parser.parse_args()

    try:
        requests.get(f"{URL}/health", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        sys.exit(f"Nothing answering at {URL}. Start it: python app.py")

    run_tag = dt.datetime.now().strftime("%H%M%S")
    c4 = [trial_appeals(t, run_tag) for t in range(1, args.trials + 1)]
    c5 = [trial_bad_input(t, run_tag) for t in range(1, args.trials + 1)]
    summary = summarize_report(args.report) if args.report else {}

    lines = [f"# Eval extras{f' — {args.label}' if args.label else ''}", "",
             "- Produced by: `eval_extras.py::main`",
             f"- {args.trials} trials · {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
             f"- Criteria 1–3 summarised from: `{args.report}`" if args.report else "", "",
             "## Per-trial numbers", ""]
    for key, values in summary.items():
        lines.append(f"- **{key}:** {values}")
    lines.append(f"- **C4 appeals passed:** {[f'{r['appeals_passed']}/{r['of']}' for r in c4]}"
                 f" · unknown id → {[r['unknown_id_status'] for r in c4]}"
                 f" (entries added {[r['unknown_id_entries_added'] for r in c4]})")
    lines.append(f"- **C5 4xx with error field:** {[f'{r['four_xx_with_error']}/{r['of']}' for r in c5]}"
                 f" · 500s {[r['five_hundreds'] for r in c5]} · rejected logged {[r['rejected_logged'] for r in c5]}"
                 f" · decisions logged {[r['decisions_logged'] for r in c5]} · /ping ok {[r['ping_ok'] for r in c5]}")
    lines += ["", "## Criterion 4 — raw", "", "```json", json.dumps(c4, indent=2, ensure_ascii=False), "```", "",
              "## Criterion 5 — raw", "", "```json", json.dumps(c5, indent=2, ensure_ascii=False), "```", ""]

    config.RESULTS_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    path = config.RESULTS_DIR / f"extras_{stamp}{'_' + args.label if args.label else ''}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:12 + len(summary)]))
    print(f"\nWrote {path.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
