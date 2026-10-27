"""Render deployment contracts with generated throwaway secrets; never start services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose required')
class GatewayDeploymentTests(unittest.TestCase):
    def render(self, path, profiles):
        environment = os.environ.copy()
        environment['COMPOSE_PROFILES'] = profiles
        return json.loads(subprocess.check_output(
            ['docker', 'compose', '--env-file', str(path), '-f', str(ROOT / 'compose.yaml'),
             'config', '--format', 'json'], cwd=ROOT, env=environment,
        ))

    def test_managed_and_external_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            subprocess.run(['python3', str(ROOT / 'scripts/env.py'), '--output', str(path)], check=True, capture_output=True)
            managed = self.render(path, 'gateway')
            token = managed['services']['newapi']['environment']['ACTVERO_BOOTSTRAP_TOKEN']
            self.assertTrue(token.startswith('nap_') and len(token) >= 48)
            self.assertEqual(token, managed['services']['app']['environment']['ACTVERO_NEWAPI_MANAGEMENT_TOKEN'])
            self.assertNotIn('ports', managed['services']['newapi'])
            self.assertEqual(managed['services']['newapi']['environment']['ACTVERO_ORGANIZATION_ISOLATION'], 'true')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('__NEWAPI_', path.read_text())
            external = self.render(path, '')
            self.assertNotIn('newapi', external['services'])
            self.assertFalse(external['services']['app']['depends_on']['newapi']['required'])


if __name__ == '__main__':
    unittest.main()
