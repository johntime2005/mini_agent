import { spawn } from 'node:child_process';

import { PYTHON_BIN, SANDBOX_MODULE, sandboxRoot } from '../config/env.js';
import { parseJsonOutput } from '../utils/http.js';

function runPythonCli(args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, ['-m', SANDBOX_MODULE, ...args], {
      cwd: sandboxRoot,
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });

    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) {
        resolve({ stdout, stderr, code });
        return;
      }
      reject(new Error(stderr.trim() || stdout.trim() || `sandbox cli exited with code ${code}`));
    });

    if (options.stdin !== undefined) {
      child.stdin.write(options.stdin);
    }
    child.stdin.end();
  });
}

export async function createSandboxSession() {
  const result = await runPythonCli(['create-session']);
  return parseJsonOutput(result.stdout, 'Failed to parse create-session output');
}

export async function writeSandboxFile(sessionId, relativePath, content) {
  const result = await runPythonCli(['write-file', sessionId, relativePath, '--stdin'], {
    stdin: content,
  });
  return parseJsonOutput(result.stdout, 'Failed to parse write-file output');
}

export async function runSandboxScript(sessionId, script, timeoutMs, scriptArgs = []) {
  const result = await runPythonCli([
    'run',
    sessionId,
    script,
    ...scriptArgs,
    '--timeout-ms',
    String(timeoutMs),
  ]);
  return parseJsonOutput(result.stdout, 'Failed to parse run output');
}

export async function cleanupSandboxSession(sessionId) {
  const result = await runPythonCli(['cleanup-session', sessionId]);
  return parseJsonOutput(result.stdout, 'Failed to parse cleanup output');
}
