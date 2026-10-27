"""Failure boundaries for operator-side releases; no live service requests."""
import importlib.util
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('remote', Path(__file__).with_name('server-remote.py'))
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


class ReleaseTests(unittest.TestCase):
    def test_missing_server_path_fails_before_network_access(self):
        with patch('sys.argv', ['server-remote.py', '--host', 'deployment-host']), \
             patch.object(remote.subprocess, 'check_output') as network, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                remote.main()
            self.assertEqual(error.exception.code, 2)
            network.assert_not_called()

    def test_stream_failure_is_detected_even_when_loader_exits_successfully(self):
        processes = []
        for status in [1, 0, 0]:
            process = Mock()
            process.wait.return_value = status
            process.poll.return_value = status
            processes.append(process)
        with patch.object(remote.subprocess, 'Popen', side_effect=processes) as popen:
            with self.assertRaises(ValueError):
                remote.transport_images(['release:commit'], ['ssh', 'server'], 'docker')
            self.assertIn('--platform', popen.call_args_list[0][0][0])
            self.assertIn('linux/amd64', popen.call_args_list[0][0][0])

    def test_failed_build_never_transfers_images(self):
        with tempfile.TemporaryDirectory() as temp:
            def call(command, **kwargs):
                if command[:3] == ['docker', 'buildx', 'build']:
                    raise OSError('build failed')
            with patch.object(remote.subprocess, 'check_call', side_effect=call), \
                 patch.object(remote, 'transport_images') as transport:
                with self.assertRaises(OSError):
                    remote.prepare_images('a' * 40, temp, 'actvero-test', ['ssh', 'server'])
                transport.assert_not_called()

    def test_source_export_uses_fixed_commit_and_loaded_image_must_match(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            metadata = json.dumps([{'Architecture':'amd64', 'Config': {'Labels': {'org.opencontainers.image.revision': 'wrong'}}}]).encode()
            with patch.object(remote.subprocess, 'check_call') as call, \
                 patch.object(remote.subprocess, 'check_output', side_effect=[b'docker', metadata]), \
                 patch.object(remote, 'transport_images'):
                with self.assertRaises(ValueError):
                    remote.prepare_images('a' * 40, temp, 'actvero-test', ['ssh', 'server'])
                archive = call.call_args_list[0][0][0]
                self.assertEqual(archive[-1], 'a' * 40)
                self.assertFalse(any(' tag ' in str(entry) for entry in call.call_args_list))

    def test_gateway_profile_transfers_and_verifies_the_gateway_image(self):
        import json
        for managed, count in [(False, 3), (True, 4)]:
            with self.subTest(managed=managed), tempfile.TemporaryDirectory() as temp:
                commit = 'a' * 40
                metadata = json.dumps([{'Architecture': 'amd64', 'Config': {
                    'Labels': {'org.opencontainers.image.revision': commit}}}]).encode()
                with patch.object(remote.subprocess, 'check_call') as call, \
                     patch.object(remote.subprocess, 'check_output', side_effect=[b'docker'] + [metadata] * count), \
                     patch.object(remote, 'transport_images') as transport:
                    remote.prepare_images(commit, temp, 'actvero-test', ['ssh', 'server'], managed)
                builds = [entry.args[0] for entry in call.call_args_list
                          if entry.args[0][:3] == ['docker', 'buildx', 'build']]
                self.assertEqual(len(builds), count)
                self.assertEqual(len(transport.call_args.args[0]), count + 2)
                if managed:
                    self.assertEqual(builds[-1][-1], 'integrations/newapi')
                    self.assertIn('integrations/newapi/Dockerfile', builds[-1])
                    self.assertIn('actvero-release-newapi:' + commit[:12], transport.call_args.args[0])
                    self.assertTrue(any('actvero-test-newapi:' in str(entry) for entry in call.call_args_list))


if __name__ == '__main__':
    unittest.main()
