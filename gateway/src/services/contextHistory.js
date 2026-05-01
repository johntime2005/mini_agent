import { DEFAULT_CONTEXT_HISTORY_LIMIT } from '../config/env.js';
import { clampHistoryLimit } from '../utils/numbers.js';
import { truncateForContext } from '../utils/strings.js';
import { readGatewayConfigFile, writeGatewayConfigFile } from './configStore.js';

export function normalizeContextEntry(entry) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    return null;
  }

  if (typeof entry.type !== 'string' || typeof entry.content !== 'string') {
    return null;
  }

  return {
    timestamp: typeof entry.timestamp === 'string' ? entry.timestamp : new Date().toISOString(),
    sessionId: typeof entry.sessionId === 'string' && entry.sessionId ? entry.sessionId : null,
    type: entry.type,
    content: entry.content,
    metadata:
      entry.metadata && typeof entry.metadata === 'object' && !Array.isArray(entry.metadata)
        ? entry.metadata
        : {},
  };
}

export function getContextHistoryFromConfig(config) {
  if (!Array.isArray(config.contextHistory)) {
    return [];
  }

  return config.contextHistory.map(normalizeContextEntry).filter(Boolean);
}

export function buildContextEntry({ sessionId = null, type, content, metadata = {} }) {
  return {
    timestamp: new Date().toISOString(),
    sessionId,
    type,
    content: truncateForContext(content),
    metadata,
  };
}

export async function appendContextHistory(entries, limit = DEFAULT_CONTEXT_HISTORY_LIMIT) {
  const currentConfig = await readGatewayConfigFile();
  const normalizedEntries = (Array.isArray(entries) ? entries : [entries])
    .map(normalizeContextEntry)
    .filter(Boolean);
  const historyLimit = clampHistoryLimit(limit);
  const existingHistory = getContextHistoryFromConfig(currentConfig);
  const mergedHistory = [...existingHistory, ...normalizedEntries];
  const scopedSessionIds = [
    ...new Set(normalizedEntries.map((entry) => entry.sessionId).filter(Boolean)),
  ];

  let nextHistory = mergedHistory;
  for (const sessionId of scopedSessionIds) {
    const sessionEntries = nextHistory
      .filter((entry) => entry.sessionId === sessionId)
      .slice(-historyLimit);
    const otherEntries = nextHistory.filter((entry) => entry.sessionId !== sessionId);
    nextHistory = [...otherEntries, ...sessionEntries].sort((left, right) =>
      left.timestamp.localeCompare(right.timestamp),
    );
  }

  const mergedConfig = {
    ...currentConfig,
    contextHistory: nextHistory,
  };

  await writeGatewayConfigFile(mergedConfig);
  return mergedConfig.contextHistory;
}

export async function getRecentContextHistory({
  sessionId = null,
  limit = DEFAULT_CONTEXT_HISTORY_LIMIT,
} = {}) {
  const config = await readGatewayConfigFile();
  const history = getContextHistoryFromConfig(config);
  const filteredHistory = sessionId
    ? history.filter((entry) => entry.sessionId === sessionId)
    : history;
  return filteredHistory.slice(-clampHistoryLimit(limit));
}

export async function clearContextHistory({ sessionId = null } = {}) {
  const currentConfig = await readGatewayConfigFile();
  const nextHistory = sessionId
    ? getContextHistoryFromConfig(currentConfig).filter((entry) => entry.sessionId !== sessionId)
    : [];

  await writeGatewayConfigFile({
    ...currentConfig,
    contextHistory: nextHistory,
  });

  return nextHistory;
}

export function formatContextHistoryForPrompt(entries) {
  if (!entries.length) {
    return null;
  }

  const lines = entries.map((entry, index) => {
    const sessionLine = entry.sessionId ? ` session=${entry.sessionId}` : '';
    return [
      `#${index + 1} [${entry.timestamp}] type=${entry.type}${sessionLine}`,
      entry.content,
    ].join('\n');
  });

  return [
    'Recent cached interaction context follows.',
    'Use it only as supporting context. Prioritize the current user request if there is any conflict.',
    ...lines,
  ].join('\n\n');
}
