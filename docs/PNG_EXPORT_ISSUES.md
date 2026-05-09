# PNG Export Issues (macOS, in-process PyStata)

## Summary
- PNG graph export can fail intermittently on macOS when invoked from the in-process Python Stata client.
- Observed failure mode: `graph export ... as(png)` returns `rc=5100` and may leave a zero-byte output file.

## Reproduction Context
- Runtime: `stata-se` initialized via `stata_setup` and used through embedded PyStata calls.
- Typical sequence:
  - `scatter price mpg, name(ServerGraph, replace)`
  - `graph display ServerGraph`
  - `graph export "<path>.png", replace as(png)`
- Result: repeated `rc=5100` in some runs.

## Diagnostics Observed
- Stack traces point into Stata's Java/OpenGL rendering path (e.g., `tr_bitmap_from_svg` / AWT OpenGL surface calls).
- The same export operation succeeds when run as a standalone `stata-se -b do ...` batch command.
- Requirement for this project is to keep export in the Python Stata client path (no terminal fallback path for macOS).

## Current Status
- PNG export logic has been reverted to the standard in-client behavior.
- No non-Stata image conversion fallback is used.
- This issue remains documented for future Stata-side or PyStata-side mitigation.
