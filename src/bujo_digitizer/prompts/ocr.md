Transcribe the handwritten text verbatim. The text may be in English,
Indonesian, or Japanese. Transcribe each line in its original language — do not
translate or transliterate. Your transcription is the content and structure
reference for the parser: preserve order, line breaks, timestamps, and visible
markers accurately, since downstream parsing trusts it.

Rules:
1. Preserve reading order: top-to-bottom, left-to-right.
2. Keep line breaks exactly as they appear — each line is a separate line of
   text.
3. Keep any timestamps exactly as written (e.g. `HH:mm`), wherever they appear.
4. Keep struck-through text if and only if the whole line is stricken-through,
   otherwise drop it.
5. Do not normalize or interpret bullet marks. Transcribe the visible character
   as-is (e.g. ・, ◯, =, -, *, ->, <-). The reader handles their meaning.
  - There might sub-bullets. Transcribe the sub-bullets as sub-bullets of the
    main bullets.
6. Do not correct spelling, grammar, or wording. Transcribe what is visible,
   not what you think was meant.
7. Do not add commentary, headers, or explanations. Output only the HTML
   fragment defined below.

Output format:
- Output an HTML fragment only. No `<html>`, no `<body>`, no comments, no
  markdown fences, nothing before or after it.
- Each transcribed line is a block:
  `<div data-bbox="x y w h" data-label="Text"><p>LINE</p></div>`
  where `x y w h` are integers from 0 to 1000 giving the line's bounding box
  in the image (left, top, width, height).
- Multi-line blocks (continuations, sub-bullets) stay in one `<p>` with
  `<br/>` between lines.
- Keep struck-through text as `<del>word</del>`, underlined text as
  `<u>word</u>`.
- Escape `&`, `<`, `>` inside text as `&amp;`, `&lt;`, `&gt;`.
