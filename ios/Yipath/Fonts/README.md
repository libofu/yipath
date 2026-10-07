# Bundled font

`NotoSerifSC-Regular.ttf` and `NotoSerifSC-Bold.ttf` are static, subsetted instances of
**Noto Serif SC** (思源宋体), © Google / Adobe, licensed under the SIL Open Font License 1.1
(see `OFL.txt`).

- Source: https://github.com/google/fonts/tree/main/ofl/notoserifsc (variable font `NotoSerifSC[wght].ttf`)
- Made with fontTools: instanced at wght 400 and 700, then subset to the 6,763 GB2312 Hanzi,
  ASCII, common punctuation, fullwidth forms, and every character in the theme library and angle files.
  Characters outside the subset fall back to the system font (PingFang).
- If you add theme-library entries with rare characters, regenerate the subset.
