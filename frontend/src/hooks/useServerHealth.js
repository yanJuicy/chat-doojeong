import { useEffect, useState } from "react";
import { getHealth } from "../api";

export default function useServerHealth() {
  const [health, setHealth] = useState({
    status: "checking",
    checks: {},
    reachable: false,
  });

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const data = await getHealth();
      if (!cancelled) setHealth(data);
    };

    check();
    const timer = window.setInterval(check, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return health;
}
