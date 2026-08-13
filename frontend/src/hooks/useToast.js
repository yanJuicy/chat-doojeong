import { useCallback, useEffect, useRef, useState } from "react";

export default function useToast() {
  const [toast, setToast] = useState("");
  const timerRef = useRef(null);

  const showToast = useCallback((message) => {
    setToast(message);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setToast(""), 3200);
  }, []);

  useEffect(
    () => () => {
      window.clearTimeout(timerRef.current);
    },
    [],
  );

  return { toast, showToast };
}
