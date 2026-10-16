"""Reset timing input that keeps invalid drafts visible instead of clamping them."""
from __future__ import annotations

import re

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLineEdit


class ResetTimingInput(QLineEdit):
    valueChanged = Signal(float)

    def __init__(self):
        super().__init__()
        self._minimum = 0.0
        self._maximum = 10.0
        self._value = 0.0
        self._suffix = " s"
        self._step = 0.01
        self.finished_input = False
        self.textChanged.connect(self._changed)
        self.textEdited.connect(self._typing)
        self.editingFinished.connect(self._finished)

    def _typing(self, _text):
        self.finished_input = False

    def _finished(self):
        self.finished_input = True

    def number(self):
        text = self.text().removesuffix(self._suffix).strip().replace(",", ".")
        if not re.fullmatch(r"(?:\d+|\d*\.\d{1,2})", text):
            return None
        return float(text)

    def is_incomplete(self):
        text = self.text().removesuffix(self._suffix).strip().replace(",", ".")
        return text in ("", ".") or bool(re.fullmatch(r"\d+\.", text))

    def _changed(self, _text):
        number = self.number()
        if number is not None and self._minimum <= number <= self._maximum:
            if number != self._value:
                self._value = number
                self.valueChanged.emit(number)

    def value(self):
        number = self.number()
        return self._value if number is None else number

    def setValue(self, value):
        self.finished_input = False
        self.setText(f"{value:.2f}{self._suffix}")
        # A valueChanged handler may have rejected this edit and restored a value.
        number = self.number()
        self._value = value if number is None else number
        self.setModified(False)

    def setRange(self, minimum, maximum):
        self._minimum, self._maximum = minimum, maximum

    def setMinimum(self, value):
        self._minimum = value

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum

    def setSingleStep(self, value):
        self._step = value

    def singleStep(self):
        return self._step

    def setDecimals(self, _value):
        pass  # Timing precision is always two decimal places.

    def setSuffix(self, value):
        self._suffix = value

    def suffix(self):
        return self._suffix

    def lineEdit(self):
        return self

    def interpretText(self):
        self._finished()
        self.editingFinished.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            direction = 1 if event.key() == Qt.Key_Up else -1
            self.setValue(max(self._minimum, min(self._maximum, self.value() + direction * self._step)))
            self.textEdited.emit(self.text())
            return
        super().keyPressEvent(event)
