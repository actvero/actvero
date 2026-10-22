# Third-party notices

Actvero CLI is licensed under MIT. Dependencies retain their own licenses and notices. The exact dependency graph is recorded in `package-lock.json`.

| Package | Purpose | License | Upstream |
| --- | --- | --- | --- |
| commander | Command parsing and help | MIT | https://github.com/tj/commander.js |
| @napi-rs/keyring | Native operating-system credential storage | MIT | https://github.com/Brooooooklyn/keyring-node |
| open | Launch the default browser for OIDC login | MIT | https://github.com/sindresorhus/open |
| proper-lockfile | Serialize CLI session updates across processes | MIT | https://github.com/moxystudio/node-proper-lockfile |
| TypeScript | Compile and check TypeScript sources | Apache-2.0 | https://github.com/microsoft/TypeScript |
| @types/node, @types/proper-lockfile | Development-time type declarations | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |

Platform API behavior is implemented by the MIT-licensed [Actvero platform](https://github.com/actvero/actvero). Native keyring packages and transitive dependencies are installed by npm with their distributed license files; they are not vendored into this source repository.
