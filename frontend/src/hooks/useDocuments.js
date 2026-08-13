import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDocuments as requestDeleteDocuments,
  getDocuments,
  reextractDocument,
  retryDocument,
  runDocumentWorkers,
  updateDocumentLabels,
  uploadDocument,
} from "../api";
import { PROCESSING_STATUSES } from "../constants/documents";
import { uniqueLabels } from "../utils/labels";

export default function useDocuments(showToast) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploadItems, setUploadItems] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [workersStarting, setWorkersStarting] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const fileInputRef = useRef(null);

  const loadDocuments = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const data = await getDocuments();
      setDocuments(Array.isArray(data) ? data : []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!documents.some((document) => PROCESSING_STATUSES.has(document.status))) {
      return undefined;
    }
    const timer = window.setInterval(() => loadDocuments({ quiet: true }), 5000);
    return () => window.clearInterval(timer);
  }, [documents, loadDocuments]);

  const addFiles = (fileList) => {
    const nextFiles = Array.from(fileList ?? []);
    if (!nextFiles.length) return;
    setUploadItems((current) => [
      ...current,
      ...nextFiles.map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${Date.now()}-${Math.random()}`,
        file,
        labels: [],
      })),
    ]);
  };

  const removeFile = (id) => {
    setUploadItems((current) => current.filter((item) => item.id !== id));
  };

  const updateItemLabels = (id, labels) => {
    setUploadItems((current) =>
      current.map((item) =>
        item.id === id ? { ...item, labels: uniqueLabels(labels) } : item,
      ),
    );
  };

  const applyCommonLabels = (labels) => {
    if (!labels.length) return;
    setUploadItems((current) =>
      current.map((item) =>
        item.file.name.toLowerCase().endsWith(".zip")
          ? item
          : { ...item, labels: uniqueLabels([...item.labels, ...labels]) },
      ),
    );
  };

  const startWorkers = async () => {
    if (workersStarting) return;
    setWorkersStarting(true);
    setError("");
    try {
      await runDocumentWorkers();
      showToast("대기 중인 문서 처리를 시작했습니다.");
      window.setTimeout(() => loadDocuments({ quiet: true }), 800);
    } catch (workerError) {
      setError(`문서 처리를 시작하지 못했습니다. ${workerError.message}`);
    } finally {
      setWorkersStarting(false);
    }
  };

  const uploadFiles = async () => {
    if (!uploadItems.length || uploading) return;
    setUploading(true);
    let completed = 0;
    let duplicates = 0;
    let newlyRegistered = 0;
    let skipped = 0;
    const failures = [];

    for (const item of uploadItems) {
      try {
        const result = await uploadDocument(item.file, item.labels);
        completed += 1;
        if (item.file.name.toLowerCase().endsWith(".zip")) {
          const created = Array.isArray(result.created) ? result.created : [];
          duplicates += created.filter((entry) => entry.is_duplicate).length;
          newlyRegistered += created.filter((entry) => !entry.is_duplicate).length;
          skipped += Array.isArray(result.skipped) ? result.skipped.length : 0;
        } else if (result.is_duplicate) {
          duplicates += 1;
        } else {
          newlyRegistered += 1;
        }
      } catch (uploadError) {
        failures.push(`${item.file.name}: ${uploadError.message}`);
      }
    }

    setUploading(false);
    if (completed) {
      const duplicateText = duplicates ? ` · 중복 ${duplicates}개` : "";
      const skippedText = skipped ? ` · 건너뜀 ${skipped}개` : "";
      setUploadItems([]);
      await loadDocuments();

      if (newlyRegistered > 0) {
        try {
          setWorkersStarting(true);
          await runDocumentWorkers();
          showToast(
            `문서 ${newlyRegistered}개를 등록하고 처리를 시작했습니다${duplicateText}${skippedText}.`,
          );
        } catch (workerError) {
          setError(`문서는 등록됐지만 자동 처리를 시작하지 못했습니다. ${workerError.message}`);
          showToast(`문서 ${newlyRegistered}개가 등록됐습니다. 처리 시작 버튼을 눌러주세요.`);
        } finally {
          setWorkersStarting(false);
        }
      } else {
        showToast(`새로 처리할 문서가 없습니다${duplicateText}${skippedText}.`);
      }
    }

    if (failures.length) setError(failures.join("\n"));
  };

  const removeDocuments = async (documentIds) => {
    if (!documentIds.length || actionPending) return null;
    setActionPending(true);
    setError("");
    try {
      const result = await requestDeleteDocuments(documentIds);
      const deletedCount = result.deleted?.length ?? 0;
      const blockedText = result.blocked?.map((item) => item.reason).join("\n") ?? "";
      if (deletedCount) showToast(`문서 ${deletedCount}개를 삭제했습니다.`);
      if (blockedText) setError(blockedText);
      await loadDocuments({ quiet: true });
      return result;
    } catch (deleteError) {
      setError(`문서를 삭제하지 못했습니다. ${deleteError.message}`);
      return null;
    } finally {
      setActionPending(false);
    }
  };

  const saveLabels = async (documentId, labels) => {
    if (actionPending) return false;
    setActionPending(true);
    setError("");
    try {
      await updateDocumentLabels(documentId, uniqueLabels(labels));
      showToast("라벨을 저장하고 문서 재처리를 시작했습니다.");
      await loadDocuments({ quiet: true });
      return true;
    } catch (labelError) {
      setError(`라벨을 저장하지 못했습니다. ${labelError.message}`);
      return false;
    } finally {
      setActionPending(false);
    }
  };

  const retryProcessing = async (documentId) => {
    if (actionPending) return false;
    setActionPending(true);
    setError("");
    try {
      await retryDocument(documentId);
      await runDocumentWorkers();
      showToast("문서 처리를 다시 시작했습니다.");
      window.setTimeout(() => loadDocuments({ quiet: true }), 800);
      return true;
    } catch (retryError) {
      setError(`문서를 재시도하지 못했습니다. ${retryError.message}`);
      return false;
    } finally {
      setActionPending(false);
    }
  };

  const restartExtraction = async (documentId) => {
    if (actionPending) return false;
    setActionPending(true);
    setError("");
    try {
      await reextractDocument(documentId);
      showToast("원문 추출부터 다시 시작했습니다.");
      window.setTimeout(() => loadDocuments({ quiet: true }), 800);
      return true;
    } catch (reextractError) {
      setError(`원문 재추출을 시작하지 못했습니다. ${reextractError.message}`);
      return false;
    } finally {
      setActionPending(false);
    }
  };

  return {
    documents,
    loading,
    error,
    uploadItems,
    uploading,
    workersStarting,
    actionPending,
    fileInputRef,
    loadDocuments,
    addFiles,
    removeFile,
    updateItemLabels,
    applyCommonLabels,
    startWorkers,
    uploadFiles,
    removeDocuments,
    saveLabels,
    retryProcessing,
    restartExtraction,
  };
}
