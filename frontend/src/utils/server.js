export function getServerView(health) {
  if (health.status === "checking") {
    return {
      key: "checking",
      label: "서버 확인 중",
      title: "백엔드 연결 상태를 확인하고 있습니다.",
    };
  }
  if (!health.reachable) {
    return {
      key: "offline",
      label: "서버 연결 안 됨",
      title: "FastAPI 서버가 실행 중인지 확인하세요.",
    };
  }
  if (health.status !== "ok") {
    const failed = Object.entries(health.checks ?? {})
      .filter(([, value]) => value !== "ok")
      .map(([name]) => name)
      .join(", ");
    return {
      key: "degraded",
      label: "일부 기능 점검 필요",
      title: failed ? `점검 필요: ${failed}` : "백엔드 일부 기능을 사용할 수 없습니다.",
    };
  }
  return {
    key: "online",
    label: "서버 정상",
    title: "FastAPI, DB, RAG가 정상 연결되었습니다.",
  };
}
