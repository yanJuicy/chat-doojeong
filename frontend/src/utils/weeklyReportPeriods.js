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

// "N월 M주차" 라벨을 계산한다. 실제 33주치 원본 문서에서 확인된 규칙: 그 주의 월요일이
// 속한 달 기준으로, 그 달의 몇 번째 월요일인지로 정해진다(예: "1월 4주차"(01.26~01.30)
// 다음이 "2월 1주차"(02.02~02.06) — 주의 끝(금요일)이 다음 달로 넘어가도 라벨은 월요일
// 기준). 그래서 "이번 주가 몇 주차인지"를 사람이 직접 지정할 필요 없이, 그 주의 월요일
// 날짜 하나만 있으면 계산으로 항상 정확히 구할 수 있다.
export function getWeekOfMonthLabel(mondayDate) {
  const year = mondayDate.getFullYear();
  const month = mondayDate.getMonth();

  const cursor = new Date(year, month, 1);
  while (cursor.getDay() !== 1) cursor.setDate(cursor.getDate() + 1); // 그 달의 첫 월요일로 이동

  let weekOfMonth = 0;
  while (cursor <= mondayDate) {
    weekOfMonth += 1;
    cursor.setDate(cursor.getDate() + 7);
  }

  return `${month + 1}월 ${weekOfMonth}주차`;
}

// 실적 기간(이번 주 월~금)과 계획 기간(다음 주 월~금)을 오늘 날짜 기준으로 계산한다.
export function getDefaultReportPeriods(today = new Date()) {
  const currentMonday = mondayOf(today);
  const currentFriday = addDays(currentMonday, 4);
  const nextMonday = addDays(currentMonday, 7);
  const nextFriday = addDays(nextMonday, 4);

  return {
    currentPeriod: {
      start: formatLocalDate(currentMonday),
      end: formatLocalDate(currentFriday),
      label: getWeekOfMonthLabel(currentMonday),
    },
    nextPeriod: {
      start: formatLocalDate(nextMonday),
      end: formatLocalDate(nextFriday),
      label: getWeekOfMonthLabel(nextMonday),
    },
  };
}
