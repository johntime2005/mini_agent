import { SESSION_TTL_MS } from '../config/env.js';
import { cleanupSandboxSession } from './sandboxCli.js';

const sessionCleanupTimers = new Map();

function getCleanupAt() {
  return new Date(Date.now() + SESSION_TTL_MS).toISOString();
}

export function clearSessionCleanup(sessionId) {
  const existing = sessionCleanupTimers.get(sessionId);
  if (existing) {
    clearTimeout(existing);
    sessionCleanupTimers.delete(sessionId);
  }
}

export function scheduleSessionCleanup(sessionId) {
  clearSessionCleanup(sessionId);
  const cleanupAt = getCleanupAt();
  const timer = setTimeout(async () => {
    try {
      await cleanupSandboxSession(sessionId);
    } catch (_error) {
      // Ignore cleanup failures during background expiry.
    } finally {
      sessionCleanupTimers.delete(sessionId);
    }
  }, SESSION_TTL_MS);
  timer.unref?.();
  sessionCleanupTimers.set(sessionId, timer);
  return cleanupAt;
}
