"""Compact, allocation-free readout for the curves visible in Compare Runs."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from core.stat_labels import abbreviate_stat_label
from projections import scrubber as scrubber_model
from ui.shared import FlowLayout
from ui.timeline_controls import timeline_series_accent_role


class _SeriesLegendItem(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsTimelineLegendItem")
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(5)

        self._dot = QLabel("●")
        self._dot.setObjectName("CompareRunsTimelineLegendDot")
        self._name = QLabel()
        self._name.setObjectName("CompareRunsTimelineLegendName")
        self._value_a = self._make_value("A")
        self._arrow = QLabel("→")
        self._arrow.setObjectName("CompareRunsTimelineLegendArrow")
        self._value_b = self._make_value("B")
        self._delta = QLabel("Δ --")
        self._delta.setObjectName("CompareRunsTimelineLegendDelta")
        self._delta.setToolTip("Difference: Run B minus Run A")

        layout.addWidget(self._dot)
        layout.addWidget(self._name)
        layout.addSpacing(2)
        layout.addWidget(self._value_a)
        layout.addWidget(self._arrow)
        layout.addWidget(self._value_b)
        self._separator = QLabel("·")
        self._separator.setObjectName("CompareRunsTimelineLegendSeparator")
        layout.addWidget(self._separator)
        layout.addWidget(self._delta)

    @staticmethod
    def _make_value(side: str) -> QLabel:
        label = QLabel(f"{side} --")
        label.setObjectName("CompareRunsTimelineLegendValue")
        label.setProperty("side", side)
        return label

    def set_key(self, key: str) -> None:
        self._set_text(
            self._name,
            abbreviate_stat_label(scrubber_model.series_label(key)),
        )
        accent = timeline_series_accent_role((key,))
        if self._dot.property("accentRole") != accent:
            self._dot.setProperty("accentRole", accent)
            style = self._dot.style()
            style.unpolish(self._dot)
            style.polish(self._dot)

    def set_values(self, value_a: str, value_b: str, delta: str) -> None:
        self._set_text(self._value_a, f"A {value_a}")
        self._set_text(self._value_b, f"B {value_b}")
        self._set_text(self._delta, f"Δ {delta}")

    @staticmethod
    def _set_text(label: QLabel, text: str) -> None:
        if label.text() != text:
            label.setText(text)


class CompareRunsTimelineLegend(QWidget):
    """Pooled footer items; pointer input changes text, never widget structure."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsTimelineLegend")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._flow = FlowLayout(self, margin=0, spacing=8)
        self._items: list[_SeriesLegendItem] = []
        self._keys: tuple[str, ...] = ()

        self._empty = QLabel("No curves selected")
        self._empty.setObjectName("CompareRunsTimelineLegendEmpty")
        self._flow.addWidget(self._empty)

    @property
    def keys(self) -> tuple[str, ...]:
        return self._keys

    def set_keys(self, keys) -> None:
        unique_keys = tuple(dict.fromkeys(str(key) for key in keys if key))
        if unique_keys == self._keys:
            return
        self._keys = unique_keys

        while len(self._items) < len(unique_keys):
            item = _SeriesLegendItem(self)
            self._items.append(item)
            self._flow.addWidget(item)

        self._empty.setVisible(not unique_keys)
        for index, item in enumerate(self._items):
            visible = index < len(unique_keys)
            item.setVisible(visible)
            if visible:
                item.set_key(unique_keys[index])
        self.updateGeometry()

    def set_values(self, values) -> None:
        readings = dict(values)
        for key, item in zip(self._keys, self._items):
            item.set_values(*readings.get(key, ("--", "--", "--")))
