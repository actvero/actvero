#!/usr/bin/env python3
"""Fetch committed main and build on the operator computer; servers need no GitHub credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
EDGE_IMAGE = 'nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236'
MAIL_IMAGE = 'axllent/mailpit:v1.27.8'


def transport_images(images, ssh, docker):
    processes = []
    try:
        save = subprocess.Popen(['docker', 'image', 'save', '--platform', 'linux/amd64'] + images, stdout=subprocess.PIPE)
        processes.append(save)
        compress = subprocess.Popen(['gzip', '-6'], stdin=save.stdout, stdout=subprocess.PIPE)
        processes.append(compress)
        save.stdout.close()
        load = subprocess.Popen(ssh + ['bash -o pipefail -c ' +
            shlex.quote('gzip -d | ' + docker + ' load')], stdin=compress.stdout)
        processes.append(load)
        compress.stdout.close()
        # Check every stage: a truncated stream must never proceed to migration.
        statuses = [process.wait() for process in reversed(processes)]
        if any(statuses):
            raise ValueError('Image transport failed; the running server was not upgraded.')
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait()


def prepare_images(commit, temporary, project, ssh):
    source = Path(temporary) / 'source'
    source.mkdir()
    archive = Path(temporary) / 'source.tar'
    subprocess.check_call(['git', 'archive', '--format=tar', '--output=' + str(archive), commit], cwd=str(ROOT))
    subprocess.check_call(['tar', '-xf', str(archive), '-C', str(source)])
    release = commit[:12]
    images = []
    for kind, dockerfile, target in [
        ('database', 'deploy/Dockerfile.database', None),
        ('app', 'deploy/Dockerfile', 'app'),
        ('identity', 'deploy/Dockerfile', 'identity')
    ]:
        image = 'actvero-release-' + kind + ':' + release
        command = ['docker', 'buildx', 'build', '--platform', 'linux/amd64', '--load',
                   '--label', 'org.opencontainers.image.revision=' + commit,
                   '--file', dockerfile, '--tag', image]
        if target:
            command += ['--target', target]
        subprocess.check_call(command + ['.'], cwd=str(source))
        images.append(image)
    for image in [EDGE_IMAGE, MAIL_IMAGE]:
        subprocess.check_call(['docker', 'pull', '--platform', 'linux/amd64', image])
    docker = subprocess.check_output(ssh + [
        'if docker info >/dev/null 2>&1; then printf docker; else sudo -n docker info >/dev/null && printf "sudo -n docker"; fi'
    ]).decode().strip()
    if docker not in ['docker', 'sudo -n docker']:
        raise ValueError('Docker access is unavailable on the server.')
    transport_images(images + [EDGE_IMAGE, MAIL_IMAGE], ssh, docker)
    # Validate the loaded revision/architecture before assigning Compose release names.
    for kind, image in zip(['database', 'app', 'identity'], images):
        metadata = json.loads(subprocess.check_output(ssh + [docker + ' image inspect ' + shlex.quote(image)]))[0]
        if (metadata['Architecture'] != 'amd64' or
                metadata['Config']['Labels'].get('org.opencontainers.image.revision') != commit):
            raise ValueError('Loaded image revision or architecture mismatch.')
        subprocess.check_call(ssh + [docker + ' tag ' + shlex.quote(image) + ' ' +
            shlex.quote(project + '-' + kind + ':' + release)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--path', required=True, help='Absolute repository path on the server.')
    parser.add_argument('--build-on-server', action='store_true',
                        help='Optional fallback when the operator computer has no Docker.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.host):
        parser.error('Use a configured SSH host alias.')
    path = args.path
    if not path or not path.startswith('/') or any(c in path for c in '\n\r'):
        parser.error('Provide the absolute server repository path.')
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', args.host]
    preflight = """import json, platform, runpy, subprocess
from pathlib import Path
module = runpy.run_path('scripts/server.py', run_name='deployment_preflight')
values = module['load_env'](Path('.env.server'))
assert subprocess.check_output(['git', 'branch', '--show-current']).strip() == b'main', 'Server branch must be main'
assert not subprocess.check_output(['git', 'status', '--porcelain']).strip(), 'Server repository has local changes'
print(json.dumps({'project': values['COMPOSE_PROJECT_NAME'], 'architecture': platform.machine()}))
"""
    metadata = json.loads(subprocess.check_output(ssh + ['cd ' + shlex.quote(path) +
        ' && python3 -c ' + shlex.quote(preflight)]))
    project = metadata['project']
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,50}', project):
        raise ValueError('Invalid server Compose project.')
    if not args.build_on_server and metadata['architecture'] != 'x86_64':
        raise ValueError('Prebuilt transfer currently supports x86_64 servers only.')
    subprocess.check_call(['git', 'fetch', 'origin', 'main'], cwd=str(ROOT))
    commit = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=str(ROOT)).decode().strip()
    with tempfile.TemporaryDirectory(prefix='actvero-release-') as temporary:
        bundle = Path(temporary) / 'main.bundle'
        subprocess.check_call(['git', 'bundle', 'create', str(bundle), 'refs/remotes/origin/main'], cwd=str(ROOT))
        heads = subprocess.check_output(['git', 'bundle', 'list-heads', str(bundle)], cwd=str(ROOT)).decode().split()
        if heads != [commit, 'refs/remotes/origin/main']:
            raise ValueError('Fetched main changed while preparing the release; retry.')
        if not args.build_on_server:
            prepare_images(commit, temporary, project, ssh)
        checksum = hashlib.sha256(bundle.read_bytes()).hexdigest()
        remote = path + '/.local/incoming-' + uuid.uuid4().hex + '.bundle'
        subprocess.check_call(ssh + ['mkdir -p ' + shlex.quote(path + '/.local')])
        try:
            subprocess.check_call(['scp', '-q', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                   str(bundle), args.host + ':' + shlex.quote(remote)])
            actual = subprocess.check_output(ssh + ['sha256sum ' + shlex.quote(remote)]).decode().split()[0]
            if actual != checksum:
                raise ValueError('Bundle transport checksum mismatch.')
            subprocess.check_call(ssh + ['cd ' + shlex.quote(path) +
                ' && python3 scripts/server.py upgrade --bundle ' + shlex.quote(remote) +
                ('' if args.build_on_server else ' --no-build')])
        finally:
            subprocess.call(ssh + ['rm -f -- ' + shlex.quote(remote)])


if __name__ == '__main__':
    main()
