# Review · colloquia-lanzamiento

- Built as a twin of `dicto/videos/dicto-lanzamiento` at the user's request ("como el de Dicto"): same 30 s length, structure (hook → app → proof → privacy → end card), music track and SFX. No alternative storylines were explored.
- UI is rebuilt from `ui.html` (real labels, the five real processing stages, real colours and logo) at roughly 2x. The session is fictional: the transcript lines come from the README example, plus two invented turns (`¿Y qué viste allí?` / `Un perro ⟨pelo⟩ muy grande.`) that illustrate the `⟨ ⟩` feature.
- Avoided claims the repo does not make: no "open source" (the repo has no LICENSE), no accuracy promises.
- Measured: `check` passes with 0 errors. One kept warning: `contrast_aa_failure` on "consulta" in privacy at 21.67 s, mid colour tween (the word is lighting up). Looked at the 19 QA frames listed in SPEC.md plus re-shots at 10.6 s and 13.6 s after the fixes.
- Not checked: the sound was placed, not heard; motion between beats was not sampled with `--range`.
- Weakest shot: 13.0–14.5 s, the transcript card is mostly empty while the first rows arrive. With more time: start with two rows already in, or shrink the card and grow it as rows land.
