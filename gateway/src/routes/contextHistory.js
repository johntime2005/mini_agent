import { Router } from 'express';

import { DEFAULT_CONTEXT_HISTORY_LIMIT } from '../config/env.js';
import {
  clearContextHistory,
  getRecentContextHistory,
} from '../services/contextHistory.js';
import { clampHistoryLimit } from '../utils/numbers.js';

const router = Router();

router.get('/context/history', async (req, res) => {
  try {
    const limit = clampHistoryLimit(Number(req.query.limit ?? DEFAULT_CONTEXT_HISTORY_LIMIT));
    const sessionId =
      typeof req.query.sessionId === 'string' && req.query.sessionId
        ? req.query.sessionId
        : null;
    const history = await getRecentContextHistory({ sessionId, limit });
    res.json({
      sessionId,
      limit,
      size: history.length,
      items: history,
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

router.delete('/context/history', async (req, res) => {
  try {
    const sessionId =
      typeof req.query.sessionId === 'string' && req.query.sessionId
        ? req.query.sessionId
        : null;
    await clearContextHistory({ sessionId });
    res.json({ ok: true, cleared: true, sessionId });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

export default router;
