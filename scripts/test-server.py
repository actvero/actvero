"""Deployment contract tests without contacting any running service."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('server', Path(__file__).with_name('server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ConfigureTests(unittest.TestCase):
    def args(self, root, **overrides):
        values = dict(url='https://192.0.2.1:8445', project='actvero-test', port=5194,
                      edge_prefix='172.30.210', env_file=root / '.env.server',
                      data_dir=str(root / 'data'), backup_dir=str(root / 'backups'))
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_new_configuration_has_independent_secrets_and_no_account(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = self.args(root)
            server.configure(args)
            env = server.load_env(args.env_file)
            self.assertEqual(env['ACTVERO_PLATFORM_EDITION'], 'saas')
            self.assertEqual(env['ACTVERO_OIDC_ISSUER'], args.url + '/identity/realms/actvero')
            self.assertEqual(env['ACTVERO_WEB_SESSION_POLICY'], 'persistent')
            self.assertNotIn('__APP_DB_PASSWORD__', args.env_file.read_text())
            self.assertEqual(args.env_file.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                server.configure(args)
            self.assertEqual(env, server.load_env(args.env_file))

    def test_rejects_non_origin_before_creating_credentials(self):
        for url in ['http://example.com', 'https://example.com/', 'https://user@example.com',
                    'https://example.com/a', 'https://example.com?x=1']:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaises(ValueError):
                    server.configure(self.args(root, url=url))
                self.assertFalse((root / '.env.server').exists())

    def test_rejects_project_and_environment_injection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for overrides in [{'project': 'other;delete'}, {'port': 543},
                              {'edge_prefix': '8.8.8'}, {'data_dir': '/tmp/${HOME}'}]:
                with self.assertRaises(ValueError):
                    server.configure(self.args(root, **overrides))


class UpdateTests(unittest.TestCase):
    def test_dirty_or_wrong_branch_never_fetches_or_resets(self):
        for outputs in [[b' M compose.yaml'], [b'', b'work']]:
            with patch.object(server.subprocess, 'check_output', side_effect=outputs), \
                 patch.object(server.subprocess, 'check_call') as call:
                with self.assertRaises(ValueError):
                    server.update_git()
                call.assert_not_called()

    def test_diverged_branch_only_fetches_and_refuses_merge(self):
        with patch.object(server.subprocess, 'check_output', side_effect=[b'', b'main']), \
             patch.object(server.subprocess, 'check_call') as call, \
             patch.object(server.subprocess, 'call', return_value=1):
            with self.assertRaises(ValueError):
                server.update_git()
            self.assertEqual(call.call_args[0][0], ['git', 'fetch', 'origin', 'main'])


class StartTests(unittest.TestCase):
    def instance(self):
        instance = object.__new__(server.Server)
        instance.run = lambda *args, **kwargs: None
        instance.running = lambda: ['postgres', 'app', 'keycloak', 'edge']
        instance.verify = lambda: None
        return instance

    def test_backup_failure_never_migrates_or_starts_new_image(self):
        instance = self.instance()
        calls = []
        instance.run = lambda args, **kwargs: calls.append(args)
        instance.backup = lambda: (_ for _ in ()).throw(OSError('disk full'))
        with self.assertRaises(OSError):
            instance.start(no_build=True)
        self.assertEqual(calls, [['config', '--quiet']])

    def test_build_failure_keeps_running_services_untouched(self):
        instance = self.instance()
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[0] == 'build':
                raise OSError('build failed')
        instance.run = run
        with patch.object(instance, 'backup') as backup:
            with self.assertRaises(OSError):
                instance.start()
            backup.assert_not_called()
        self.assertFalse(any(c[0] in ['stop', 'run', 'up'] for c in calls))

    def test_migration_failure_never_starts_application(self):
        instance = self.instance()
        calls = []
        instance.backup = lambda: '/backup'
        def run(args, **kwargs):
            calls.append(args)
            if args[0] == 'run':
                raise OSError('migration failed')
        instance.run = run
        with self.assertRaises(OSError):
            instance.start(no_build=True)
        self.assertEqual(calls[-1], ['run', '--rm', '--no-deps', 'migrate'])
        self.assertEqual(sum(c[0] == 'up' for c in calls), 1)

    def test_dump_output_is_streamed_to_file(self):
        instance = object.__new__(server.Server)
        instance.compose = ['docker', 'compose']
        instance.environment = {}
        with patch.object(server.subprocess, 'run') as run:
            instance.run(['exec', 'postgres', 'pg_dump'], stdout='file-object')
            self.assertEqual(run.call_args[1]['stdout'], 'file-object')

    def test_accounting_journal_backup_preserves_pending_record_and_checksum(self):
        instance = self.instance()
        instance.docker = ['docker']
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            def run(args, **kwargs):
                if args[0] == 'ps':
                    return SimpleNamespace(stdout=b'app-id\n')
                self.assertEqual(args[:3], ['cp', '-a', 'app:/app/data/llm-outbox'])
                destination = Path(args[3])
                destination.mkdir()
                (destination / 'pending.json').write_text('{"complete":false}')
            instance.run = run
            metadata = json.dumps([{'Mounts': [{'Destination': '/app/data/llm-outbox'}]}]).encode()
            with patch.object(server.subprocess, 'check_output', return_value=metadata):
                instance.backup_outbox(target)
            journal = target / 'llm-outbox/pending.json'
            manifest = json.loads((target / 'llm-outbox-manifest.json').read_text())
            self.assertTrue(manifest['present'])
            self.assertEqual(manifest['files']['pending.json'], server.hashlib.sha256(journal.read_bytes()).hexdigest())
            self.assertEqual(journal.stat().st_mode & 0o777, 0o600)

    def test_pre_journal_release_records_absence_without_copying_missing_path(self):
        instance = self.instance()
        instance.docker = ['docker']
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(stdout=b'app-id\n')
        instance.run = run
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(server.subprocess, 'check_output', return_value=b'[{"Mounts":[]}]'):
                instance.backup_outbox(Path(temp))
            self.assertEqual(calls, [['ps', '--all', '--quiet', 'app']])
            self.assertFalse(json.loads((Path(temp) / 'llm-outbox-manifest.json').read_text())['present'])


if __name__ == '__main__':
    unittest.main()
