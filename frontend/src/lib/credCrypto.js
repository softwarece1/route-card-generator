/**
 * Encrypt login/signup credentials with the server RSA public key (RSA-OAEP SHA-256).
 * Payload is JSON: { empId, password } — never send those fields in cleartext.
 */

const ALG = 'RSA-OAEP-SHA256';

let cachedKey = null;
let cachedPem = '';

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

async function importPublicKey(pem) {
  if (cachedKey && cachedPem === pem) return cachedKey;
  const key = await crypto.subtle.importKey(
    'spki',
    pemToArrayBuffer(pem),
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['encrypt'],
  );
  cachedKey = key;
  cachedPem = pem;
  return key;
}

/**
 * @param {{ publicKeyPem: string }} keyInfo from GET /auth/public-key
 * @param {{ empId: string, password: string }} creds
 * @returns {Promise<{ cipher: string, alg: string }>}
 */
export async function encryptCredentials(keyInfo, creds) {
  const pem = keyInfo?.publicKeyPem;
  if (!pem) {
    throw new Error('Server public key is missing');
  }
  if (!window.crypto?.subtle) {
    throw new Error('Web Crypto is not available in this browser (use HTTPS or localhost)');
  }
  const key = await importPublicKey(pem);
  const payloadData = {
    empId: String(creds?.empId || '').trim(),
    password: String(creds?.password || ''),
  };
  if (creds?.captchaId) {
    payloadData.captchaId = String(creds.captchaId);
  }
  if (creds?.captchaAnswer) {
    payloadData.captchaAnswer = String(creds.captchaAnswer);
  }
  const payload = JSON.stringify(payloadData);
  const encoded = new TextEncoder().encode(payload);
  const cipherBuf = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, key, encoded);
  const bytes = new Uint8Array(cipherBuf);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return {
    cipher: btoa(binary),
    alg: keyInfo?.alg || ALG,
  };
}

export { ALG as CREDS_ALG };
