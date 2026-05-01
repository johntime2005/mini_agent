import express from 'express';

import contextHistoryRouter from './routes/contextHistory.js';
import executeRouter from './routes/execute.js';
import healthRouter from './routes/health.js';
import llmConfigRouter from './routes/llmConfig.js';
import sandboxSessionsRouter from './routes/sandboxSessions.js';

export function createApp() {
  const app = express();

  app.use(express.json({ limit: '1mb' }));

  app.use(healthRouter);
  app.use(llmConfigRouter);
  app.use(contextHistoryRouter);
  app.use(sandboxSessionsRouter);
  app.use(executeRouter);

  return app;
}
