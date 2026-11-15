from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.shutdown import ShutdownReport
from gui_app import MegabonkApp


class _ShutdownWindowOwner:
    """Inject the collaborators while exercising the application's Qt shutdown."""

    on_closing = MegabonkApp.on_closing
    _handle_window_close = MegabonkApp._handle_window_close
    destroy = MegabonkApp.destroy

    def __init__(self, validator):
        self.window = QWidget()
        self._window_shown = False
        self._close_in_progress = False
        self._is_shutting_down = False
        self._close_protocol_handler = self.on_closing
        self._appearance_runtime = None
        self.coordinator = SimpleNamespace(validator=validator)

    @property
    def qt_app(self):
        return QApplication.instance()


def test_window_close_keeps_qt_running_until_validator_finishes():
    qt = QApplication.instance() or QApplication([])
    events = []
    validator = SimpleNamespace(done=False)

    def close(*, timeout):
        events.append(('validator', timeout))
        return validator.done

    validator.close = close
    app = _ShutdownWindowOwner(validator)
    app.window.show()
    app._window_shown = True
    app._capture_window_placement = lambda: (
        events.append(('capture', app.window.isVisible())), {'rect': [1, 2, 3, 4]})[1]
    app._save_window_placement = lambda: events.append(
        ('save', app.window.isVisible(), app._pending_window_placement))
    app.runtime = SimpleNamespace(shutdown=lambda deadline, **options: (
        events.append(('shutdown', options)), ShutdownReport())[1])

    event = QCloseEvent()
    app._handle_window_close(event)
    assert not event.isAccepted()
    assert not app._is_shutting_down
    assert ('capture', True) in events
    assert not app.window.isVisible()
    assert not any(item[0] == 'save' for item in events)
    QTimer.singleShot(0, lambda: events.append(('heartbeat',)))
    QTest.qWait(50)
    assert ('heartbeat',) in events
    assert any(item[0] == 'validator' for item in events)
    assert not any(item[0] == 'shutdown' for item in events)

    validator.done = True
    QTest.qWait(60)
    assert ('shutdown', {'validator_timeout': 0.0}) in events
    assert ('save', False, {'rect': [1, 2, 3, 4]}) in events
    assert app._shutdown_report.completed
    assert all(item[1] == 0.0 for item in events if item[0] == 'validator')


def test_hidden_window_keeps_application_loop_alive_until_shutdown():
    qt = QApplication.instance() or QApplication([])
    validator = SimpleNamespace(done=False)
    validator.close = lambda *, timeout: validator.done
    app = _ShutdownWindowOwner(validator)
    app.runtime = SimpleNamespace(shutdown=lambda deadline, **options: ShutdownReport())
    app.window.show()

    heartbeat = []
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(qt.quit)
    watchdog.start(1000)
    QTimer.singleShot(0, lambda: app._handle_window_close(QCloseEvent()))
    QTimer.singleShot(40, lambda: heartbeat.append(True))
    QTimer.singleShot(120, lambda: setattr(validator, 'done', True))
    qt.exec()
    watchdog.stop()

    assert heartbeat == [True]
    assert validator.done
    assert app._shutdown_report.completed
