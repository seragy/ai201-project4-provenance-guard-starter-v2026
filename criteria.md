# Acceptance criteria — Provenance Guard

Five criteria that say what "working" means for this service, written in unit 7
**before** you built it.

**All five are yours.** None are given.

An acceptance criterion names a number or something plainly observable. *"The
detector is accurate"* is an opinion — and perfect AI detection isn't possible
anyway, so it's an opinion about something nobody can deliver. *"Of 10 pieces I
wrote myself, at most 1 is labelled high-confidence AI"* is a criterion.

Under each, write a sentence or two on **why that target**. *"I allow at most 1
false positive in 10 because on a writing site a wrong accusation costs more
than a missed detection"* is a real answer.

> Missing your own targets next unit costs you nothing. Setting a target so
> easy you can't miss it does.

---

## Pick numbers you can defend

**Cover at least three of these five areas.** They're prompts, not a form.

| Area | A question it could answer |
|---|---|
| False positives | How often may a human's writing get called AI? |
| Score spread | How far apart should clearly-AI and clearly-human text score? |
| Label coverage | Is every one of your three labels actually reachable? |
| The appeal path | Does an appeal always change status and always get recorded? |
| Bad input | What happens when `text` is missing, empty, or enormous? |

Two things worth knowing before you pick numbers:

- **The expensive mistake is one-sided.** Missing some AI text costs the site a
  little. Accusing a real writer costs that person a lot. A criterion that
  treats both errors as equally bad is describing a system nobody would ship.
- **Unit 8 tests across three trials, and the target has to hold across all
  three.** Your first signal runs a model, so identical input can score
  differently twice. A target of "at most 1 in 10" against trials of 2, 1, 2 is
  a **miss**.

---
## 1. Real human writing is almost never called AI

Of 10 pieces of human-written text (my own paragraphs plus real forum posts
written by people before 2022), **at most 1 is labelled high-confidence AI**, and
that holds in **each of 3 trials** (a trial of 2/10 is a miss).

**Why this target:** On a writing site, accusing a real writer is the expensive
mistake — it ends their relationship with the platform — while missing an AI
submission is a nuisance. I'd rather have zero, but gpt2 perplexity is known to
read plain writing as machine-like, so 0/10 would be a target I'd be guessing
at; 1/10 is the most I'd accept if it were my own work being judged.

---

## 2. Clearly-AI and clearly-human text score far apart

Across 5 clearly AI-generated texts and 5 clearly human-written texts, the
**mean combined score of the AI set is at least 0.30 higher than the mean of the
human set**, in each of 3 trials.

**Why this target:** My labels split the 0–1 range into bands about 0.35–0.40
wide. If the easy cases aren't at least ~0.30 apart on average, they can't sit
in different bands, and the score isn't telling anyone anything. A gap smaller
than that means the score is basically noise around the middle.

---

## 3. Every label is reachable

From a fixed set of 9 coverage inputs (3 I expect to be AI, 3 human, 3
borderline), **each of the three labels — high-confidence human, unsure,
high-confidence AI — is produced at least once**, in each of 3 trials.

**Why this target:** A label nobody can reach is a gap in the ranges, and an
"AI" label that never fires means the threshold is so high the system has
silently stopped detecting anything. Requiring all three every trial also
catches the opposite failure: everything collapsing into "unsure".

---

## 4. Every appeal changes status and is recorded

For **5 out of 5** appeals sent against real content_ids, the response is a 200
with `status: "under_review"`, and `GET /log` shows **exactly one new appeal
entry per appeal** carrying the same content_id and the writer's reasoning
verbatim, with the original decision entry still present above it. An appeal
against a content_id that was never issued returns a 404 and adds no
`under_review` entry.

**Why this target:** The appeal is the only thing between a wrong accusation and
nothing at all, so it has to work every time, not most of the time — 5/5, not
4/5. The 404 half matters because a typo that "succeeds" silently would tell a
writer their appeal is filed when it isn't.

---

## 5. Bad input never crashes the service

For 6 malformed requests — empty text, whitespace-only text, missing `text`,
`text: null`, a 50,000-word text, and a JSON body that is a list instead of an
object — **6 out of 6 return a 4xx status with an `error` field (zero 500s and
zero scored decisions)**, and each one writes a `rejected` entry to the audit
log, in each of 3 trials. `/ping` still answers afterwards.

**Why this target:** A crash on malformed input is one of the most common real
failures, and an enormous input that gets scored anyway ties up the model for
everyone. Logging the rejections matters because an attack that only shows up
as an absence is one I'd never find.

---

<!-- ─────────────────────────────────────────────────────────────────────────
     UNIT 8 — read this before you change anything above.

     If a criterion turns out to be BROKEN rather than merely unmet, you can
     revise it, and that earns credit. But never delete or edit the original
     line. Add the revision underneath, like this:

         ## 2. Uncertain cases land in the unsure band

         The system handles uncertain cases well.

         **Why this target:** ...

         > **Revised in unit 8:** Text I judged borderline scores between
         > 0.4 and 0.6 in at least 4 of 5 cases.
         >
         > **Why revised:** "well" gave me nothing to check. I couldn't
         > reach a verdict from it at all.

     That's a revision because the criterion couldn't be MEASURED.

     Lowering a target because you missed it is not a revision, and it costs
     you the point:

         ✗ "At most 1 of 10 of my own pieces flagged as AI" → "at most 3
            of 10", because 1 of 10 turned out to be hard.

     A number you missed stays where it is, gets diagnosed, and gets a fix
     attempted. That's where the points are.
     ───────────────────────────────────────────────────────────────────────── -->
