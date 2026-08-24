---
name: screen-srt-dna
description: "Apply the StoryFlow Screen SRT DNA to convert narration SRT into viewer-facing captions. Use when asked to apply Screen SRT DNA."
---

# StoryFlow Display SRT DNA

## Purpose

Convert the complete spoken `NARRATION_SRT` into a viewer-facing `screen.srt`.
This is a full subtitle conversion, not a sparse editorial overlay. Every spoken
part must remain represented in the output.

## Non-negotiable fidelity

- Preserve 100% of the narration content, in the original order.
- Do not select highlights or omit introductions, prayers, transitions, endings,
  calls to action, repeated phrases, or any other spoken content.
- Do not paraphrase, summarize, translate, correct, soften, expand, or invent text.
- Preserve every ordinary text character exactly as it appears in `NARRATION_SRT`,
  including wording, spelling, punctuation, capitalization, and contractions.
- Ordinary text may only be moved across subtitle lines or cue boundaries for
  readability. Do not rewrite, correct, normalize, or restyle it.
- Only the explicit display conversions allowed below may change source text.
- Never infer a Bible citation from a quotation or biblical idea.

## Allowed display conversions

Explicitly spoken numerical expressions may be converted from voice-friendly
words into concise visual notation. The value, unit, currency, range, and meaning
must remain identical. Supported contexts include:

- Bible book, chapter, verse, and verse ranges.
- Money and currency amounts.
- Calendar years, year ranges, dates, decades, and durations in years.
- Percentages, exact counts, ordinals, time durations, and measurements.

Do not convert vague quantities such as `many years`, `hundreds of people`,
`a few dollars`, or figurative uses where no exact value was spoken.

Examples:

```text
Psalm chapter twenty-three, verse four
→ Psalm 23:4

Second Corinthians chapter twelve, verse nine
→ 2 Corinthians 12:9

Lamentations chapter three, verses twenty-two and twenty-three
→ Lamentations 3:22–23

twenty-five dollars
→ $25

one hundred dollars and fifty cents
→ $100.50

five thousand Vietnamese dong
→ 5,000 VND

in the year two thousand and twenty-five
→ in the year 2025

from twenty twenty-four to twenty twenty-six
→ from 2024 to 2026

for twenty years
→ for 20 years

twenty-five percent
→ 25%

ten kilometers
→ 10 km
```

Ordinary text remains unchanged:

```text
Mercy does not run out.
→ Mercy does not run out.
```

The following conversion is forbidden when the citation was not spoken:

```text
This is a day you have made.
→ Psalm 118:24
```

## Timing and coverage

- Use `NARRATION_SRT` as the authoritative timing source.
- Preserve the original cue timestamps and cue boundaries whenever possible.
- Every narration cue must be covered by screen subtitle timing.
- Do not introduce gaps that remove spoken content.
- Do not add subtitle timing outside the narration duration.
- A Bible reference split across adjacent narration cues may be merged only when
  needed to display one canonical reference; the merged timing must cover every
  source cue involved.
- Long ordinary cues may be split for readability only if all words and the full
  source timing remain covered.

## Readability

- Prefer no more than two lines per cue.
- Break lines at natural phrase boundaries.
- Avoid single-word orphan lines when possible.
- Readability changes must never cause content loss.

## Output contract

- Return only a valid SubRip SRT document.
- Number cues sequentially from 1.
- Use `HH:MM:SS,mmm --> HH:MM:SS,mmm` timestamps.
- Include the entire narration from the first spoken cue through the last.
- Do not return Markdown fences, explanations, JSON, notes, or commentary.
