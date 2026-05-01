import { Router } from 'express';

import { clearContextHistory } from '../services/contextHistory.js';
import {
  cleanupSandboxSession,
  createSandboxSession,
} from '../services/sandboxCli.js';
import {
  clearSessionCleanup,
  scheduleSessionCleanup,
} from '../services/sessionCleanup.js';
import { getStatusCode } from '../utils/http.js';

function buildSessionResponse(session, cleanupAt = null) {
  return {
    ...session,
    cleanup_at: cleanupAt,
  };
}

const router = Router();

router.post('/sandbox/sessions', async (_req, res) => {
  try {
    const session = await createSandboxSession();
    const cleanupAt = scheduleSessionCleanup(session.session_id);
    res.status(201).json(buildSessionResponse(session, cleanupAt));
  } catch (error) {
    res.status(getStatusCode(error)).json({ error: error.message });
  }
});

router.delete('/sandbox/sessions/:sessionId', async (req, res) => {
  try {
    clearSessionCleanup(req.params.sessionId);
    const result = await cleanupSandboxSession(req.params.sessionId);
    await clearContextHistory({ sessionId: req.params.sessionId });
    res.json(result);
  } catch (error) {
    res.status(getStatusCode(error)).json({ error: error.message });
  }
});

export default router;
