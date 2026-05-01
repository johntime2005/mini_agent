import { Router } from 'express';

import {
  DEFAULT_CONTEXT_HISTORY_LIMIT,
  GATEWAY_CONFIG_PATH,
  SESSION_TTL_MS,
} from '../config/env.js';

const router = Router();

router.get('/health', (_req, res) => {
  res.json({
    ok: true,
    sessionTtlMs: SESSION_TTL_MS,
    configPath: GATEWAY_CONFIG_PATH,
    contextHistoryLimit: DEFAULT_CONTEXT_HISTORY_LIMIT,
  });
});

export default router;
