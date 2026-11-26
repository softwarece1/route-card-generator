/**
 * Login helper for Playwright using the same RSA-OAEP path as the SPA (node-forge).
 */
import forge from 'node-forge';

const ALG = 'RSA-OAEP-SHA256';

function encryptCredentials(pem, payload) {
  const key = forge.pki.publicKeyFromPem(pem);
  const json = JSON.stringify(payload);
  const encrypted = key.encrypt(json, 'RSA-OAEP', {
    md: forge.md.sha256.create(),
    mgf1: { md: forge.md.sha256.create() },
  });
  return { cipher: forge.util.encode64(encrypted), alg: ALG };
}

/**
 * @param {import('@playwright/test').APIRequestContext} request
 * @param {{ empId: string, password: string }} creds
 */
export async function apiLogin(request, creds) {
  const keyResp = await request.get('/api/v1/auth/public-key');
  if (!keyResp.ok()) {
    throw new Error(`public-key failed: ${keyResp.status()}`);
  }
  const keyInfo = await keyResp.json();
  const body = encryptCredentials(keyInfo.publicKeyPem || keyInfo.pem, {
    empId: creds.empId,
    password: creds.password,
  });
  let loginResp = await request.post('/api/v1/auth/login', {
    data: {
      ...body,
      terminateExistingSession: true,
    },
  });
  if (loginResp.status() === 409) {
    const detail = (await loginResp.json()).detail || {};
    const resume = detail.resumeToken;
    if (!resume) {
      throw new Error(`login 409 without resumeToken: ${JSON.stringify(detail)}`);
    }
    loginResp = await request.post('/api/v1/auth/login/takeover', {
      data: { resumeToken: resume },
    });
  }
  if (!loginResp.ok()) {
    const text = await loginResp.text();
    throw new Error(`login failed: ${loginResp.status()} ${text}`);
  }
  return loginResp.json();
}

export const VNV = {
  engineer: { empId: '810004', password: 'VnVTestPass2026!#Aa' },
  engineer_ied: { empId: '810005', password: 'VnVTestPass2026!#Aa' },
};
