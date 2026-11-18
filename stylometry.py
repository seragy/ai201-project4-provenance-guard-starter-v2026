"""
Signal two: the style signal. ← YOU BUILD THIS IN MILESTONE 4

Signal one reads the text for meaning. This one measures it *as text* — the
shape of it, without understanding a word.

Three measures are stubbed below because the brief names those three. They are
stubs, not implementations: what they compute is yours, and so is how you
combine them.

    sentence_length_spread   do sentences vary in length, or march in step?
    type_token_ratio         how much of the vocabulary repeats?
    punctuation_density      how much punctuation, and how varied?

Why these might differ between human and AI writing: generated prose tends
toward even, mid-length sentences and a narrower band of vocabulary, because
that's what "most likely next word" produces on average. Human writing is
lumpier — a three-word sentence next to a forty-word one.

⚠️ **The blind spot, which you have to name in Milestone 1.**

This signal cannot read. It has no idea what the text says. Anything that
changes the shape without changing the substance moves it — adding typos,
breaking up sentences, pasting in a quotation. That is a very cheap thing for
someone to do on purpose, and unit 8's attack set will do it to you.

Build each function on its own and call it from a terminal before you wire
anything together:

    python stylometry.py "some text to look at"
"""

import re
import statistics


def sentences(text: str) -> list[str]:
    """Split into sentences. Rough and good enough — given to you."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def words(text: str) -> list[str]:
    """Split into lowercase words, punctuation stripped. Given to you."""
    return re.findall(r"[a-z0-9']+", text.lower())


# ── The three measures — YOU BUILD THESE ─────────────────────────────────────

def _sentences_for_shape(text: str) -> list[str]:
    """
    Like `sentences`, but a line break also ends a sentence.

    Forum and poetry writing uses line breaks as sentence boundaries all the
    time; without this a three-line comment with no full stops reads as one
    enormous sentence and the spread measure is meaningless.
    """
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p for p in parts if words(p)]


def sentence_length_spread(text: str) -> float:
    """
    How much sentence length varies: the coefficient of variation (stdev / mean)
    of words-per-sentence.

    Scale: 0 upward. 0 means every sentence is the same length; ~0.2–0.35 is
    typical of generated prose; human writing usually lands above 0.45.
    **Higher = more human.**

    Edge case: with fewer than two sentences there is no spread to measure.
    Returns 0.0 — and `style_signal` treats that as *no evidence*, not as
    "perfectly even", so a one-sentence poem isn't read as machine-like.
    """
    lengths = [len(words(s)) for s in _sentences_for_shape(text)]
    if len(lengths) < 2:
        return 0.0
    mean = statistics.mean(lengths)
    return statistics.stdev(lengths) / mean if mean else 0.0


MATTR_WINDOW = 40


def type_token_ratio(text: str) -> float:
    """
    Vocabulary variety: unique words over total words, 0–1. Higher = more
    varied vocabulary.

    Plain TTR falls as text gets longer, so I use the *moving-average* TTR:
    the TTR of every 40-word window, averaged. That makes a 60-word comment and
    a 300-word essay comparable. Texts shorter than one window fall back to
    plain TTR.
    """
    tokens = words(text)
    if not tokens:
        return 0.0
    if len(tokens) <= MATTR_WINDOW:
        return len(set(tokens)) / len(tokens)
    ratios = [
        len(set(tokens[i:i + MATTR_WINDOW])) / MATTR_WINDOW
        for i in range(len(tokens) - MATTR_WINDOW + 1)
    ]
    return sum(ratios) / len(ratios)


# Everything except the comma and the full stop. Those two are what every
# writer — and every model — uses by default; the rest (dashes, brackets,
# question marks, ellipses, quotes, apostrophes in contractions, slashes) is
# where individual writers differ and where generated prose is sparse.
EXPRESSIVE_PUNCTUATION = set(";:-\u2013\u2014()[]?!\"'\u2018\u2019\u201c\u201d\u2026/&*")


def punctuation_density(text: str) -> float:
    """
    Expressive punctuation per 100 words.

    Counts every punctuation mark that ISN'T a comma or a full stop. Scale: 0
    upward; generated prose usually sits around 0–3, casual human writing
    often 5–15. **Higher = more human.**
    """
    n_words = len(words(text))
    if not n_words:
        return 0.0
    marks = sum(1 for ch in text if ch in EXPRESSIVE_PUNCTUATION)
    return 100.0 * marks / n_words


# ── Combining them ───────────────────────────────────────────────────────────

def _scale(value: float, ai_end: float, human_end: float) -> float:
    """Linear map: `ai_end` -> 1.0, `human_end` -> 0.0, clamped to 0–1."""
    t = (value - human_end) / (ai_end - human_end)
    return min(max(t, 0.0), 1.0)


# How each measure maps onto 0 (human-like) … 1 (AI-like), and how much it
# counts. The end points come from the 15 calibration inputs in
# calibration.py — see the README's Signals and Scoring section.
#
#                         AI end  human end  weight
STYLE_MEASURES = {
    "spread":      (0.15,   0.80,   0.4),   # even sentences   -> AI
    "punctuation": (0.0,    8.0,    0.4),   # only , and .     -> AI
    "ttr":         (0.95,   0.75,   0.2),   # FLIPPED, see below
}
# TTR direction: the starter's hint is "narrower vocabulary = AI". On my short
# calibration texts it ran the other way — the AI paragraphs (0.89–0.92) used
# MORE distinct words than the people (0.76–0.97, most below 0.89), because
# people repeat themselves ("Wow… Wow", "take a bow, take a bow") and models
# reach for a fresh synonym every sentence. It's the weakest of the three, so
# it gets half the weight of the others.


def style_components(text: str) -> dict:
    """Each measure on the shared 0–1 AI-ness scale; None = no evidence."""
    n_sentences = len(_sentences_for_shape(text))
    raw = {
        "spread": sentence_length_spread(text) if n_sentences >= 2 else None,
        "punctuation": punctuation_density(text),
        "ttr": type_token_ratio(text),
    }
    return {
        name: None if value is None else _scale(value, *STYLE_MEASURES[name][:2])
        for name, value in raw.items()
    }


def style_signal(text: str) -> float:
    """
    The style signal as a 0–1 score. **Higher means more likely AI.**

    Each measure is put on the same 0–1 scale (1 = AI-like) with `_scale`, so
    no measure wins just by having bigger raw numbers, then they're averaged
    with the weights in STYLE_MEASURES (spread 0.4, punctuation 0.4, ttr 0.2).

    A measure with no evidence (spread on a one-sentence text) is dropped and
    the remaining weights are renormalised, rather than being counted as 0 or 1.
    """
    components = style_components(text)
    total = weight_sum = 0.0
    for name, value in components.items():
        if value is None:
            continue
        weight = STYLE_MEASURES[name][2]
        total += weight * value
        weight_sum += weight
    if not weight_sum:
        return 0.5
    return round(total / weight_sum, 4)


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or (
        "The system works well. It handles most cases correctly and provides "
        "good results. Users generally find it easy to use and understand."
    )

    print(f"{len(sentences(text))} sentences, {len(words(text))} words\n")
    print(f"sentence_length_spread   {sentence_length_spread(text)}")
    print(f"type_token_ratio         {type_token_ratio(text)}")
    print(f"punctuation_density      {punctuation_density(text)}")
    print(f"style_signal             {style_signal(text)}   (higher = more likely AI)")
    print(f"components (0=human-like, 1=AI-like)  {style_components(text)}")
