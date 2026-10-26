/**
 * Encrypt login/signup credentials with the server RSA public key (RSA-OAEP SHA-256).
 * Payload is JSON: { empId, password } — never send those fields in cleartext.
 *
 * Uses Web Crypto when available (HTTPS / localhost). On plain HTTP LAN IPs,
 * browsers hide crypto.subtle — fall back to node-forge (same OAEP+SHA-256).
 */

import forge from 'node-forge';

const ALG = 'RSA-OAEP-SHA256';

let cachedSubtleKey = null;
let cachedSubtlePem = '';
let cachedForgeKey = null;
let cachedForgePem = '';

function pemToArrayBuffer(pem) {
  const b64 = String(pem || '')
    .replace(/-----BEGIN PUBLIC KEY-----/g, '')
    .replace(/-----END PUBLIC KEY-----/g, '')
    .replace(/\s+/g, '');
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function bytesToBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function importSubtleKey(pem) {
  if (cachedSubtleKey && cachedSubtlePem === pem) return cachedSubtleKey;
  const key = await crypto.subtle.importKey(
    'spki',
    pemToArrayBuffer(pem),
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['encrypt'],
  );
  cachedSubtleKey = key;
  cachedSubtlePem = pem;
  return key;
}

function importForgeKey(pem) {
  if (cachedForgeKey && cachedForgePem === pem) return cachedForgeKey;
  const key = forge.pki.publicKeyFromPem(pem);
  cachedForgeKey = key;
  cachedForgePem = pem;
  return key;
}

async function encryptWithSubtle(pem, payload) {
  const key = await importSubtleKey(pem);
  const encoded = new TextEncoder().encode(payload);
  const cipherBuf = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, key, encoded);
  return bytesToBase64(new Uint8Array(cipherBuf));
}

function encryptWithForge(pem, payload) {
  const key = importForgeKey(pem);
  const encrypted = key.encrypt(payload, 'RSA-OAEP', {
    md: forge.md.sha256.create(),
    mgf1: { md: forge.md.sha256.create() },
  });
  return forge.util.encode64(encrypted);
}

/**
 * @param {{ publicKeyPem: string, alg?: string }} keyInfo from GET /auth/public-key
 * @param {{ empId: string, password: string }} creds
 * @returns {Promise<{ cipher: string, alg: string }>}
 */
export async function encryptCredentials(keyInfo, creds) {
  const pem = keyInfo?.publicKeyPem;
  if (!pem) {
    throw new Error('Server public key is missing');
  }
  const payload = JSON.stringify({
    empId: String(creds?.empId || '').trim(),
    password: String(creds?.password || ''),
  });

  let cipher;
  if (window.crypto?.subtle) {
    cipher = await encryptWithSubtle(pem, payload);
  } else {
    cipher = encryptWithForge(pem, payload);
  }

  return {
    cipher,
    alg: keyInfo?.alg || ALG,
  };
}

export { ALG as CREDS_ALG };
