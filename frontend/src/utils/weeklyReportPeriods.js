// 이번 주/다음 주(월~금) 기간을 계산한다. toISOString()은 UTC로 변환하면서 날짜가
// 하루 밀릴 수 있어서(타임존 문제), 로컬 날짜 필드를 직접 조합해서 포맷한다.
function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function mondayOf(date) {
  const weekday = (date.getDay() + 6) % 7; // 월=0 ... 일=6
  const monday = new Date(date);
  monday.setDate(date.getDate() - weekday);
  return monday;
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(date.getDate() + days);
  return next;
}

// 실적 기간(이번 주 월~금)과 계획 기간(다음 주 월~금)을 오늘 날짜 기준으로 계산한다.
export function getDefaultReportPeriods(today = new Date()) {
  const currentMonday = mondayOf(today);
  const currentFriday = addDays(currentMonday, 4);
  const nextMonday = addDays(currentMonday, 7);
  const nextFriday = addDays(nextMonday, 4);

  return {
    currentPeriod: { start: formatLocalDate(currentMonday), end: formatLocalDate(currentFriday) },
    nextPeriod: { start: formatLocalDate(nextMonday), end: formatLocalDate(nextFriday) },
  };
}
