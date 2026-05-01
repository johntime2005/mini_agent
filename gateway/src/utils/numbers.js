import {
  DEFAULT_CONTEXT_HISTORY_LIMIT,
  DEFAULT_TIMEOUT_MS,
  MAX_TIMEOUT_MS,
} from '../config/env.js';

export function clampHistoryLimit(value) {
  if (!Number.isFinite(value)) {
    return DEFAULT_CONTEXT_HISTORY_LIMIT;
  }

  return Math.min(Math.max(1, Math.floor(value)), 100);
}

export function clampTimeout(value) {
  if (!Number.isFinite(value)) {
    return DEFAULT_TIMEOUT_MS;
  }

  return Math.min(Math.max(1, value), MAX_TIMEOUT_MS);
}
