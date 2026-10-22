#!/usr/bin/env node
import { CommanderError } from 'commander';
import { buildProgram } from './commands.js';
import { CliError } from './errors.js';

try {
  await buildProgram().parseAsync(process.argv);
} catch (error) {
  if (error instanceof CommanderError) {
    if (error.exitCode !== 0)
      process.stderr.write(
        JSON.stringify({ error: { code: error.code, message: error.message } }) + '\n',
      );
    process.exitCode = error.exitCode;
  } else {
    const safe =
      error instanceof CliError
        ? error
        : new CliError('command_failed', '命令未完成，请检查输入文件、平台连接与 CLI 版本');
    process.stderr.write(
      JSON.stringify({
        error: {
          code: safe.code,
          message: safe.message,
          status: safe.status,
          request_id: safe.requestId,
        },
      }) + '\n',
    );
    process.exitCode = 1;
  }
}
