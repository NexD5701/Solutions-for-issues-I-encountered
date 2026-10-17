"""Offline checks; never connects to a student account or changes Windows settings."""
import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
PROJECT = Path(__file__).resolve().parents[1] / "Easy_Cidaren"
os.chdir(PROJECT)

from PyQt6.QtWidgets import QApplication, QLineEdit
from api import local_token_capture as capture
from log.log import Log, RedactingFormatter, register_secret
from publicInfo.publicInfo import PublicInfo
from view.main_window import UiMainWindow


class SetupChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=PROJECT.parent / ".setup")
        self.state_dir = Path(self.directory.name)
        self.patch_dir = patch.object(capture, "STATE_DIR", self.state_dir)
        self.patch_file = patch.object(capture, "STATE_FILE", self.state_dir / "restore.json")
        self.patch_dir.start()
        self.patch_file.start()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.patch_dir.stop)
        self.addCleanup(self.patch_file.stop)

    def state(self, certificate=None):
        return {"proxy_values": {"ProxyEnable": {"kind": 4, "value": 0},
                                  "ProxyServer": None, "ProxyOverride": None},
                "proxy_applied": True, "new_certificate": certificate}

    def test_gui_and_single_task_controls(self):
        window = UiMainWindow(PublicInfo(str(PROJECT)), str(PROJECT), Log("offline_check"), Mock())
        self.assertEqual(window.token_input.echoMode(), QLineEdit.EchoMode.Password)
        self.assertTrue(window.batch_start.isHidden())
        self.assertFalse(window.action_third_party.isVisible())
        self.assertEqual(window.user_info.text(), "未获取")
        window.close()

    def test_model_can_lemmatize(self):
        import spacy
        model = spacy.load(PROJECT / "en_core_web_sm")
        self.assertEqual(model("running")[0].lemma_, "run")

    def test_log_formatter_hides_credentials(self):
        fake = "synthetic-credential-for-offline-test"
        register_secret(fake)
        formatter = RedactingFormatter("%(message)s")
        for message in ("UserToken: " + fake, "value=" + fake, '{"token":"other-test-value"}'):
            record = logging.LogRecord("check", logging.INFO, __file__, 1, message, (), None)
            formatted = formatter.format(record)
            self.assertNotIn(fake, formatted)
            self.assertNotIn("other-test-value", formatted)

    def test_recovery_restores_snapshot_and_only_own_certificate(self):
        thumbprint = "A" * 40
        state = self.state(thumbprint)
        capture._save_state(state)
        (self.state_dir / "token.txt").write_text("synthetic", encoding="utf-8")
        with patch.object(capture, "_set_proxy") as restore, \
             patch.object(capture, "_certificate_thumbprint", return_value=thumbprint), \
             patch.object(capture, "_certutil", return_value=SimpleNamespace(returncode=0)) as cert:
            self.assertTrue(capture.restore_capture_state())
            restore.assert_called_once_with(state["proxy_values"])
            cert.assert_any_call("-user", "-delstore", "Root", thumbprint)
        self.assertFalse(capture.STATE_FILE.exists())
        self.assertFalse((self.state_dir / "token.txt").exists())
        self.assertFalse(capture.restore_capture_state())

    def test_failed_restore_keeps_recovery_record(self):
        capture._save_state(self.state())
        with patch.object(capture, "_set_proxy", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                capture.restore_capture_state()
        self.assertTrue(capture.STATE_FILE.exists())

    def test_mismatched_certificate_is_never_deleted(self):
        state = self.state("A" * 40)
        state["proxy_applied"] = False
        capture._save_state(state)
        with patch.object(capture, "_certificate_thumbprint", return_value="B" * 40), \
             patch.object(capture, "_certutil") as cert:
            with self.assertRaises(RuntimeError):
                capture.restore_capture_state()
            cert.assert_not_called()
        self.assertTrue(capture.STATE_FILE.exists())

    def test_existing_recovery_record_is_not_overwritten(self):
        capture._save_state(self.state())
        before = capture.STATE_FILE.read_bytes()
        errors = []
        service = capture.TokenCaptureService(str(PROJECT / "get token" / "fetch_token"))
        with patch.object(capture, "_set_proxy") as registry:
            self.assertIsNone(service.start_capture(error_callback=errors.append))
            registry.assert_not_called()
        self.assertEqual(capture.STATE_FILE.read_bytes(), before)
        self.assertTrue(errors)

    def test_capture_restores_before_delivering_token(self):
        certificate = self.state_dir / "ca" / "mitmproxy-ca-cert.cer"
        certificate.parent.mkdir()
        certificate.write_bytes(b"synthetic cert; parsed by mock")
        token = "synthetic-in-memory-credential"
        process = Mock()
        process.poll.return_value = None
        def start_child(*args, **kwargs):
            (self.state_dir / "token.txt").write_text(token, encoding="utf-8")
            command = args[0]
            self.assertIn("127.0.0.1", command)
            self.assertIn(r"allow_hosts=^app\.vocabgo\.com(:443)?$", command)
            return process
        def delivered(value):
            self.assertEqual(value, token)
            self.assertFalse(capture.STATE_FILE.exists())
            self.assertFalse((self.state_dir / "token.txt").exists())
        service = capture.TokenCaptureService(str(PROJECT / "get token" / "fetch_token"))
        with patch.object(capture, "find_spec", return_value=object()), \
             patch.object(capture.socket, "socket"), \
             patch.object(capture, "_snapshot_proxy", return_value=self.state()["proxy_values"]), \
             patch.object(capture, "_certificate_thumbprint", return_value="C" * 40), \
             patch.object(capture, "_certutil", return_value=SimpleNamespace(returncode=0)) as cert, \
             patch.object(capture, "_set_proxy") as registry, \
             patch.object(service, "_is_port_in_use", return_value=True), \
             patch.object(capture.subprocess, "Popen", side_effect=start_child):
            self.assertEqual(service.start_capture(token_callback=delivered), token)
            self.assertEqual(registry.call_count, 2)
            self.assertFalse(any("-delstore" in call.args for call in cert.call_args_list))
        process.terminate.assert_called_once()

    def test_addon_ignores_other_sites_and_does_not_log_token(self):
        addon_path = PROJECT / "get token" / "fetch_token" / "addon.py"
        spec = importlib.util.spec_from_file_location("offline_capture_addon", addon_path)
        addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(addon)
        fake = "synthetic-addon-secret"
        target = self.state_dir / "addon-token.txt"
        with patch.dict(os.environ, {"CIDAREN_TOKEN_FILE": str(target)}), \
             patch.object(addon.capture_logger, "info") as logged:
            flow = SimpleNamespace(request=SimpleNamespace(host="other.example", headers={"UserToken": fake}))
            addon.TokenCatcher().response(flow)
            self.assertFalse(target.exists())
            flow.request.host = "app.vocabgo.com"
            addon.TokenCatcher().response(flow)
            self.assertEqual(target.read_text(encoding="utf-8"), fake)
            self.assertNotIn(fake, str(logged.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
