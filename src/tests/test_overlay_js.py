"""Runs the overlay.js behaviour harness under node.

`overlay.js` is the only part of the OBS overlay that runs in the browser, and
nothing in this suite could see it: the status-card flicker and the wipe-the-DOM
-on-one-failed-poll bug both shipped because a Python test cannot reach them.
`support/overlay_js_check.mjs` evaluates the real file in a `vm` context against
a minimal DOM stub and asserts the quiet-status behaviour.

The test skips when node is unavailable rather than adding a hard toolchain
dependency to a Python suite. A skip is a *gap*, not a pass -- if the overlay
JS is being changed, run the harness directly:

    node src/tests/support/overlay_js_check.mjs
"""

from __future__ import annotations

import src  # noqa: F401  (path bootstrap, as in the rest of the suite)

from pathlib import Path
import shutil
import subprocess
import unittest


HARNESS = Path(__file__).resolve().parent / "support" / "overlay_js_check.mjs"


class OverlayJsBehaviourTests(unittest.TestCase):
    def test_overlay_js_quiet_status_behaviour(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; run the harness manually")
        self.assertTrue(HARNESS.is_file(), f"missing harness: {HARNESS}")

        result = subprocess.run(
            [node, str(HARNESS)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"overlay.js harness failed:\n{result.stdout}\n{result.stderr}",
        )
        self.assertIn("all overlay.js checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
