#!/usr/bin/env python3
"""Same-origin server deployment; Python 3.6+, Docker Compose 2.24.4+."""
import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def load_env(path):
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            result[key] = value.strip().strip('"').strip("'")
    return result


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Use the final HTTPS origin without a trailing slash or path.')
    parsed.port  # Validate the port.
    return value


def private_write(path, content):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(content)


def configure(args):
    origin(args.url)
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,50}', args.project):
        raise ValueError('Invalid Compose project name.')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Internal port must be 1024..65535.')
    if not re.fullmatch(r'172\.(?:1[6-9]|2[0-9]|3[01])\.(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])', args.edge_prefix):
        raise ValueError('Use a private 172.16..31 /24 edge prefix.')
    data = Path(args.data_dir).expanduser().resolve()
    backups = Path(args.backup_dir).expanduser().resolve()
    for value in [args.url, str(data), str(backups)]:
        if any(c in value for c in '\n\r\"\'$#'):
            raise ValueError('Unsupported character in deployment configuration.')
    if args.env_file.exists():
        raise ValueError('Configuration already exists; refusing to replace credentials.')
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = (ROOT / '.env.example').read_text()
    for key in ['APP_DB_PASSWORD', 'KEYCLOAK_DB_PASSWORD', 'POSTGRES_ADMIN_PASSWORD',
                'KEYCLOAK_ADMIN_PASSWORD', 'WEB_CLIENT_SECRET', 'PROVISIONER_CLIENT_SECRET']:
        content = content.replace('__' + key + '__', secrets.token_hex(24))
    content = content.replace('__NEWAPI_MANAGEMENT_TOKEN__', 'nap_' + secrets.token_hex(32))
    content = content.replace('__NEWAPI_SESSION_SECRET__', secrets.token_hex(32))
    content = content.replace('__SESSION_ENCRYPTION_KEY__',
                              base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    overrides = {
        'COMPOSE_PROJECT_NAME': args.project,
        'ACTVERO_PLATFORM_EDITION': 'saas',
        'ACTVERO_APP_URL': args.url,
        'ACTVERO_OIDC_ISSUER': args.url + '/identity/realms/actvero',
        'ACTVERO_APP_PORT': str(args.port),
        'ACTVERO_EDGE_PREFIX': args.edge_prefix,
        'ACTVERO_DATA_DIR': str(data),
        'ACTVERO_BACKUP_DIR': str(backups),
        'ACTVERO_SESSION_COOKIE_NAME': args.project.replace('-', '_') + '_session',
        'ACTVERO_WEB_SESSION_POLICY': 'persistent',
        'ACTVERO_DESKTOP_SESSION_POLICY': 'persistent',
        'ACTVERO_DESKTOP_REAUTHENTICATION_DAYS': '90',
    }
    for key, value in overrides.items():
        if re.search(r'^' + key + '=', content, re.M):
            content = re.sub(r'^' + key + r'=.*$', key + '=' + value, content, flags=re.M)
        else:
            content += '\n' + key + '=' + value + '\n'
    private_write(args.env_file, content)
    print('Created private server configuration. No platform account was initialized.')


class Server:
    def __init__(self, path):
        self.path = path
        self.values = load_env(path)
        self.environment = os.environ.copy()
        self.release = subprocess.check_output(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=str(ROOT)).decode().strip()
        self.environment['ACTVERO_RELEASE_ID'] = self.release
        if subprocess.call(['docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            self.docker = ['docker']
        else:
            self.docker = ['sudo', '-n', 'docker']
        self.compose = self.docker + ['compose', '--env-file', str(path)]
        for name in ['compose.yaml', 'deploy/same-origin.compose.yaml', 'deploy/server.compose.yaml']:
            self.compose += ['-f', str(ROOT / name)]

    def run(self, args, capture=False, **kwargs):
        command = self.compose + args
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE if capture else None
        return subprocess.run(command, cwd=str(ROOT), env=self.environment, check=True, **kwargs)

    def running(self):
        return self.run(['ps', '--status', 'running', '--services'], capture=True).stdout.decode().splitlines()

    def verify(self):
        app_url = origin(self.values['ACTVERO_APP_URL'])
        authority = urlsplit(app_url).netloc
        loopback = 'http://127.0.0.1:' + self.values['ACTVERO_APP_PORT']
        for path in ['/api/v1/ready', '/download', '/login',
                     '/identity/realms/actvero/.well-known/openid-configuration']:
            with urlopen(Request(loopback + path, headers={'Host': authority}), timeout=20) as response:
                body = response.read()
                if response.status != 200:
                    raise ValueError('Health check failed: ' + path)
                if 'openid-configuration' in path:
                    if json.loads(body)['issuer'] != app_url + '/identity/realms/actvero':
                        raise ValueError('Public identity issuer mismatch.')
        self.run(['ps', '--all'])
        print('Local app, download, login and same-origin OIDC checks passed.')
        print('Public HTTPS must also be verified through the host reverse proxy.')

    def backup(self):
        stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S%fZ')
        target = Path(self.values['ACTVERO_BACKUP_DIR']) / stamp
        target.mkdir(parents=True, mode=0o700)
        services = ['edge', 'app', 'keycloak'] + (['newapi'] if self.managed_gateway() else [])
        stopped = [s for s in services if s in self.running()]
        if stopped:
            self.run(['stop'] + stopped)
        self.backup_outbox(target)
        if self.managed_gateway():
            containers = self.run(['ps', '--all', '--quiet', 'newapi'], capture=True).stdout.decode().split()
            if containers:
                destination = target / 'newapi'
                self.run(['cp', '-a', 'newapi:/data', str(destination)])
                for entry in [destination] + list(destination.rglob('*')):
                    if entry.is_symlink():
                        raise ValueError('Unexpected gateway backup symlink; backup refused.')
                    os.chmod(str(entry), 0o700 if entry.is_dir() else 0o600)
        shutil.copy2(str(self.path), str(target / 'environment'))
        os.chmod(str(target / 'environment'), 0o600)
        for db in ['actvero', 'actvero_identity']:
            dump = target / (db + '.dump')
            with dump.open('xb') as output:
                os.chmod(str(dump), 0o600)
                self.run(['exec', '-T', 'postgres', 'pg_dump', '-U', 'postgres', '-Fc', db], stdout=output)
            with dump.open('rb') as source:
                listing = self.run(['exec', '-T', 'postgres', 'pg_restore', '--list'], capture=True, stdin=source)
            (target / (db + '.toc')).write_bytes(listing.stdout)
            os.chmod(str(target / (db + '.toc')), 0o600)
        previous = ROOT / '.local/server-release.json'
        if previous.exists():
            shutil.copy2(str(previous), str(target / 'previous-release.json'))
        for name in ['compose.yaml', 'deploy/same-origin.compose.yaml', 'deploy/server.compose.yaml']:
            shutil.copy2(str(ROOT / name), str(target / Path(name).name))
        print('Consistent database/configuration backup: ' + str(target))
        print('Archives were read successfully; full restore has not been rehearsed.')
        return str(target)

    def backup_outbox(self, target):
        """Copy the stopped app's durable accounting journal beside its DB dump."""
        containers = self.run(['ps', '--all', '--quiet', 'app'], capture=True).stdout.decode().split()
        manifest = {'present': False, 'files': {}}
        if containers:
            metadata = json.loads(subprocess.check_output(self.docker + ['inspect', containers[0]]))[0]
            journal = '/app/data/llm-outbox'
            if any(m.get('Destination') == journal for m in metadata.get('Mounts', [])):
                destination = target / 'llm-outbox'
                self.run(['cp', '-a', 'app:' + journal, str(destination)])
                os.chmod(str(destination), 0o700)
                manifest['present'] = True
                for entry in destination.iterdir():
                    if entry.is_symlink() or not entry.is_file():
                        raise ValueError('Unexpected accounting journal entry; backup refused.')
                    os.chmod(str(entry), 0o600)
                    manifest['files'][entry.name] = hashlib.sha256(entry.read_bytes()).hexdigest()
        private_write(target / 'llm-outbox-manifest.json', json.dumps(manifest, indent=2) + '\n')

    def managed_gateway(self):
        profiles = getattr(self, 'environment', {}).get(
            'COMPOSE_PROFILES', getattr(self, 'values', {}).get('COMPOSE_PROFILES', ''))
        return 'gateway' in re.split(r'[,\s]+', profiles)

    def start(self, no_build=False):
        self.run(['config', '--quiet'])
        if not no_build:
            self.run(['build', 'postgres'])
            self.run(['build', 'app'])
            self.run(['build', 'keycloak'])
            if self.managed_gateway():
                self.run(['build', 'newapi'])
        backup = None
        if 'postgres' in self.running():
            backup = self.backup()
        self.run(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '300', 'postgres'])
        self.run(['run', '--rm', '--no-deps', 'migrate'])
        # Recreate stopped old app/identity and edge after migrations; keep database intact.
        self.run(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '300'])
        self.verify()
        metadata = {'commit': self.release, 'url': self.values['ACTVERO_APP_URL'],
                    'backup': backup, 'verified_at_utc': datetime.datetime.utcnow().isoformat() + 'Z'}
        (ROOT / '.local/server-release.json').write_text(json.dumps(metadata, indent=2) + '\n')


def update_git(bundle=None):
    def git(*args):
        return subprocess.check_output(['git'] + list(args), cwd=str(ROOT)).decode().strip()
    if git('status', '--porcelain'):
        raise ValueError('Repository has local changes; update refused without deleting them.')
    if git('branch', '--show-current') != 'main':
        raise ValueError('Server upgrades require the main branch.')
    if bundle:
        subprocess.check_call(['git', 'bundle', 'verify', str(bundle)], cwd=str(ROOT))
        subprocess.check_call(['git', 'fetch', str(bundle), 'refs/remotes/origin/main:refs/remotes/origin/main'], cwd=str(ROOT))
    else:
        subprocess.check_call(['git', 'fetch', 'origin', 'main'], cwd=str(ROOT))
    if subprocess.call(['git', 'merge-base', '--is-ancestor', 'HEAD', 'origin/main'], cwd=str(ROOT)):
        raise ValueError('Local history diverged from main; no reset or force update performed.')
    subprocess.check_call(['git', 'merge', '--ff-only', 'origin/main'], cwd=str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.server')
    sub = parser.add_subparsers(dest='action')
    config = sub.add_parser('configure')
    config.add_argument('--url', required=True)
    config.add_argument('--project', default='actvero-server')
    config.add_argument('--port', type=int, default=5194)
    config.add_argument('--edge-prefix', default='172.30.194')
    config.add_argument('--data-dir', default=str(Path.home() / 'data/actvero'))
    config.add_argument('--backup-dir', default=str(Path.home() / 'backups/actvero'))
    for action in ['up', 'upgrade']:
        child = sub.add_parser(action)
        child.add_argument('--no-build', action='store_true')
        if action == 'upgrade':
            child.add_argument('--bundle', type=Path)
    for action in ['status', 'logs', 'check', 'stop']:
        sub.add_parser(action)
    args = parser.parse_args()
    if not args.action:
        parser.error('Choose an action.')
    args.env_file = args.env_file.expanduser().resolve()
    local = ROOT / '.local'
    local.mkdir(exist_ok=True, mode=0o700)
    with (local / 'server.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'Another server operation is running.\n')
        if args.action == 'configure':
            configure(args)
            return
        if args.action == 'upgrade':
            update_git(args.bundle)
            command = [sys.executable, str(ROOT / 'scripts/server.py'), '--env-file', str(args.env_file), 'up']
            if args.no_build:
                command.append('--no-build')
            os.execv(sys.executable, command)
        server = Server(args.env_file)
        if args.action in ['up', 'upgrade']:
            server.start(args.no_build)
        elif args.action == 'status':
            server.run(['ps', '--all'])
        elif args.action == 'logs':
            server.run(['logs', '--follow', '--tail', '80', 'app', 'migrate', 'keycloak', 'edge'] + (['newapi'] if server.managed_gateway() else []))
        elif args.action == 'check':
            server.verify()
        elif args.action == 'stop':
            server.run(['stop'])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        # Do not echo environment values, database URLs, or child process output.
        print('Server operation failed: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        print('No database reset or automatic restore was attempted. Inspect the service logs and backup before continuing.', file=sys.stderr)
        sys.exit(1)
