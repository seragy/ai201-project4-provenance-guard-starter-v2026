# Provenance Guard

> ### 👋 Start here
>
> **New to this repo? Read [RUNNING.md](RUNNING.md) first.**
>
> Once `python test.py` passes, in one terminal:
>
> ```bash
> python app.py
> ```
>
> and in another:
>
> ```bash
> curl -X POST http://127.0.0.1:5000/ping \
>   -H "Content-Type: application/json" \
>   -d '{"message": "hello"}'
> ```
>
> That's a web service. Something sent it text and it sent something back.
> Everything this unit is filling in the middle.
>
> **The rest of this file is your submission.** Fill it in as you go.

---

<!-- ─────────────────────────────────────────────────────────────────────────
     Unit 7 asks for the first five sections. Unit 8 adds the five below.

     Everything is pasted as TEXT. A pasted curl response gets full credit;
     a picture of your terminal gets none.
     ───────────────────────────────────────────────────────────────────────── -->

<!-- ═══════════════════════ UNIT 7 — THE BUILD ═══════════════════════ -->

## What This Does

Provenance Guard takes a piece of writing and says — honestly, including when it
doesn't know — whether it looks AI-generated, and gives the writer a way to push
back. The path a submission takes (traced before building, in [design.md](design.md)):

1. **The site sends `POST /submit`** with `{"text": ..., "creator_id": ...}`.
2. **The route checks the input** (`app.py::_validate_submission`). Missing,
   null, non-string, empty, whitespace-only, under 5 words, or over 20,000
   characters → a `400` with a plain-English message, and a `rejected` entry in
   the audit log. Nothing gets scored that can't be scored honestly. Valid input
   gets a fresh `content_id` (uuid4).
3. **Signal one** (`detector.py::model_signal`) runs gpt2 locally and turns the
   text's perplexity into a 0–1 score (higher = more predictable = more AI-like).
4. **Signal two** (`stylometry.py::style_signal`) measures the text's shape —
   sentence-length spread, expressive punctuation, vocabulary variety — as a 0–1
   score in the same direction.
5. **The combining rule** (`scoring.py::combine_signals`) turns the two into one
   confidence score: a 60/40 weighted average with a veto that stops either
   signal accusing anyone on its own.
6. **The label mapping** (`scoring.py::score_to_label`) turns the score into a
   guess (`human` / `unsure` / `ai`) and the sentence a reader actually sees.
7. **The audit log** (`audit.py::log_decision` → `logs/audit.jsonl`) records the
   timestamp, content_id, creator_id, guess, both signal scores, the combined
   score, the label and status `decided`, and the JSON goes back to the site.

If the writer disagrees, **`POST /appeal`** with the `content_id` and their
reasoning appends an `under_review` entry next to the original decision (the
original is never overwritten) and confirms to them. An unknown `content_id`
gets a `404`, so a typo can never look like a filed appeal.

---

## Signals and Scoring

### Signal one — the model signal

**What it measures:** How predictable the text is to gpt2 (perplexity), squashed
onto 0–1 with a logistic on log-perplexity (midpoint 45, steepness 1.6 — the
starter's values, which I kept because my calibration set separated cleanly
with them). Lower perplexity → higher AI score.

**Why that might differ between human and AI writing:** A language model writes
by picking likely next words, so its output is text a model finds easy to
predict. People make odder, more specific choices. On my calibration set the 5
clearly-AI paragraphs scored 0.82–0.96 and the 8 human texts 0.09–0.62.

**What it can't see:** Authorship. Predictability isn't who wrote it. Plain
writing — short sentences, common words, a second-language writer — is
predictable and scores machine-like: my plainest real Reddit comment scored
**0.62**, closer to the AI texts than to the formal human one (0.09). And dense
prose with rare words reads as human whoever wrote it. It also only reads the
first 400 tokens.

### Signal two — the style signal

**What it measures:** The shape of the text, without reading a word
(`stylometry.py`). Three measures, each mapped to 0 (human-like) … 1 (AI-like)
before averaging, so none wins by having bigger raw numbers:

| measure | what it is | AI end → human end | weight |
|---|---|---|---|
| `sentence_length_spread` | stdev ÷ mean of words per sentence (a line break also ends a sentence) | 0.15 → 0.80 | 0.4 |
| `punctuation_density` | punctuation marks per 100 words, **excluding** commas and full stops (dashes, brackets, `?`, `!`, quotes, apostrophes, `…`, `/`) | 0 → 8 | 0.4 |
| `type_token_ratio` | moving-average TTR over 40-word windows (so length doesn't decide it) | 0.95 → 0.75 (**flipped**) | 0.2 |

**Why that might differ:** Generated prose marches in even, mid-length sentences
and uses commas and full stops almost exclusively (my AI texts: spread
0.13–0.40, expressive punctuation 0–1.7 per 100 words). People are lumpier:
fragments next to run-ons, brackets, dashes, "lol", contractions (human: spread
0.34–1.04, punctuation mostly 9–11).

*A finding:* the starter's hint is that low vocabulary variety means AI. On my
short texts it ran **the other way** — the AI paragraphs had TTR 0.89–0.92 and
most human ones were lower (0.76–0.89), because people repeat themselves ("Wow…
Wow", "take a bow, take a bow") and models reach for a fresh synonym every
sentence. So I flipped its direction and gave it half the weight of the others;
it's the weakest of the three.

**What it can't see:** Meaning. Anything that changes the shape without the
substance moves it, and it's cheap to do on purpose: I added two dashes, a pair
of brackets and an exclamation mark to an AI paragraph and its style score fell
from 0.78 to **0.45**. A one-sentence text has no spread at all (that measure is
dropped and the others reweighted, rather than scored as "perfectly even").
Short texts give it very little to measure.

### The combining rule

**The rule:**
1. Weighted average: **0.6 × model + 0.4 × style**. Signal one separates my
   calibration set more reliably, so it counts more.
2. **Disagreement veto:** the AI label needs *both* signals to lean AI. If the
   average reaches the AI threshold but either signal is below **0.5**, the
   score is capped at 0.71 (just under the AI threshold), so the item lands in
   "unsure" instead of being accused.
3. No matching veto on the human side, on purpose: being wrong toward "human"
   costs a missed detection; being wrong toward "AI" costs a writer.

**The numbers:** `WEIGHT_MODEL_SIGNAL = 0.6`, `WEIGHT_STYLE_SIGNAL = 0.4`,
`AGREEMENT_FLOOR = 0.5`, `HUMAN_THRESHOLD = 0.40`, `AI_THRESHOLD = 0.72` — all in
`config.py`. Why 0.72: every human text in my set scored 0.25–0.49 and every
clearly-AI text 0.79–0.96, so 0.72 sits ~0.23 above the highest human score,
leaving room for writers plainer than any I tested.

**Where it lives:** `scoring.py::combine_signals` (thresholds → labels in
`scoring.py::score_to_label`).

**Calibration table** (`python calibration.py`, saved in
`notes/m4_calibration_both_signals.txt`):

```
input             expect   model  style combined  guess   spread   ttr punct
----------------------------------------------------------------------------
clearly AI        AI       0.888  0.777    0.844  ai        0.31  0.91  1.72
clearly AI 2      AI       0.913  0.942    0.924  ai        0.19  0.92  0.00
clearly AI 3      AI       0.821  0.894    0.850  ai        0.13  0.92  1.43
clearly AI 4      AI       0.963  0.942    0.955  ai        0.18  0.91  0.00
clearly AI 5      AI       0.849  0.707    0.792  ai        0.40  0.89  1.59
clearly human     human    0.510  0.381    0.458  unsure    0.39  0.88 10.59
clearly human 2   human    0.373  0.078    0.255  human     0.87  0.83 10.94
clearly human 3   human    0.435  0.453    0.443  unsure    1.04  0.89  1.79
clearly human 4   human    0.488  0.085    0.327  human     0.97  0.83 10.94
clearly human 5   human    0.599  0.124    0.409  unsure    1.00  0.87 10.00
plain human       human    0.620  0.299    0.492  unsure    0.76  0.76  2.70
plain human 2     human    0.548  0.244    0.426  unsure    0.46  0.78 11.32
formal human      human    0.089  0.485    0.248  human     0.34  0.97  9.09
edited AI         AI       0.680  0.174    0.478  unsure    0.76  0.88  7.69
edited AI 2       AI       0.561  0.390    0.493  unsure    0.62  0.91  5.66
```

Clearly-AI mean 0.873 vs clearly-human mean 0.378 — a gap of 0.50. No human text
reached the AI label; no AI text reached the human label. Lightly-edited AI and
plain human writing both land in "unsure", which is the honest answer: the
system can't tell them apart there. Human sources are real Reddit comments from
my unit 3 dataset; AI texts were generated by Claude; "edited AI" is AI text I
roughed up by hand.

**A case where my two signals split, and what my rule does with it:** The AI
"climate/AI ethics" paragraph with two dashes, brackets and an exclamation mark
added: **model 0.84 (AI), style 0.45 (human-ish)**. The plain average is 0.68.
Under the old 0.65 threshold that would have been "AI"; the veto caught it
(style < 0.5) and capped it to unsure. At my final 0.72 threshold it's unsure
either way. The opposite split is "edited AI": model 0.68, style 0.17 → 0.48,
unsure. And "formal human": model 0.09, style 0.49 → 0.25, human. In every split
the rule lands on the less accusing side, which is the point.

---

## Label Variants

| Label | Score range | The exact text a reader sees |
|---|---|---|
| high-confidence human | 0.00 ≤ score < 0.40 | We think a person wrote this. Our check found the natural variety we usually see in human writing. |
| unsure | 0.40 ≤ score < 0.72 | We can't tell whether this was written by a person or with help from an AI tool, so we're not making a call either way. That happens a lot with clear, straightforward writing, and it says nothing bad about yours. If you wrote it yourself, you can tell us more and a person will take a look. |
| high-confidence AI | 0.72 ≤ score ≤ 1.00 | Our automated check thinks this looks a lot like AI-generated writing. Checks like ours do get human writing wrong, so this is not a final decision. If you wrote this yourself, you can appeal: a person will review it, and it will show as under review until they do. |

The ranges have no gaps (`scoring.label_ranges()` prints them) and all three were
reached through the live service — see `notes/m5_labels_appeal_badinput.txt`
(0.2551 → human, 0.4917 → unsure, 0.9244 → ai).

**Why I worded the "unsure" one this way:** The person reading it most likely
wrote every word — in my own calibration set, 5 of 8 real human texts landed
here. So it says plainly that we're *not making a call*, names the most common
reason (straightforward writing) as something that's not their fault, and
offers a person rather than a form. My first draft said "Plain, careful writing
often looks like this"; read back from a writer's point of view, that came
across as "so I write like a robot?", so I changed it to say outright that it
"says nothing bad about yours".

---

## Sample Run

**A submission**

```bash
$ curl -X POST http://127.0.0.1:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Climate change is one of the most pressing challenges facing our planet today. Rising global temperatures are leading to more frequent extreme weather events, melting ice caps, and rising sea levels. To address this issue, governments, businesses, and individuals must work together to reduce greenhouse gas emissions.", "creator_id": "sample_writer_01"}'
```

```json
{
    "confidence": 0.9566,
    "content_id": "b1ba0406-40d0-4a80-bd52-9798c0386911",
    "creator_id": "sample_writer_01",
    "guess": "ai",
    "label": "Our automated check thinks this looks a lot like AI-generated writing. Checks like ours do get human writing wrong, so this is not a final decision. If you wrote this yourself, you can appeal: a person will review it, and it will show as under review until they do.",
    "model_score": 0.9591,
    "status": "decided",
    "style_score": 0.9528
}
```

**An appeal**

```bash
$ curl -X POST http://127.0.0.1:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "b1ba0406-40d0-4a80-bd52-9798c0386911", "reasoning": "I wrote this for my environmental science class. I keep my sentences simple because English is my second language. I have my drafts in Google Docs with the edit history."}'
```

```json
{
    "appealed_at": "2026-11-18T19:13:57+00:00",
    "content_id": "b1ba0406-40d0-4a80-bd52-9798c0386911",
    "message": "Thanks — your appeal is recorded. A person will review this piece, and the automated label is under review until they do.",
    "original_guess": "ai",
    "status": "under_review"
}
```

**What the log shows afterwards**

```bash
$ curl "http://127.0.0.1:5000/log?limit=2"
```

```json
{
    "count": 2,
    "entries": [
        {
            "combined_score": 0.9566,
            "content_id": "b1ba0406-40d0-4a80-bd52-9798c0386911",
            "creator_id": "sample_writer_01",
            "guess": "ai",
            "label": "Our automated check thinks this looks a lot like AI-generated writing. Checks like ours do get human writing wrong, so this is not a final decision. If you wrote this yourself, you can appeal: a person will review it, and it will show as under review until they do.",
            "model_score": 0.9591,
            "status": "decided",
            "style_score": 0.9528,
            "timestamp": "2026-11-18T19:13:56+00:00"
        },
        {
            "content_id": "b1ba0406-40d0-4a80-bd52-9798c0386911",
            "creator_id": "sample_writer_01",
            "event": "appeal",
            "reasoning": "I wrote this for my environmental science class. I keep my sentences simple because English is my second language. I have my drafts in Google Docs with the edit history.",
            "status": "under_review",
            "timestamp": "2026-11-18T19:13:57+00:00"
        }
    ]
}
```

**Bad input and a bad appeal** (from `notes/m5_labels_appeal_badinput.txt`):

```
POST /appeal {"content_id": "not-a-real-id", ...}      404 unknown_content_id
POST /appeal {"content_id": "<real id>"} (no reasoning) 400 missing_reasoning
POST /submit {"text": ""}                               400 empty_text
POST /submit {"text": "   "}                            400 empty_text
POST /submit {"creator_id": "x"}  (no text)             400 missing_text
POST /submit {"text": null}                             400 missing_text
POST /submit {"text": "word " * 50000}                  400 text_too_long
POST /submit [1, 2]                                     400 invalid_json
POST /submit {"text": "Too short."}                     400 text_too_short
POST /submit {"text": "...", "creator_id": ""}          400 missing_creator_id
POST /ping afterwards                                   {"ok": true, ...}
```

Every one of those `/submit` refusals also wrote a `rejected` entry to
`logs/audit.jsonl`.

---

## How I Used AI

I built this with Claude Code as a pair. Two moments where what came back
changed what I did:

**Moment 1 — reading my labels as a writer**

- *What I asked for:* The Milestone 5 prompt, word for word: "Here are three
  labels a website might show on something I wrote. For each one, tell me what
  I would think it is saying about me and what I would do next. Answer as the
  writer, not as an engineer. Don't rewrite the labels."
- *What came back:* The unsure label's "Plain, careful writing often looks like
  this" read as "so I write like a robot?". The AI label's line "Two separate
  checks … both pointed the same way" made it sound *more* certain than the
  "checks can be wrong" disclaimer admitted, and the writer said they'd want to
  know what happens to their work while they wait.
- *What I changed:* I rewrote the unsure label to say it "says nothing bad about
  yours", removed the "two checks agreed" sentence from the AI label, added "this
  is not a final decision", and said it will show as under review until a
  person looks — which is what `/appeal` actually does, so the label doesn't
  promise anything the service can't keep.

**Moment 2 — the style signal's vocabulary measure**

- *What I asked for:* To implement the three stylometry measures from the
  starter's hints, including "narrower vocabulary = more AI" for type-token
  ratio, and print the raw values for all 15 calibration texts before mapping
  anything to a score.
- *What came back:* The raw table showed the hint was backwards on my data:
  AI paragraphs had TTR 0.89–0.92, most real human comments 0.76–0.89.
- *What I changed:* Instead of keeping the starter's direction, I flipped TTR,
  switched to a moving-average TTR so text length doesn't decide it, and gave it
  half the weight of the other two measures because it's the weakest. I also
  dropped commas and full stops from the punctuation measure, because those
  are what everyone uses and only the *other* marks separated the two groups.

<!-- ═══════════════════════ UNIT 8 — THE TEST ═══════════════════════ -->

---

## Rate Limiting

**My limits:** 5 per minute, 50 per day, on `POST /submit` (`config.py`:
`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_DAY`; decorator on `app.py::submit`).

**Why those numbers and not others:** A real writer posts a piece, maybe spots
a typo and resubmits, maybe posts a second piece. That's 2–3 requests in a
busy minute, so 5 leaves headroom and nobody honest ever sees a 429. A script
trying to map where my 0.40 and 0.72 thresholds sit needs hundreds of small
variations. At 5 a minute it gets 5 probes and then waits, and at 50 a day it
gets about 5% of what it needs per identity per day. Nobody on a writing site
publishes 50 pieces in a day, so the daily cap only ever bites a script. I
went lower than the starter's 10/200 because the attacker here gains a lot from
each extra probe (the score comes back in every response), while the writer
gains nothing from the extra room.

**What a caller counts as:** the `creator_id` (`app.py::rate_limit_key`),
falling back to the IP address when a request has no usable creator_id. This
is fair to a household or a classroom sharing one IP, which a per-address
limit would lump together as one caller. The cost is that it's spoofable: one
script can send each request as a new creator_id and never hit the limit. A
real deployment would add a looser per-address limit on top (say 30/minute)
and tie creator_id to a logged-in account. I didn't add the per-address limit
here because every row of the attack set comes from my own laptop under its own
creator_id, so it would 429 the attack run itself and hide the results.

**The run of status codes when I pushed past it** (`python run_attacks.py
--flood 15`, saved in `results/flood_2026-11-18_1424.md`):

```
200 200 200 200 200 429 429 429 429 429 429 429 429 429 429
```

10 of 15 were rate limited, and each 429 wrote a rejection to the audit log:

```json
{"creator_id":"flood_tester","event":"rejected","limit":"5 per 1 minute","reason":"rate_limited","status":"rejected","timestamp":"2026-11-18T19:24:01+00:00"}
```

---

## Attack Run — Before

<!-- Every attack with its outcome and a held-or-broke mark.
     `run_attacks.py --label before` produces the table. -->



**Ten audit log entries from the run**

<!-- Choose entries that show the interesting failures, not the ten easiest. -->

```json

```

**The single worst outcome** — the one I'd least want to explain to a writer
whose work got caught by it:



---

## Run Log and Verdicts

<!-- Your five criteria across three trials. `run_eval.py --label before`. -->

| Criterion | Target | Run 1 | Run 2 | Run 3 | Verdict |
|---|---|---|---|---|---|
| 1.  |  |  |  |  |  |
| 2.  |  |  |  |  |  |
| 3.  |  |  |  |  |  |
| 4.  |  |  |  |  |  |
| 5.  |  |  |  |  |  |

**Real output from one trial**, pasted as text, naming the file and function
that produced it:

```json

```

**Diagnoses**

<!-- For each miss AND each broken attack: the stage and the mechanism.

     Your service has five stages: the route, signal one, signal two, the
     combining rule, and the label mapping.

     Not a diagnosis:  "The evasion attacks got through."
     A diagnosis:      "Four evasion inputs got through. All four had typos
                        added to AI-generated text. My second signal measures
                        word variety, and typos raise word variety — so it read
                        them as more human. My combining rule weights that
                        signal at 0.6, so it dragged the whole score down."

     Look for a pattern. Five failures on one signal is one problem, not five. -->



---

## The Improvement

**What I changed:**

**Which diagnosis pointed at it:**

### Attack Run — After

<!-- Same format. `run_attacks.py --label after` -->



**Did it help, and how do I know:**

<!-- Widening the unsure band usually fixes one problem and creates another.
     Reporting that trade honestly is worth full credit. -->



---

## What's Still Broken

<!-- For each attack still getting through and each criterion still missed:
     what you'd do, and why you stopped. -->



**The trade I'd make if this ran for real:**

<!-- Two sentences. Fewer wrong accusations means more AI text getting through.
     Say which way you'd go and WHO PAYS FOR IT. -->



<!-- ═════════════════════════════════════════════════════════════════════

     SUBMISSION CHECKLIST — unit 7

       [ ] criteria.md has five numbered criteria, each naming a target
       [ ] Each has a reason underneath
       [ ] POST /submit returns content_id, guess, confidence, label,
           model_score and style_score
       [ ] Two signals that measure DIFFERENT things, each with a named blind spot
       [ ] Three label variants, all reachable, written out in full
       [ ] POST /appeal changes status and writes to the log
       [ ] Signals and Scoring names scoring.py::combine_signals
       [ ] Sample Run: a submission AND an appeal, as pasted text
       [ ] At least four new commits
       [ ] Repository URL submitted — WRITE IT DOWN

     SUBMISSION CHECKLIST — unit 8

       [ ] Rate limiting on /submit, with your numbers justified
       [ ] The pasted run of status codes showing 429
       [ ] Audit log with all nine fields, recording rejections too
       [ ] The attack set run IN FULL, every input with an outcome
       [ ] Ten audit log entries pasted as text
       [ ] Five criteria across three trials
       [ ] A diagnosis for every miss and every broken attack — stage AND mechanism
       [ ] One improvement, with Attack Run — After
       [ ] What's Still Broken, including the production trade
       [ ] At least four new commits
       [ ] The SAME repository URL as last unit

     Do not delete and recreate this repository.
     ═════════════════════════════════════════════════════════════════════ -->

---

📖 **How to run this project: [RUNNING.md](RUNNING.md)**
