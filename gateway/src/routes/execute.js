import { Router } from 'express';

import {
  DEFAULT_CONTEXT_HISTORY_LIMIT,
  DEFAULT_FILE_NAME,
  DEFAULT_TIMEOUT_MS,
} from '../config/env.js';
import {
  appendContextHistory,
  buildContextEntry,
  clearContextHistory,
} from '../services/contextHistory.js';
import { generatePythonCode } from '../services/llm.js';
import { runCodeInSandbox } from '../services/runner.js';
import {
  cleanupSandboxSession,
  createSandboxSession,
} from '../services/sandboxCli.js';
import { clearSessionCleanup } from '../services/sessionCleanup.js';
import { getStatusCode } from '../utils/http.js';
import { clampHistoryLimit, clampTimeout } from '../utils/numbers.js';

const router = Router();

function validateCommonBody({ fileName, scriptArgs }) {
  if (typeof fileName !== 'string' || !fileName.endsWith('.py')) {
    return 'fileName must be a .py file';
  }

  if (!Array.isArray(scriptArgs) || scriptArgs.some((item) => typeof item !== 'string')) {
    return 'scriptArgs must be an array of strings';
  }

  return null;
}

async function abandonOwnedSession(sessionId) {
  if (!sessionId) {
    return;
  }

  clearSessionCleanup(sessionId);
  try {
    await cleanupSandboxSession(sessionId);
    await clearContextHistory({ sessionId });
  } catch (_cleanupError) {
    // Ignore cleanup failures while handling the primary error.
  }
}

router.post('/execute-code', async (req, res) => {
  const {
    code,
    sessionId,
    fileName = DEFAULT_FILE_NAME,
    timeoutMs,
    scriptArgs = [],
  } = req.body ?? {};

  if (typeof code !== 'string' || !code.trim()) {
    res.status(400).json({ error: 'code is required' });
    return;
  }

  const validationError = validateCommonBody({ fileName, scriptArgs });
  if (validationError) {
    res.status(400).json({ error: validationError });
    return;
  }

  const effectiveTimeout = clampTimeout(Number(timeoutMs ?? DEFAULT_TIMEOUT_MS));
  let effectiveSessionId = sessionId || null;
  const ownedSession = !sessionId;

  try {
    if (!effectiveSessionId) {
      effectiveSessionId = (await createSandboxSession()).session_id;
    }

    await appendContextHistory(
      buildContextEntry({
        sessionId: effectiveSessionId,
        type: 'user_instruction',
        content: code,
        metadata: {
          mode: 'execute-code',
          fileName,
          scriptArgs,
        },
      }),
    );

    const result = await runCodeInSandbox({
      sessionId: effectiveSessionId,
      fileName,
      code,
      timeoutMs: effectiveTimeout,
      scriptArgs,
      ownedSession,
    });

    res.json({
      ...result,
      code,
    });
  } catch (error) {
    if (ownedSession) {
      await abandonOwnedSession(effectiveSessionId);
    }
    res.status(getStatusCode(error)).json({ error: error.message });
  }
});

router.post('/generate-and-run', async (req, res) => {
  const {
    prompt,
    sessionId,
    fileName = DEFAULT_FILE_NAME,
    timeoutMs,
    scriptArgs = [],
    contextLimit,
  } = req.body ?? {};

  if (typeof prompt !== 'string' || !prompt.trim()) {
    res.status(400).json({ error: 'prompt is required' });
    return;
  }

  const validationError = validateCommonBody({ fileName, scriptArgs });
  if (validationError) {
    res.status(400).json({ error: validationError });
    return;
  }

  const effectiveTimeout = clampTimeout(Number(timeoutMs ?? DEFAULT_TIMEOUT_MS));
  const effectiveContextLimit = clampHistoryLimit(
    Number(contextLimit ?? DEFAULT_CONTEXT_HISTORY_LIMIT),
  );
  let effectiveSessionId = sessionId || null;
  const ownedSession = !sessionId;

  try {
    if (!effectiveSessionId) {
      effectiveSessionId = (await createSandboxSession()).session_id;
    }

    const generatedCode = await generatePythonCode(prompt, {
      contextLimit: effectiveContextLimit,
      sessionId: effectiveSessionId,
    });

    await appendContextHistory(
      buildContextEntry({
        sessionId: effectiveSessionId,
        type: 'user_instruction',
        content: prompt,
        metadata: {
          mode: 'generate-and-run',
          fileName,
          scriptArgs,
        },
      }),
    );

    const result = await runCodeInSandbox({
      sessionId: effectiveSessionId,
      fileName,
      code: generatedCode,
      timeoutMs: effectiveTimeout,
      scriptArgs,
      ownedSession,
    });

    res.json({
      ...result,
      generatedCode,
    });
  } catch (error) {
    if (ownedSession) {
      await abandonOwnedSession(effectiveSessionId);
    }
    res.status(getStatusCode(error)).json({ error: error.message });
  }
});

export default router;
