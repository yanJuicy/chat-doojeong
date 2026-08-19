# -*- coding: utf-8 -*-
"""
거래처 주문서(구매입고 export .doc — 실제로는 HTML) 파서.
Doc.doc / Doc__1_.doc / Doc__2_.doc 세 샘플 모두 이 구조를 따른다:
  1) 헤더 테이블(1행): 사업장/관리번호/작성자/작성일/상태/비고/납품사(협력사)/... 등 30개 컬럼
  2) 품목 테이블(N행): 순번/협력사LOT번호/품목(품번)/품명/내부LOT/재고단위/입고수량/상태
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser


@dataclass
class OrderItem:
    seq: int
    lot_no: str
    item_code: str      # 품번
    item_name: str      # 품명
    unit: str            # 재고단위
    quantity: float       # 입고수량


@dataclass
class OrderDocument:
    company: str          # 사업장 (예: (주)두정테크)
    mgmt_no: str           # 관리번호 (예: PRC-2608-067)
    author: str             # 작성자
    written_at: datetime     # 작성일
    vendor: str                # 납품사(협력사)
    warehouse: str               # 입고창고
    memo: str                     # 비고
    items: list = field(default_factory=list)


class _TableExtractor(HTMLParser):
    """중첩 없는 단순 <table><tr><td>/<th> 구조만 다루는 최소 파서."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._cur_table = None
        self._cur_row = None
        self._cur_cell = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._cur_table = []
        elif tag == "tr" and self._cur_table is not None:
            self._cur_row = []
        elif tag in ("td", "th") and self._cur_row is not None:
            self._cur_cell = []
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag == "table" and self._cur_table is not None:
            self.tables.append(self._cur_table)
            self._cur_table = None
        elif tag == "tr" and self._cur_row is not None:
            if self._cur_table is not None:
                self._cur_table.append(self._cur_row)
            self._cur_row = None
        elif tag in ("td", "th") and self._in_cell:
            text = "".join(self._cur_cell).strip()
            if self._cur_row is not None:
                self._cur_row.append(text)
            self._in_cell = False
            self._cur_cell = None

    def handle_data(self, data):
        if self._in_cell and self._cur_cell is not None:
            self._cur_cell.append(data)


def _parse_written_at(s: str) -> datetime:
    """'2026-08-19 오전 10:56:14' 형태를 파싱."""
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s*(오전|오후)?\s*(\d{1,2}):(\d{2}):(\d{2})", s)
    if not m:
        # 시간 없이 날짜만 있는 경우 대비
        m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m2:
            y, mo, d = map(int, m2.groups())
            return datetime(y, mo, d)
        raise ValueError(f"작성일 형식을 해석할 수 없습니다: {s!r}")
    y, mo, d, ampm, h, mi, se = m.groups()
    h = int(h)
    if ampm == "오후" and h != 12:
        h += 12
    if ampm == "오전" and h == 12:
        h = 0
    return datetime(int(y), int(mo), int(d), h, int(mi), int(se))


# 헤더 테이블의 컬럼명 -> 인덱스는 파일마다 살짝 다를 수 있어(있는 값만 채워짐),
# 라벨을 <th>에서 직접 읽어 순번을 그때그때 찾는다.
_HEADER_LABELS_WANTED = {
    "사업장": "company",
    "관리번호": "mgmt_no",
    "작성자": "author",
    "작성일": "written_at_raw",
    "비고": "memo",
    "납품사(협력사)": "vendor",
    "입고창고": "warehouse",
}
_ITEM_LABELS_WANTED = {
    "순번": "seq",
    "협력사 LOT 번호": "lot_no",
    "품목": "item_code",
    "품명": "item_name",
    "재고단위": "unit",
    "입고수량": "quantity",
}


def _match_label(header_text: str, wanted_keys) -> str | None:
    """헤더 셀 텍스트(뒤에 '[...]' 나 공백이 붙기도 함)를 미리 정의된 라벨과 느슨하게 매칭."""
    cleaned = re.sub(r"\[.*?\]", "", header_text).strip()
    for k in wanted_keys:
        if cleaned == k or cleaned.startswith(k):
            return k
    return None


def parse_order_doc(path: str) -> OrderDocument:
    with open(path, encoding="utf-8", errors="ignore") as f:
        html = f.read()

    parser = _TableExtractor()
    parser.feed(html)
    tables = [t for t in parser.tables if t]

    if len(tables) < 2:
        raise ValueError(f"예상한 테이블 2개(헤더+품목)를 찾지 못했습니다: {path}")

    header_table, item_table = tables[0], tables[1]

    # --- 헤더 테이블: th행(0) + 값행(1) ---
    header_labels = header_table[0]
    header_values = header_table[1]
    header_map = {}
    for label, value in zip(header_labels, header_values):
        key = _match_label(label, _HEADER_LABELS_WANTED)
        if key:
            header_map[_HEADER_LABELS_WANTED[key]] = value

    # --- 품목 테이블: th행(0) + 데이터행(1..) ---
    item_labels = item_table[0]
    label_to_col = {}
    for i, label in enumerate(item_labels):
        key = _match_label(label, _ITEM_LABELS_WANTED)
        if key:
            label_to_col[_ITEM_LABELS_WANTED[key]] = i

    items = []
    for row in item_table[1:]:
        if not any(row):
            continue

        def get(field_key, default=""):
            idx = label_to_col.get(field_key)
            if idx is None or idx >= len(row):
                return default
            return row[idx]

        qty_raw = get("quantity", "0").replace(",", "")
        try:
            qty = float(qty_raw) if qty_raw else 0.0
        except ValueError:
            qty = 0.0

        items.append(OrderItem(
            seq=int(get("seq", "0") or 0),
            lot_no=get("lot_no"),
            item_code=get("item_code"),
            item_name=get("item_name"),
            unit=get("unit"),
            quantity=qty,
        ))

    written_at_raw = header_map.get("written_at_raw", "")
    written_at = _parse_written_at(written_at_raw) if written_at_raw else None

    return OrderDocument(
        company=header_map.get("company", ""),
        mgmt_no=header_map.get("mgmt_no", ""),
        author=header_map.get("author", ""),
        written_at=written_at,
        vendor=header_map.get("vendor", ""),
        warehouse=header_map.get("warehouse", ""),
        memo=header_map.get("memo", ""),
        items=[it for it in items if it.item_code],
    )


if __name__ == "__main__":
    import sys
    doc = parse_order_doc(sys.argv[1])
    print(f"사업장: {doc.company}")
    print(f"관리번호: {doc.mgmt_no}")
    print(f"작성자: {doc.author}")
    print(f"작성일: {doc.written_at}")
    print(f"납품사: {doc.vendor}")
    print(f"입고창고: {doc.warehouse}")
    print(f"비고: {doc.memo}")
    print(f"품목 {len(doc.items)}건:")
    for it in doc.items:
        print(f"  - {it.item_code} | {it.item_name} | {it.quantity}{it.unit}")
