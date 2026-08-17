const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function errorMessage(payload, status) {
  const apiError =
    typeof payload === "object" ? payload?.error?.message : null;

  if (typeof apiError === "string") return apiError;

  const detail = typeof payload === "object" ? payload?.detail : null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg ?? JSON.stringify(item))
      .filter(Boolean)
      .join(" · ");
  }
  if ([502, 504].includes(status)) {
    return "백엔드 서버에 연결할 수 없습니다. RAG 서버가 실행 중인지 확인하세요.";
  }
  if (typeof payload === "string" && payload) return payload;
  return `요청에 실패했습니다. (${status})`;
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new Error(errorMessage(payload, response.status));
  }

  return payload;
}

async function parseV1Response(response) {
  const payload = await parseResponse(response);

  if (payload?.success === false) {
    throw new Error(
      payload.error?.message ?? "요청 처리에 실패했습니다.",
    );
  }

  return payload?.data;
}

export async function streamQuestion(question, { signal, onEvent } = {}) {
  const query = encodeURIComponent(question);
  const response = await fetch(apiUrl(`/api/v1/chat-stream?question=${query}`), {
    headers: { Accept: "text/event-stream" },
    signal,
  });

  if (!response.ok) return parseResponse(response);
  if (!response.body) throw new Error("실시간 답변 스트림을 열 수 없습니다.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  const consumeBlock = (block) => {
  const jsonText = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");

  if (!jsonText) return;

  const event = JSON.parse(jsonText);

  if (event.type === "progress") {
    onEvent?.({ stage: event.message });
    return;
  }

  if (event.type === "token") {
    onEvent?.({ token: event.token });
    return;
  }

  if (event.type === "done") {
    if (!event.success) {
      throw new Error(
        event.error?.message ?? "답변 생성에 실패했습니다.",
      );
    }

    result = event.data;
  }
};

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    blocks.forEach(consumeBlock);
    if (done) break;
  }
  if (buffer.trim()) consumeBlock(buffer);
  if (!result) throw new Error("서버가 최종 답변을 보내지 않았습니다.");
  return result;
}

export async function getHealth(signal) {
  try {
    const response = await fetch(apiUrl("/health"), { signal });
    const payload = await response.json();
    return { ...payload, reachable: true, httpOk: response.ok };
  } catch (error) {
    if (error.name === "AbortError") throw error;
    return { status: "offline", checks: {}, reachable: false, httpOk: false };
  }
}

export async function getDocuments(signal) {
  const response = await fetch(apiUrl("/api/documents"), { signal });
  return parseResponse(response);
}

export async function getDocumentStatus(documentId, signal) {
  const response = await fetch(
    apiUrl(`/api/v1/documents/${encodeURIComponent(documentId)}`),
    { signal },
  );

  return parseV1Response(response);
}

export async function getDocumentLabels(documentId, signal) {
  const response = await fetch(
    apiUrl(`/api/documents/${encodeURIComponent(documentId)}/labels`),
    { signal },
  );
  return parseResponse(response);
}

export async function getDocumentChunks(documentId, signal) {
  const response = await fetch(
    apiUrl(`/api/documents/${encodeURIComponent(documentId)}/chunks`),
    { signal },
  );
  return parseResponse(response);
}

export async function updateDocumentLabels(documentId, labels) {
  const response = await fetch(
    apiUrl(`/api/documents/${encodeURIComponent(documentId)}/labels`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ labels }),
    },
  );
  return parseResponse(response);
}

export async function retryDocument(documentId) {
  const response = await fetch(
    apiUrl(`/api/documents/${encodeURIComponent(documentId)}/retry`),
    { method: "POST" },
  );
  return parseResponse(response);
}

export async function reextractDocument(documentId) {
  const response = await fetch(
    apiUrl(`/api/documents/${encodeURIComponent(documentId)}/reextract`),
    { method: "POST" },
  );
  return parseResponse(response);
}

export async function deleteDocuments(documentIds) {
  const response = await fetch(apiUrl("/api/documents/delete-batch"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_ids: documentIds }),
  });
  return parseResponse(response);
}

export async function uploadDocument(file, labels) {
  const formData = new FormData();
  formData.append("file", file);

  const isZip = file.name.toLowerCase().endsWith(".zip");

  if (!isZip) {
    labels.forEach((label) => formData.append("labels", label));
  }

  const endpoint = isZip
    ? "/api/documents/upload-zip"
    : "/api/v1/upload";

  const response = await fetch(apiUrl(endpoint), {
    method: "POST",
    body: formData,
  });

  return isZip
    ? parseResponse(response)
    : parseV1Response(response);
}


export async function runDocumentWorkers(signal) {
  const response = await fetch(apiUrl("/api/admin/run-workers"), {
    method: "POST",
    signal,
  });
  return parseResponse(response);
}

export async function searchLabels(query, signal) {
  if (!query.trim()) return [];
  const response = await fetch(
    apiUrl(`/api/document-labels/search?q=${encodeURIComponent(query.trim())}`),
    { signal },
  );
  return parseResponse(response);
}

export function documentFileUrl(documentId, pageNumber) {
  const url = apiUrl(`/api/documents/${encodeURIComponent(documentId)}/file`);
  return Number.isFinite(pageNumber) && pageNumber > 0
    ? `${url}#page=${Math.trunc(pageNumber)}`
    : url;
}

export function assetUrl(path) {
  if (!path || /^(https?:|data:|blob:)/i.test(path)) return path;
  return apiUrl(path.startsWith("/") ? path : `/${path}`);
}

export async function generateDailyReport(payload) {
  const response = await fetch(apiUrl("/api/reports/daily/generate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function searchDailyReportReference(query, signal) {
  if (!query.trim()) return { query, items: [] };
  const response = await fetch(
    apiUrl(`/api/reports/daily/reference?q=${encodeURIComponent(query.trim())}`),
    { signal },
  );
  return parseResponse(response);
}