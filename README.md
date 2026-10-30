# pose-claim-audit

An offline static auditor comparing body-pose promises in Markdown with
provider-resolved Python operations. Version 0.1.0; Python 3.9 or later;
MIT licensed; no runtime dependencies. Source is parsed, never executed.

Install and run:

```sh
pip install pose-claim-audit
pose-claim-audit ./project --json
python3 -m pose_claim_audit ./project --verbose
pose-claim-audit ./project --ignore 'vendor/*' --fail-on MEDIUM
pose-claim-audit --version
```

The documentation scope is root README.md and Markdown beneath any docs
path component. Blank lines separate paragraphs; fenced blocks are omitted,
inline code counts, and contractions, hyphens and whitespace are normalized.
Exact templates in phrases.py are matched longest first with word boundaries.
Negative spans are removed before positive matching. Example templates:

```text
supports pose estimation
does not estimate poses
```

Evidence comes from mediapipe solutions pose.Pose construction or a bound
process call, and tasks vision.PoseLandmarker construction (including
create_from_options) or bound detect, detect_for_video and detect_async calls.
Import aliases and assignment, annotated assignment, attribute, with-target
and chained forms are recognized within each module. Local definitions shadow
imports. Construction alone counts; imports, image loading, camera capture,
landmark drawing, face/hand detection, generic YOLO objects, strings and
subprocess commands do not.

Symlinks are omitted. Production evidence excludes fixtures, docs, examples
and tests components and test_*.py or *_test.py names. Tests supply separate
fallback evidence; invalid Python supplies none. Repeatable --ignore patterns
use fnmatch against root-relative POSIX paths. files_scanned counts included
Markdown and Python files, including Python with invalid syntax.

Rules (at most one finding per family):

```text
documented-pose-claim-false: HIGH without production evidence; MEDIUM with test evidence only
documented-no-pose-claim-false: HIGH when production evidence contradicts a negative claim
```

JSON contains verdict, findings (rule, severity, message), and files_scanned.
Human output includes the verdict and findings; --verbose adds a file count.
Exit 0 means the selected threshold was not reached, including MEDIUM findings
at the default HIGH threshold. Exit 2 means failure; exit 1 means invalid or
unreadable input or a command-line usage error. --fail-on accepts HIGH or MEDIUM.
Without a documentation claim the result passes regardless of source.

This is a syntactic check, not proof of working inference or model quality.
Dynamic imports, intermodule bindings and arbitrary data flow are unsupported.
It does not load models, validate options, resolve runtime branches or check
that a constructed object receives real images. Module-wide binding resolution
is conservative about local name shadowing and does not model execution order.

Development:

```sh
python3 -m unittest discover
python3 -m build
python3 -m pose_claim_audit .
```

The source distribution includes the unittest suite and its fixtures.
