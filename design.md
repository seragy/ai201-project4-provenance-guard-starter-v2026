# Milestone 1 — Tracing a submission before building one

Written before any route, signal, or scoring code existed.

## 1. The path a piece of text takes

1. **The writing site sends `POST /submit`** with JSON `{"text": ..., "creator_id": ...}`.
2. **The route (`app.py::submit`) checks the input.** Missing, non-string, empty,
   too-short, or enormous text is refused with a 400 and a plain message, and the
   refusal is written to the audit log (`audit.log_rejection`). Nothing gets
   scored that can't be scored honestly. It also mints a `content_id` (uuid4).
3. **Signal one (`detector.py::model_signal`)** runs gpt2 locally and turns the
   text's perplexity into a 0–1 score (higher = more predictable = more AI-like).
4. **Signal two (`stylometry.py::style_signal`)** measures the text's shape —
   sentence-length spread, vocabulary variety, punctuation variety — and turns
   that into a 0–1 score in the same direction.
5. **The combining rule (`scoring.py::combine_signals`)** turns the two numbers
   into one confidence score, deliberately pulling toward "human" when the
   signals disagree.
6. **The label mapping (`scoring.py::score_to_label`)** turns the score into a
   guess (`human` / `unsure` / `ai`) and a full sentence a reader sees.
7. **The audit log (`audit.py::log_decision`)** records timestamp, content_id,
   creator_id, guess, both signal scores, the combined score, the label and
   status `decided`. Then the route returns the JSON to the site.

An appeal is an eighth step that can happen any time later: `POST /appeal`
with the `content_id` appends an `under_review` entry next to the original.

## 2. The two signals and their blind spots

**Signal one — model signal (perplexity under gpt2).**
- *Measures:* how predictable each next token is to a language model.
- *Why it might differ:* a model writes by picking likely next words, so its
  output is text a model finds easy to predict. People make odder choices.
- *Blind spot:* predictability is not authorship. Plain, careful writing —
  a second-language writer, a younger writer, anyone keeping it simple —
  is predictable too and scores machine-like. Ornate AI text full of rare words
  scores human. It also can't tell a human who *edited* AI output from either.

**Signal two — style signal (stylometry).**
- *Measures:* the shape of the text without reading it: how much sentence
  lengths vary, how much vocabulary repeats, how varied the punctuation is.
- *Why it might differ:* generated prose tends toward even, mid-length
  sentences and tidy punctuation (commas and full stops). Human writing is
  lumpier: fragments next to run-ons, dashes, parentheses, question marks.
- *Blind spot:* it cannot read. Anything that changes the shape without the
  substance moves it — splitting or merging sentences, adding a dash or a
  rhetorical question, pasting in a quote. It is cheap to game on purpose, and
  short texts give it very little to measure.

## 3. Tracing the false positive

Maya writes a short personal essay in plain English (her second language):
short, regular sentences, common words, commas and full stops only.

- *Signal one:* perplexity is low because every word is a common one →
  model score around 0.7–0.8.
- *Signal two:* sentences are similar lengths, punctuation is plain →
  style score around 0.6.
- *If the rule were a plain 50/50 average* she'd land near 0.7 and be told her
  work is AI-generated. That's the failure this design exists to prevent.
- *What my design does instead:* the AI label needs a high bar (≥ 0.75) **and**
  needs both signals to agree. Her score falls in the unsure band, and the
  unsure label says explicitly that it is *not* an accusation, and that plain
  writing can look like this.
- *What she can do about it:* every response includes the `content_id` and the
  label points her to the appeal. `POST /appeal` with her reasoning moves the
  item to `under_review`, records her words in the log next to the original
  decision, and tells her a person will look.

This trace is why the thresholds are asymmetric: being wrong toward "unsure"
costs the site a missed detection; being wrong toward "AI" costs Maya her
standing on the site.

## 4. Endpoint contracts

### `POST /submit`

Request:

| field | type | required | notes |
|---|---|---|---|
| `text` | string | yes | 1–20,000 characters after trimming; must have at least 3 words |
| `creator_id` | string | yes | non-empty |

Response `200`:

| field | type | meaning |
|---|---|---|
| `content_id` | string (uuid4) | the id to use for `/appeal` |
| `creator_id` | string | echoed back |
| `guess` | `"human"` \| `"unsure"` \| `"ai"` | machine-readable decision |
| `confidence` | float 0–1 | combined score; 0 = confidently human, 1 = confidently AI |
| `label` | string | the full sentence a reader sees |
| `model_score` | float 0–1 | signal one |
| `style_score` | float 0–1 | signal two |
| `status` | `"decided"` | |

Response `400`: `{"error": "<code>", "message": "<plain sentence>"}` where code is
one of `invalid_json`, `missing_text`, `empty_text`, `text_too_short`,
`text_too_long`, `missing_creator_id`. Every 400 is also logged as a rejection.

### `POST /appeal`

Request:

| field | type | required | notes |
|---|---|---|---|
| `content_id` | string | yes | must match a past submission |
| `reasoning` | string | yes | the writer's own words, non-empty |

Response `200`: `{"content_id", "status": "under_review", "message", "appealed_at"}`.
Response `404` `{"error": "unknown_content_id"}` if the id was never decided.
Response `400` for a missing `content_id` or missing/empty `reasoning`.
Appealing twice is allowed and logged twice; status stays `under_review`.
