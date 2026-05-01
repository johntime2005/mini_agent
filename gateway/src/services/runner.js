import { SANDBOX_MODULE } from '../config/env.js';
import {
  appendContextHistory,
  buildContextEntry,
  clearContextHistory,
} from './contextHistory.js';
import {
  cleanupSandboxSession,
  createSandboxSession,
  runSandboxScript,
  writeSandboxFile,
} from './sandboxCli.js';
import { clearSessionCleanup, scheduleSessionCleanup } from './sessionCleanup.js';

export async function runCodeInSandbox({
  sessionId,
  fileName,
  code,
  timeoutMs,
  scriptArgs = [],
  ownedSession,
}) {
  const shouldCleanupOwnedSession = ownedSession ?? !sessionId;
  const session = sessionId ? { session_id: sessionId } : await createSandboxSession();
  let cleanupAt = null;

  if (!shouldCleanupOwnedSession) {
    cleanupAt = scheduleSessionCleanup(session.session_id);
  }

  try {
    const writeResult = await writeSandboxFile(session.session_id, fileName, code);
    const commandPreview = [
      `python -m ${SANDBOX_MODULE} run ${session.session_id} ${fileName}`,
      ...scriptArgs,
      '--timeout-ms',
      String(timeoutMs),
    ].join(' ');

    await appendContextHistory(
      buildContextEntry({
        sessionId: session.session_id,
        type: 'command',
        content: commandPreview,
        metadata: {
          fileName,
          scriptArgs,
          timeoutMs,
        },
      }),
    );

    const execution = await runSandboxScript(session.session_id, fileName, timeoutMs, scriptArgs);

    await appendContextHistory(
      buildContextEntry({
        sessionId: session.session_id,
        type: 'command_result',
        content: JSON.stringify(
          {
            success: execution.success,
            exit_code: execution.exit_code,
            stdout: execution.stdout,
            stderr: execution.stderr,
            timeout: execution.timeout,
            duration_ms: execution.duration_ms,
            truncated: execution.truncated,
          },
          null,
          2,
        ),
      }),
    );

    return {
      sessionId: session.session_id,
      fileName,
      filePath: writeResult.path,
      timeoutMs,
      execution,
      sessionCleanup: shouldCleanupOwnedSession
        ? { mode: 'immediate', cleanup_at: null }
        : { mode: 'ttl', cleanup_at: cleanupAt },
    };
  } finally {
    if (shouldCleanupOwnedSession) {
      clearSessionCleanup(session.session_id);
      try {
        await cleanupSandboxSession(session.session_id);
        await clearContextHistory({ sessionId: session.session_id });
      } catch (_error) {
        // Ignore cleanup failures for ephemeral sessions.
      }
    }
  }
}
