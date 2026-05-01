import { Router } from 'express';

import { buildGatewayConfigResponse, updateGatewayConfig } from '../services/llm.js';

const router = Router();

router.get('/config/llm', async (_req, res) => {
  try {
    res.json(await buildGatewayConfigResponse());
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

router.put('/config/llm', async (req, res) => {
  try {
    await updateGatewayConfig(req.body ?? {});
    res.json(await buildGatewayConfigResponse());
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

export default router;
