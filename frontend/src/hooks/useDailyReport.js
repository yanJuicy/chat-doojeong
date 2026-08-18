import { useState } from "react";
import { generateDailyReport, searchDailyReportReference } from "../api";

const today = () => new Date().toISOString().slice(0, 10);

export default function useDailyReport() {
  const [form, setForm] = useState({
    report_date: today(),
    author: "",
    tasks_completed: "",
    issues: "",
    tomorrow_plan: "",
    reference_note: "",
  });
  const [result, setResult] = useState(null);
  const [issues, setIssues] = useState([]);
  const [generating, setGenerating] = useState(false);

  const [query, setQuery] = useState("");
  const [referenceItems, setReferenceItems] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const generate = async () => {
    setGenerating(true);
    setIssues([]);
    try {
      const response = await generateDailyReport(form);
      if (response.status !== "ok") {
        setIssues(response.issues ?? []);
        setResult(null);
        return;
      }
      setResult(response);
    } catch (error) {
      setIssues([{ field: "_", message: error.message }]);
    } finally {
      setGenerating(false);
    }
  };

  const searchReference = async () => {
    setSearching(true);
    setSearchError(null);
    try {
      const response = await searchDailyReportReference(query);
      setReferenceItems(response.items ?? []);
    } catch (error) {
      setSearchError(error.message);
    } finally {
      setSearching(false);
    }
  };

  const appendToReferenceNote = (item) => {
    setForm((current) => ({
      ...current,
      reference_note: current.reference_note
        ? `${current.reference_note}\n\n[${item.title}]\n${item.snippet}`
        : `[${item.title}]\n${item.snippet}`,
    }));
  };

  const reset = () => {
    setForm({
      report_date: today(),
      author: "",
      tasks_completed: "",
      issues: "",
      tomorrow_plan: "",
      reference_note: "",
    });
    setResult(null);
    setIssues([]);
  };

  return {
    form, updateField, generate, generating, result, issues, reset,
    query, setQuery, searchReference, referenceItems, searching, searchError,
    appendToReferenceNote,
  };
}
