export function parseJsonOutput(stdout, fallbackMessage) {
  try {
    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`${fallbackMessage}: ${stdout || error.message}`);
  }
}

export function getStatusCode(error) {
  if (error.message.includes('Sandbox session not found')) {
    return 404;
  }

  return 500;
}
