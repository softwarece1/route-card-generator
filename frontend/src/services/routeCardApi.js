import http from '@/lib/http';

const BASE = '/route-card';

function detailFromPayload(data) {
  if (data == null) return '';
  if (typeof data === 'string') {
    try {
      const parsed = JSON.parse(data);
      return detailFromPayload(parsed);
    } catch {
      return data.trim();
    }
  }
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) {
    return data.detail.map((d) => d?.msg || d).join('; ');
  }
  if (typeof data?.message === 'string') return data.message;
  return '';
}

/** Prefer API detail; map bare axios status messages to readable text. */
function asError(error, fallback) {
  if (!error?.response && (error?.message === 'Network Error' || error?.code === 'ERR_NETWORK')) {
    return 'Cannot reach API. Start the backend on port 8008, then refresh.';
  }
  if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') {
    return 'Analysis cancelled.';
  }
  if (
    error?.code === 'ECONNABORTED' ||
    /timeout/i.test(error?.message || '')
  ) {
    return (
      'Analysis timed out waiting for the local vision model. ' +
      'Keep Ollama running (model warm), or try again — first run can take several minutes.'
    );
  }
  const detail = detailFromPayload(error?.response?.data);
  if (detail) return detail;

  const status = error?.response?.status;
  if (status === 404) {
    return fallback || 'File or record not found.';
  }
  if (status === 403) {
    return 'You do not have permission for this action.';
  }
  if (status === 401) {
    return 'Please sign in again.';
  }
  if (status >= 500) {
    return fallback || 'Server error — please try again or contact support.';
  }
  if (error?.message && !/^Request failed with status code \d+$/i.test(error.message)) {
    return error.message;
  }
  return fallback || error?.message || 'Request failed';
}

/** Parse FastAPI JSON error when axios used responseType: 'blob'. */
async function asBlobError(error, fallback) {
  const data = error?.response?.data;
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const patched = {
        ...error,
        response: { ...error.response, data: text ? JSON.parse(text) : null },
      };
      return asError(patched, fallback);
    } catch {
      /* fall through */
    }
  }
  return asError(error, fallback);
}

export function isCanceledError(error) {
  return (
    error?.code === 'ERR_CANCELED' ||
    error?.name === 'CanceledError' ||
    error?.response?.status === 409 ||
    /cancelled/i.test(error?.message || '')
  );
}


export async function createSession() {
  try {
    const { data } = await http.post(`${BASE}/sessions`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not create upload session'));
  }
}

export async function getSession(sessionId) {
  const { data } = await http.get(`${BASE}/sessions/${sessionId}`);
  return data;
}

export async function uploadSessionDocument(sessionId, role, file) {
  const formData = new FormData();
  formData.append('file', file);
  try {
    const { data } = await http.post(
      `${BASE}/sessions/${sessionId}/documents/${role}`,
      formData,
    );
    return data;
  } catch (error) {
    throw new Error(asError(error, `Upload failed (${role})`));
  }
}

export async function deleteSessionDocument(sessionId, role, documentId = null) {
  try {
    const { data } = await http.delete(
      `${BASE}/sessions/${sessionId}/documents/${role}`,
      { params: documentId != null ? { documentId } : undefined },
    );
    return data;
  } catch (error) {
    throw new Error(asError(error, `Remove failed (${role})`));
  }
}

export async function cancelAnalyzeSession(sessionId) {
  try {
    const { data } = await http.post(
      `${BASE}/sessions/${sessionId}/analyze/cancel`,
      null,
      { timeout: 15_000 },
    );
    return data;
  } catch {
    return { sessionId, cancelled: false };
  }
}

/** @deprecated Prefer session upload; kept for compatibility */
export async function uploadDrawing(file) {
  const formData = new FormData();
  formData.append('file', file);
  try {
    const { data } = await http.post(`${BASE}/drawings`, formData);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Upload failed'));
  }
}

export async function analyzeDrawing(drawingId) {
  try {
    const { data } = await http.post(
      `${BASE}/drawings/${drawingId}/analyze`,
      null,
      { timeout: 1_200_000 },
    );
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Analysis failed'));
  }
}

export async function getDrawing(drawingId) {
  const { data } = await http.get(`${BASE}/drawings/${drawingId}`);
  return data;
}

export async function fetchDrawingFileBlob(drawingId) {
  const { data } = await http.get(`${BASE}/drawings/${drawingId}/file`, {
    responseType: 'blob',
  });
  return data;
}

export async function generateRouteCard(drawingId) {
  const { data } = await http.post(`${BASE}/drawings/${drawingId}/route-card`);
  return data;
}

export async function updateRouteCard(routeId, payload) {
  const { data } = await http.put(`${BASE}/route-cards/${routeId}`, payload);
  return data;
}

export async function saveRouteDraft(routeId) {
  const { data } = await http.post(`${BASE}/route-cards/${routeId}/draft`);
  return data;
}

export async function approveRouteCard(routeId, { adminOverride = false } = {}) {
  const { data } = await http.post(
    `${BASE}/route-cards/${routeId}/approve`,
    null,
    { params: adminOverride ? { adminOverride: true } : undefined },
  );
  return data;
}

/** PMF Create-Order (OARC) JSON — ops, LongText, raw materials prefill */
export async function exportPmfOarc(routeId, params = {}) {
  try {
    const { data } = await http.get(`${BASE}/route-cards/${routeId}/pmf-oarc`, {
      params: {
        required_qty: params.requiredQty ?? 1,
        plant: params.plant ?? '',
        production_order: params.productionOrder ?? '',
        sale_order: params.saleOrder ?? '',
        wbs: params.wbs ?? '',
        project_name: params.projectName ?? '',
      },
    });
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not export PMF order JSON'));
  }
}

export function downloadJson(filename, obj) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function copyJsonToClipboard(obj) {
  const text = JSON.stringify(obj, null, 2);
  await navigator.clipboard.writeText(text);
}

export async function fetchReviewFlags(routeId) {
  const { data } = await http.get(`${BASE}/route-cards/${routeId}/review-flags`);
  return data;
}

export async function resolveReviewFlag(flagId, resolved = true) {
  const { data } = await http.patch(`${BASE}/review-flags/${flagId}`, null, {
    params: { resolved },
  });
  return data;
}

export async function fetchItemLinkReport(sessionId) {
  const { data } = await http.get(`${BASE}/sessions/${sessionId}/item-link-report`);
  return data;
}

export async function cloneRouteToSession(sessionId, fromRouteCardId) {
  const { data } = await http.post(
    `${BASE}/sessions/${sessionId}/clone-route`,
    null,
    { params: { fromRouteCardId } },
  );
  return data;
}

export async function compareRouteCards(a, b) {
  const { data } = await http.get(`${BASE}/route-cards/compare`, { params: { a, b } });
  return data;
}

export async function fetchRouteAudit(routeId) {
  const { data } = await http.get(`${BASE}/route-cards/${routeId}/audit`);
  return data;
}

export async function fetchFavorites() {
  const { data } = await http.get(`${BASE}/my/favorites`);
  return data;
}

export async function addFavorite(payload) {
  const { data } = await http.post(`${BASE}/my/favorites`, payload);
  return data;
}

export async function deleteFavorite(favId) {
  const { data } = await http.delete(`${BASE}/my/favorites/${favId}`);
  return data;
}

export async function fetchRecent() {
  const { data } = await http.get(`${BASE}/my/recent`);
  return data;
}

export async function enqueueAnalyze(sessionId, { vlmPageIndexes, async: asAsync = true } = {}) {
  const { data } = await http.post(
    `${BASE}/sessions/${sessionId}/analyze`,
    { vlmPageIndexes, async: asAsync },
    { timeout: 30_000 },
  );
  return data;
}

export async function analyzeSession(sessionId, { signal, vlmPageIndexes } = {}) {
  try {
    const { data } = await http.post(
      `${BASE}/sessions/${sessionId}/analyze`,
      vlmPageIndexes ? { vlmPageIndexes, async: false } : { async: false },
      { timeout: 1_200_000, signal },
    );
    return data;
  } catch (error) {
    if (isCanceledError(error)) {
      const err = new Error('Analysis cancelled.');
      err.code = 'ERR_CANCELED';
      throw err;
    }
    throw new Error(asError(error, 'Analysis failed'));
  }
}

export async function fetchAnalyzeJobs({ mineOnly = true } = {}) {
  const { data } = await http.get(`${BASE}/analyze-jobs`, { params: { mineOnly } });
  return data;
}

export async function fetchAnalyzeJob(jobId) {
  const { data } = await http.get(`${BASE}/analyze-jobs/${jobId}`);
  return data;
}

export async function cancelAnalyzeJob(jobId) {
  const { data } = await http.post(`${BASE}/analyze-jobs/${jobId}/cancel`);
  return data;
}

export async function batchEnqueueAnalyze(sessionIds) {
  const { data } = await http.post(`${BASE}/analyze-jobs/batch`, { sessionIds });
  return data;
}

export async function fetchQueueStats() {
  const { data } = await http.get(`${BASE}/analyze-jobs/stats/queue`);
  return data;
}

export async function fetchNotifications({ unreadOnly = false } = {}) {
  const { data } = await http.get(`${BASE}/notifications`, { params: { unreadOnly } });
  return data;
}

export async function markNotificationRead(id) {
  const { data } = await http.post(`${BASE}/notifications/${id}/read`);
  return data;
}

export async function markAllNotificationsRead() {
  const { data } = await http.post(`${BASE}/notifications/read-all`);
  return data;
}

export async function fetchDeptRules(dept) {
  const { data } = await http.get(`${BASE}/dept-rules`, { params: dept ? { dept } : undefined });
  return data;
}

export async function saveDeptRules(payload) {
  const { data } = await http.put(`${BASE}/dept-rules`, payload);
  return data;
}

export async function fetchFewShots(dept) {
  const { data } = await http.get(`${BASE}/few-shot-examples`, {
    params: dept ? { dept } : undefined,
  });
  return data;
}

export async function createFewShot(payload) {
  const { data } = await http.post(`${BASE}/few-shot-examples`, payload);
  return data;
}

export async function deleteFewShot(id) {
  const { data } = await http.delete(`${BASE}/few-shot-examples/${id}`);
  return data;
}

export async function fetchMachinesQuietly() {
  try {
    const { data } = await http.get(`${BASE}/machines`);
    return data?.items || [];
  } catch {
    return [];
  }
}

export async function fetchSystemHealth() {
  const { data } = await http.get(`${BASE}/system/health`);
  return data;
}

export async function fetchStorageStats() {
  const { data } = await http.get(`${BASE}/admin/storage-stats`);
  return data;
}

export async function runAdminBackup() {
  const { data } = await http.post(`${BASE}/admin/backup`, null, { timeout: 600_000 });
  return data;
}

export async function runAdminCleanup({ days = 90, dryRun = true } = {}) {
  const { data } = await http.post(`${BASE}/admin/cleanup`, null, {
    params: { days, dryRun },
  });
  return data;
}

export async function createMachine(payload) {
  const { data } = await http.post(`${BASE}/machines`, payload);
  return data;
}

export async function updateMachine(id, payload) {
  const { data } = await http.put(`${BASE}/machines/${id}`, payload);
  return data;
}

export async function deleteMachine(id) {
  const { data } = await http.delete(`${BASE}/machines/${id}`);
  return data;
}

export async function listFormatTemplates() {
  try {
    const { data } = await http.get(`${BASE}/formats`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load format templates'));
  }
}

export async function learnFormatTemplate(sessionId, payload) {
  try {
    const { data } = await http.post(`${BASE}/sessions/${sessionId}/formats/learn`, payload);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not save format template'));
  }
}

export async function deleteFormatTemplate(templateId) {
  try {
    const { data } = await http.delete(`${BASE}/formats/${templateId}`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not delete format template'));
  }
}

export async function fetchMyExtractions() {
  try {
    const { data } = await http.get(`${BASE}/my/extractions`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load extraction history'));
  }
}

export async function fetchMyExtractionDetail(sessionId) {
  try {
    const { data } = await http.get(`${BASE}/my/extractions/${sessionId}`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load extraction detail'));
  }
}

export async function fetchAdminUsers() {
  try {
    const { data } = await http.get(`${BASE}/admin/users`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load users'));
  }
}

export async function fetchDeptUsers() {
  try {
    const { data } = await http.get(`${BASE}/dept/users`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load department users'));
  }
}

export async function updateAdminUserRole(userId, role) {
  try {
    const { data } = await http.patch(`${BASE}/admin/users/${userId}`, { role });
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not update user role'));
  }
}

export async function createManagedUser(payload) {
  try {
    const { data } = await http.post(`${BASE}/users`, payload);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not create user'));
  }
}

export async function updateManagedUser(userId, payload) {
  try {
    const { data } = await http.patch(`${BASE}/users/${userId}`, payload);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not update user'));
  }
}

export async function resetManagedUserPassword(userId, password) {
  try {
    const { data } = await http.post(`${BASE}/users/${userId}/reset-password`, { password });
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not reset password'));
  }
}

export async function listOperationTemplates({ scope = 'own', dept } = {}) {
  try {
    const params = { scope };
    if (dept) params.dept = dept;
    const { data } = await http.get(`${BASE}/operation-templates`, { params });
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load operation templates'));
  }
}

export async function getOperationTemplate(templateId) {
  try {
    const { data } = await http.get(`${BASE}/operation-templates/${templateId}`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load template'));
  }
}

export async function createOperationTemplate(payload) {
  try {
    const { data } = await http.post(`${BASE}/operation-templates`, payload);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not create template'));
  }
}

export async function updateOperationTemplate(templateId, payload) {
  try {
    const { data } = await http.put(`${BASE}/operation-templates/${templateId}`, payload);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not update template'));
  }
}

export async function deleteOperationTemplate(templateId) {
  try {
    const { data } = await http.delete(`${BASE}/operation-templates/${templateId}`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not delete template'));
  }
}

export async function duplicateOperationTemplate(templateId, payload = {}) {
  try {
    const { data } = await http.post(
      `${BASE}/operation-templates/${templateId}/duplicate`,
      payload,
    );
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not duplicate template'));
  }
}

export async function fetchAdminExtractions({
  empId,
  dept,
  status,
  fromDate,
  toDate,
} = {}) {
  try {
    const params = {};
    if (empId) params.empId = empId;
    if (dept) params.dept = dept;
    if (status) params.status = status;
    if (fromDate) params.fromDate = fromDate;
    if (toDate) params.toDate = toDate;
    const { data } = await http.get(`${BASE}/admin/extractions`, { params });
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load admin extractions'));
  }
}

export async function fetchAdminExtractionDetail(sessionId) {
  try {
    const { data } = await http.get(`${BASE}/admin/extractions/${sessionId}`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load extraction detail'));
  }
}

export async function fetchAdminUploads({
  empId,
  dept,
  status,
  fromDate,
  toDate,
} = {}) {
  try {
    const params = {};
    if (empId) params.empId = empId;
    if (dept) params.dept = dept;
    if (status) params.status = status;
    if (fromDate) params.fromDate = fromDate;
    if (toDate) params.toDate = toDate;
    const { data } = await http.get(`${BASE}/admin/uploads`, { params });
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load uploads'));
  }
}

export async function fetchAdminUploadSession(sessionId) {
  try {
    const { data } = await http.get(`${BASE}/admin/uploads/${sessionId}`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Could not load session uploads'));
  }
}

export function adminDocumentFileUrl(documentId) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  return `${base}/route-card/admin/documents/${documentId}/file`;
}

export async function fetchAdminDocumentBlob(documentId) {
  try {
    const { data, headers } = await http.get(
      `${BASE}/admin/documents/${documentId}/file`,
      { responseType: 'blob' },
    );
    // Some proxies still return 200 with JSON error body as a blob
    const ctype = String(headers?.['content-type'] || '');
    if (ctype.includes('application/json') && data instanceof Blob) {
      const text = await data.text();
      let detail = 'Could not open document';
      try {
        detail = detailFromPayload(JSON.parse(text)) || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return data;
  } catch (error) {
    if (error instanceof Error && !error.response) throw error;
    throw new Error(await asBlobError(error, 'Could not open document'));
  }
}

export function sessionDocumentFileUrl(sessionId, role) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  return `${base}/route-card/sessions/${sessionId}/documents/${role}/file`;
}

export async function fetchSessionDocumentBlob(sessionId, role, documentId = null) {
  try {
    const { data } = await http.get(
      `${BASE}/sessions/${sessionId}/documents/${role}/file`,
      {
        responseType: 'blob',
        params: documentId != null ? { documentId } : undefined,
      },
    );
    return data;
  } catch (error) {
    throw new Error(await asBlobError(error, 'Could not download document'));
  }
}
