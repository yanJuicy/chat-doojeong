import { useEffect, useState } from "react";
import { searchLabels } from "../api";

export default function useLabelSuggestions(value) {
  const [suggestions, setSuggestions] = useState([]);

  useEffect(() => {
    const query = value.split(",").at(-1)?.trim() ?? "";
    if (!query) {
      setSuggestions([]);
      return undefined;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const labels = await searchLabels(query, controller.signal);
        setSuggestions(Array.isArray(labels) ? labels : []);
      } catch (error) {
        if (error.name !== "AbortError") setSuggestions([]);
      }
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  return [suggestions, setSuggestions];
}
