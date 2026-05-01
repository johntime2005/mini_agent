import { MAX_CONTEXT_PREVIEW_LENGTH } from '../config/env.js';

export function normalizeOptionalString(value, fieldName) {
  if (value === undefined) {
    return undefined;
  }

  if (value === null) {
    return '';
  }

  if (typeof value !== 'string') {
    throw new Error(`${fieldName} must be a string`);
  }

  return value.trim();
}

export function truncateForContext(value, maxLength = MAX_CONTEXT_PREVIEW_LENGTH) {
  if (typeof value !== 'string') {
    return '';
  }

  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength)}\n...[truncated]`;
}

export function stripCodeFences(content) {
  const trimmed = content.trim();
  const fencedMatch = trimmed.match(/^```(?:python)?\s*([\s\S]*?)\s*```$/i);
  return fencedMatch ? fencedMatch[1].trim() : trimmed;
}
