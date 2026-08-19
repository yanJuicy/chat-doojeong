import { useCallback, useEffect, useState } from "react";
import {
  deleteWeeklyReportEntry,
  getWeeklyReportEntries,
  submitWeeklyReportChat,
  updateWeeklyReportEntry,
  uploadWeeklyReportDocument,
} from "../api";
import { getDefaultReportPeriods } from "../utils/weeklyReportPeriods";

const DEPARTMENT_STORAGE_KEY = "weeklyReportDepartment";

export default function useWeeklyReport(showToast) {
  const [department, setDepartment] = useState(
    () => window.localStorage.getItem(DEPARTMENT_STORAGE_KEY) ?? "",
  );
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [entries, setEntries] = useState([]);
  const [loadingEntries, setLoadingEntries] = useState(false);
  const [uploading, setUploading] = useState(false);

  const { currentPeriod, nextPeriod } = getDefaultReportPeriods();

  const loadEntries = useCallback(async () => {
    if (!department.trim()) {
      setEntries([]);
      return;
    }
    setLoadingEntries(true);
    try {
      const data = await getWeeklyReportEntries({
        start: currentPeriod.start,
        end: nextPeriod.end,
        department: department.trim(),
      });
      setEntries(data.entries ?? []);
    } catch (error) {
      showToast?.(error.message ?? "목록을 불러오지 못했습니다.");
    } finally {
      setLoadingEntries(false);
    }
    // currentPeriod/nextPeriod는 오늘 날짜 기준으로 매 렌더 새 객체가 생기므로 의존성에서 뺀다
    // (department가 바뀔 때만 다시 부르면 충분 — 날짜가 바뀌는 건 자정을 넘길 때뿐).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [department, showToast]);

  useEffect(() => {
    loadEntries();
  }, [loadEntries]);

  const updateDepartment = useCallback((value) => {
    setDepartment(value);
    window.localStorage.setItem(DEPARTMENT_STORAGE_KEY, value);
  }, []);

  const submit = useCallback(async () => {
    const trimmedDepartment = department.trim();
    const trimmedText = text.trim();
    if (!trimmedDepartment) {
      showToast?.("부서명을 먼저 입력해주세요.");
      return;
    }
    if (!trimmedText) return;

    setSubmitting(true);
    try {
      const result = await submitWeeklyReportChat({
        department: trimmedDepartment,
        text: trimmedText,
        currentPeriod,
        nextPeriod,
      });
      setText("");
      showToast?.(`${result.entries_created}개 항목이 저장됐습니다.`);
      await loadEntries();
    } catch (error) {
      showToast?.(error.message ?? "저장에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }, [department, text, currentPeriod, nextPeriod, loadEntries, showToast]);

  const editEntry = useCallback(
    async (entryId, content) => {
      try {
        await updateWeeklyReportEntry(entryId, content);
        setEntries((current) =>
          current.map((entry) => (entry.id === entryId ? { ...entry, content } : entry)),
        );
      } catch (error) {
        showToast?.(error.message ?? "수정에 실패했습니다.");
      }
    },
    [showToast],
  );

  const removeEntry = useCallback(
    async (entryId) => {
      try {
        await deleteWeeklyReportEntry(entryId);
        setEntries((current) => current.filter((entry) => entry.id !== entryId));
      } catch (error) {
        showToast?.(error.message ?? "삭제에 실패했습니다.");
      }
    },
    [showToast],
  );

  const uploadDocument = useCallback(
    async (file) => {
      setUploading(true);
      try {
        const result = await uploadWeeklyReportDocument(file);
        showToast?.(`${result.filename}: ${result.entries_created}개 항목이 저장됐습니다.`);
        if (!department.trim() && result.department) {
          // 부서명을 아직 안 정했으면, 문서에서 뽑힌 부서명으로 자동 채워서 바로 목록에 보이게 한다.
          updateDepartment(result.department);
        } else {
          await loadEntries();
        }
      } catch (error) {
        showToast?.(error.message ?? "업로드에 실패했습니다.");
      } finally {
        setUploading(false);
      }
    },
    [department, loadEntries, showToast, updateDepartment],
  );

  const currentWeekEntries = entries.filter(
    (entry) => entry.entry_type === "실적" && entry.period_start === currentPeriod.start,
  );
  const nextWeekEntries = entries.filter(
    (entry) => entry.entry_type === "계획" && entry.period_start === nextPeriod.start,
  );

  return {
    department,
    setDepartment: updateDepartment,
    text,
    setText,
    submitting,
    submit,
    loadingEntries,
    currentPeriod,
    nextPeriod,
    currentWeekEntries,
    nextWeekEntries,
    editEntry,
    removeEntry,
    uploadDocument,
    uploading,
  };
}
