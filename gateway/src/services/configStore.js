import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { GATEWAY_CONFIG_PATH } from '../config/env.js';

export async function readGatewayConfigFile() {
  try {
    const raw = await readFile(GATEWAY_CONFIG_PATH, 'utf8');
    const parsed = JSON.parse(raw);

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('Gateway config must be a JSON object');
    }

    return parsed;
  } catch (error) {
    if (error.code === 'ENOENT') {
      return {};
    }

    throw new Error(`Failed to read gateway config: ${error.message}`);
  }
}

export async function writeGatewayConfigFile(config) {
  await mkdir(path.dirname(GATEWAY_CONFIG_PATH), { recursive: true });
  await writeFile(GATEWAY_CONFIG_PATH, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
}
