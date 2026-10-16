from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import main
from infra import app_restart


class AppRestartTests(unittest.TestCase):
    def test_source_restart_uses_absolute_entrypoint_without_waiting_for_shell(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(
            sys, "argv", ["src/main.py"]
        ), patch.object(app_restart.subprocess, "Popen") as launch:
            app_restart.launch_restart()
        command = launch.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(os.path.isabs(command[1]))
        self.assertTrue(command[1].endswith("main.py"))
        self.assertEqual(command[2], f"--bonkscanner-restart-after={os.getpid()}")

    def test_failed_wait_does_not_open_or_migrate_storage(self):
        with patch.object(app_restart, "wait_for_previous_instance", side_effect=OSError("Still running")), patch(
            "infra.data_storage.initialize_storage"
        ) as initialize, patch.object(main, "_show_startup_storage_error") as notice:
            main.main()
        initialize.assert_not_called()
        notice.assert_called_once_with("Still running")

    def test_frozen_restart_waits_for_python_and_onefile_launcher(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "argv", ["BonkScanner.exe", "--bonkscanner-restart-after=99"]
        ), patch.dict(os.environ, {"_PYI_PARENT_PROCESS_LEVEL": "1"}), patch.object(
            app_restart.os, "getpid", return_value=10
        ), patch.object(app_restart.os, "getppid", return_value=9), patch.object(
            app_restart.subprocess, "Popen"
        ) as launch:
            app_restart.launch_restart()
        self.assertEqual(launch.call_args.args[0], [sys.executable, "--bonkscanner-restart-after=10,9"])
        self.assertEqual(launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_restart_wait_consumes_argument_before_storage_bootstrap(self):
        with patch.object(sys, "argv", ["app", "--bonkscanner-restart-after=10,9"]), patch.object(
            app_restart.os, "name", "nt"
        ), patch.object(app_restart, "_wait_for_process") as wait:
            app_restart.wait_for_previous_instance()
            self.assertEqual(sys.argv, ["app"])
        self.assertEqual([call.args[0] for call in wait.call_args_list], [10, 9])

    @unittest.skipUnless(os.name == "nt", "Windows process wait")
    def test_waits_for_real_process_exit(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.3)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            app_restart._wait_for_process(process.pid)
            self.assertEqual(process.poll(), 0)
            # Already-exited process is also a successful wait.
            app_restart._wait_for_process(process.pid)
        finally:
            process.wait(timeout=5)

    def test_main_restarts_only_after_successful_shutdown_and_lock_release(self):
        for clean in (True, False):
            with self.subTest(clean=clean):
                events = []
                app = MagicMock()
                app._restart_requested = True
                app.on_closing.side_effect = lambda: events.append("shutdown") or clean
                with patch("infra.data_storage.initialize_storage"), patch(
                    "infra.data_storage.release_storage_lock", side_effect=lambda: events.append("release")
                ), patch.object(app_restart, "wait_for_previous_instance"), patch.object(
                    app_restart, "launch_restart", side_effect=lambda: events.append("restart")
                ), patch.object(main, "install_crash_journal"), patch.object(
                    main, "mark_clean_exit"
                ), patch.object(main, "log_runtime_event"), patch.object(
                    main, "_initialize_configuration"
                ), patch.object(main, "_load_keyboard_dependency", return_value=object()), patch.object(
                    main, "_load_gui_application", return_value=MagicMock(return_value=app)
                ):
                    main.main()
                self.assertEqual(events, ["shutdown", "release", "restart"] if clean else ["shutdown", "release"])
