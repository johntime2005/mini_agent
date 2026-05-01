import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// gateway/src/config/ -> gateway/ -> repo root
export const repoRoot = path.resolve(__dirname, '..', '..', '..');

export const GATEWAY_CONFIG_PATH =
  process.env.GATEWAY_CONFIG_PATH ||
  path.join(repoRoot, '.mini-agent', 'gateway-config.json');

export const PORT = Number(process.env.PORT || 3000);
export const PYTHON_BIN = process.env.PYTHON_BIN || 'python';
export const SANDBOX_MODULE = process.env.SANDBOX_MODULE || 'mini_agent_sandbox.cli';

export const DEFAULT_TIMEOUT_MS = Number(process.env.DEFAULT_TIMEOUT_MS || 5000);
export const MAX_TIMEOUT_MS = Number(process.env.MAX_TIMEOUT_MS || 10000);
export const DEFAULT_FILE_NAME = process.env.DEFAULT_FILE_NAME || 'generated.py';
export const SESSION_TTL_MS = Number(process.env.SESSION_TTL_MS || 10 * 60 * 1000);

export const DEFAULT_LLM_API_URL =
  process.env.LLM_API_URL || 'https://api.openai.com/v1/chat/completions';
export const DEFAULT_LLM_MODEL = process.env.LLM_MODEL || 'gpt-4o-mini';
export const DEFAULT_LLM_API_KEY = process.env.LLM_API_KEY || '';

export const DEFAULT_CONTEXT_HISTORY_LIMIT = Number(process.env.CONTEXT_HISTORY_LIMIT || 10);
export const MAX_CONTEXT_PREVIEW_LENGTH = Number(process.env.MAX_CONTEXT_PREVIEW_LENGTH || 4000);
