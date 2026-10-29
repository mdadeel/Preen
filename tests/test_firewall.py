"""Tests for preen_tool.backend.firewall (UFW toggle)."""
import os
import tempfile
import unittest
from unittest import mock

from preen_tool.backend import firewall, utils


class FirewallTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin_dir = os.path.join(tmp.name, "bin")
        os.makedirs(self.bin_dir)
        self.log_path = os.path.join(tmp.name, "commands.log")
        self._old_path = os.environ.get("PATH")
        os.environ["PATH"] = self.bin_dir + os.pathsep + (self._old_path or "")
        self.addCleanup(self._restore_path)

    def _restore_path(self):
        if self._old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._old_path

    def write_fake(self, name, body):
        path = os.path.join(self.bin_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(path, 0o755)

    def fake_ufw(self, status="inactive"):
        self.write_fake("ufw", "#!/bin/sh\n"
                        "echo \"$@\" >> {}\n"
                        'if [ "$1" = "status" ]; then echo "Status: {}"; fi\n'
                        "exit 0\n".format(self.log_path, status))

    def fake_pkexec(self):
        # pkexec's argv (after $0) is already the command to run.
        self.write_fake("pkexec", '#!/bin/sh\nexec "$@"\n')

    def commands(self):
        try:
            with open(self.log_path, encoding="utf-8") as handle:
                return [line.strip() for line in handle]
        except OSError:
            return []


class UfwEnabledTest(FirewallTestBase):
    def test_parses_active_and_inactive(self):
        self.fake_ufw("active")
        self.assertIs(firewall.ufw_enabled(), True)
        self.fake_ufw("inactive")
        self.assertIs(firewall.ufw_enabled(), False)

    def test_none_when_ufw_is_missing(self):
        # Restore the real PATH: no fake ufw in front of it any more.
        os.environ["PATH"] = self._old_path or os.defpath
        self.assertIsNone(firewall.ufw_enabled())

    def test_none_when_status_fails(self):
        self.write_fake("ufw", "#!/bin/sh\nexit 1\n")
        self.assertIsNone(firewall.ufw_enabled())


class SetUfwTest(FirewallTestBase):
    def test_enable_and_disable_build_ufw_commands(self):
        self.fake_ufw("inactive")
        self.fake_pkexec()
        utils.set_simulate(False)
        try:
            outcome = firewall.set_ufw(True)
            self.assertTrue(outcome.ok, outcome.message)
            outcome = firewall.set_ufw(False)
            self.assertTrue(outcome.ok, outcome.message)
        finally:
            utils.set_simulate(False)
        # The fake logs its arguments ($@), which is "--force enable".
        self.assertIn("--force enable", " ".join(self.commands()))
        self.assertIn("--force disable", " ".join(self.commands()))

    def test_simulate_never_spawns(self):
        self.fake_ufw("inactive")
        utils.set_simulate(True)
        try:
            outcome = firewall.set_ufw(True)
        finally:
            utils.set_simulate(False)
        self.assertTrue(outcome.ok)
        self.assertEqual(self.commands(), [])


if __name__ == "__main__":
    unittest.main()
