import {
  DEFAULT_CONTEXT_HISTORY_LIMIT,
  DEFAULT_LLM_API_KEY,
  DEFAULT_LLM_API_URL,
  DEFAULT_LLM_MODEL,
  GATEWAY_CONFIG_PATH,
} from '../config/env.js';
import { normalizeOptionalString, stripCodeFences } from '../utils/strings.js';
import { readGatewayConfigFile, writeGatewayConfigFile } from './configStore.js';
import {
  formatContextHistoryForPrompt,
  getContextHistoryFromConfig,
  getRecentContextHistory,
} from './contextHistory.js';

function normalizeGatewayConfigInput(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error('config body must be a JSON object');
  }

  return {
    llmApiKey: normalizeOptionalString(input.llmApiKey, 'llmApiKey'),
    llmApiUrl: normalizeOptionalString(input.llmApiUrl, 'llmApiUrl'),
    llmModel: normalizeOptionalString(input.llmModel, 'llmModel'),
  };
}

function sanitizeGatewayConfig(config) {
  return Object.fromEntries(
    Object.entries(config).filter(([, value]) => value !== undefined),
  );
}

export async function getLlmConfig() {
  const fileConfig = await readGatewayConfigFile();
  const llmApiKey = fileConfig.llmApiKey || DEFAULT_LLM_API_KEY;
  const llmApiUrl = fileConfig.llmApiUrl || DEFAULT_LLM_API_URL;
  const llmModel = fileConfig.llmModel || DEFAULT_LLM_MODEL;

  return {
    llmApiKey,
    llmApiUrl,
    llmModel,
    source: {
      llmApiKey: fileConfig.llmApiKey ? 'config' : 'env',
      llmApiUrl: fileConfig.llmApiUrl ? 'config' : 'env',
      llmModel: fileConfig.llmModel ? 'config' : 'env',
    },
  };
}

export async function updateGatewayConfig(nextConfig) {
  const currentConfig = await readGatewayConfigFile();
  const normalizedInput = normalizeGatewayConfigInput(nextConfig);
  const mergedConfig = sanitizeGatewayConfig({
    ...currentConfig,
    ...normalizedInput,
  });

  await writeGatewayConfigFile(mergedConfig);
  return mergedConfig;
}

export async function buildGatewayConfigResponse() {
  const fileConfig = await readGatewayConfigFile();
  const effectiveConfig = await getLlmConfig();
  const contextHistory = getContextHistoryFromConfig(fileConfig);

  return {
    configPath: GATEWAY_CONFIG_PATH,
    persisted: {
      hasConfigFile:
        fileConfig.llmApiKey !== undefined ||
        fileConfig.llmApiUrl !== undefined ||
        fileConfig.llmModel !== undefined,
      llmApiKeyConfigured: Boolean(fileConfig.llmApiKey),
      llmApiUrl: fileConfig.llmApiUrl || null,
      llmModel: fileConfig.llmModel || null,
    },
    effective: {
      llmApiKeyConfigured: Boolean(effectiveConfig.llmApiKey),
      llmApiUrl: effectiveConfig.llmApiUrl,
      llmModel: effectiveConfig.llmModel,
      source: effectiveConfig.source,
    },
    contextCache: {
      limit: DEFAULT_CONTEXT_HISTORY_LIMIT,
      size: contextHistory.length,
      latestSessionId: contextHistory.at(-1)?.sessionId || null,
      sessionScoped: true,
    },
  };
}

export async function generatePythonCode(prompt, options = {}) {
  const { contextLimit = DEFAULT_CONTEXT_HISTORY_LIMIT, sessionId = null } = options;
  const { llmApiKey, llmApiUrl, llmModel } = await getLlmConfig();
  const recentContext = await getRecentContextHistory({ sessionId, limit: contextLimit });
  const contextMessage = formatContextHistoryForPrompt(recentContext);

  if (!llmApiKey) {
    throw new Error('LLM_API_KEY is not set');
  }

  const messages = [
    {
      role: 'system',
      content:
        'You generate runnable Python scripts only. Return code only, no markdown fences, no explanations. The script must write useful stdout for the user request.',
    },
  ];

  if (contextMessage) {
    messages.push({
      role: 'system',
      content: contextMessage,
    });
  }

  messages.push({
    role: 'user',
    content: prompt,
  });

  const response = await fetch(llmApiUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${llmApiKey}`,
    },
    body: JSON.stringify({
      model: llmModel,
      temperature: 0.2,
      messages,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`LLM request failed (${response.status}): ${text}`);
  }

  const payload = await response.json();
  const rawCode = payload?.choices?.[0]?.message?.content;
  if (typeof rawCode !== 'string' || !rawCode.trim()) {
    throw new Error('LLM response did not contain code');
  }

  return stripCodeFences(rawCode);
}
