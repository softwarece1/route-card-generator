import http from '@/lib/http';

const BASE = '/route-card';

function asError(error, fallback) {
  if (!error?.response && (error?.message === 'Network Error' || error?.code === 'ERR_NETWORK')) {
    return 'Cannot reach API. Start the backend on port 8008, then refresh.';
  }
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || d).join('; ');
  return error?.message || fallback;
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

export async function analyzeSession(sessionId) {
  try {
    const { data } = await http.post(`${BASE}/sessions/${sessionId}/analyze`);
    return data;
  } catch (error) {
    throw new Error(asError(error, 'Analysis failed'));
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
    const { data } = await http.post(`${BASE}/drawings/${drawingId}/analyze`);
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

export async function approveRouteCard(routeId) {
  const { data } = await http.post(`${BASE}/route-cards/${routeId}/approve`);
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

export function sessionDocumentFileUrl(sessionId, role) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  return `${base}/route-card/sessions/${sessionId}/documents/${role}/file`;
}

/** Standalone app has no plant machines API — panel stays hidden. */
export async function fetchMachinesQuietly() {
  return [];
}
