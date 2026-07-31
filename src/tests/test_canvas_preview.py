"""The read-only layout preview, and the one thing it must not get wrong.

Its whole job is *where*. A block drawn a little too large is cosmetic; a block
drawn in the wrong place is the preview lying about the thing it exists to show
-- and the first version did exactly that. It sized unknown blocks from their
label's pixel width and then slid them inward to fit the frame, so at roughly
1:6, where the label measures three to four times the real widget, a widget
parked against the right edge was drawn near the middle.

Asserted on `block_rects` rather than on rendered pixels. The pixel version was
written first and is a poor bargain: the grid drawn behind the blocks makes
"differs from the background" true almost everywhere, so the probe ends up
measuring the grid.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite


class CanvasPreviewTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication
            from ui.canvas_preview import CanvasPreview, PreviewWidget

            app = QApplication([])

            def preview(canvas=(1920, 1080), size=(320, 180)):
                widget = CanvasPreview()
                widget.set_canvas(*canvas)
                widget.resize(*size)
                return widget
            """
        ) + textwrap.dedent(body)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_label_does_not_decide_where_a_block_goes(self) -> None:
        """The regression, stated as directly as it can be.

        Two blocks at one coordinate, one with a short name and one with a long
        one. If the label is sizing the block, the long one is wider, has to be
        pushed left to fit the frame, and lands somewhere else entirely.
        """
        self._run(
            """
            short = preview()
            short.set_widgets([PreviewWidget(label="ON", x=1800, y=40)])
            long = preview()
            long.set_widgets([
                PreviewWidget(label="Scanner status and recording state", x=1800, y=40)
            ])

            (short_block,) = short.block_rects()
            (long_block,) = long.block_rects()
            assert short_block == long_block, (short_block, long_block)
            """
        )

    def test_a_block_lands_where_its_coordinates_say(self) -> None:
        self._run(
            """
            widget = preview()
            widget.set_widgets([PreviewWidget(label="Stats", x=1800, y=540)])
            frame = widget.frame_rect()
            (block,) = widget.block_rects()

            expected_x = frame.left() + round(1800 * frame.width() / 1920)
            expected_y = frame.top() + round(540 * frame.height() / 1080)
            assert block.left() == expected_x, (block.left(), expected_x)
            assert block.top() == expected_y, (block.top(), expected_y)

            # And that really is the far right: the last sixth of the frame.
            assert block.left() > frame.left() + frame.width() * 0.85, block.left()
            """
        )

    def test_a_block_past_the_edge_is_left_past_the_edge(self) -> None:
        """Off-canvas must look off-canvas -- it is what you open this to find."""
        self._run(
            """
            widget = preview()
            widget.set_widgets([PreviewWidget(label="Stats", x=1910, y=40)])
            frame = widget.frame_rect()
            (block,) = widget.block_rects()

            assert block.right() > frame.right(), (block.right(), frame.right())
            assert block.left() > frame.right() - 6, block.left()
            """
        )

    def test_a_known_size_scales_with_the_canvas(self) -> None:
        """Sizes are canvas units, like the coordinates -- not screen pixels."""
        self._run(
            """
            widget = preview()
            widget.set_widgets([PreviewWidget(label="Stats", x=0, y=0, width=960, height=540)])
            frame = widget.frame_rect()
            (block,) = widget.block_rects()

            assert abs(block.width() - frame.width() / 2) <= 1, block.width()
            assert abs(block.height() - frame.height() / 2) <= 1, block.height()
            """
        )

    def test_the_frame_follows_the_real_canvas_shape(self) -> None:
        """Not the mock's hardcoded 16:9 -- the canvas is user-set."""
        self._run(
            """
            wide = preview(canvas=(2560, 1080))
            tall = preview(canvas=(1920, 1200))
            assert wide.heightForWidth(320) == round(320 * 1080 / 2560), wide.heightForWidth(320)
            assert tall.heightForWidth(320) == round(320 * 1200 / 1920), tall.heightForWidth(320)
            """
        )

    def test_a_placeholder_draws_no_blocks_at_all(self) -> None:
        """The flow-layout case: no coordinates exist, so none are invented."""
        self._run(
            """
            widget = preview()
            widget.set_widgets([PreviewWidget(label="Stats", x=1800, y=40)])
            assert widget.block_rects()

            widget.set_placeholder("Widgets are auto-arranged.")
            assert widget.block_rects() == []
            """
        )


if __name__ == "__main__":
    unittest.main()
