# -*- coding: utf-8 -*-
"""
app/reports/material_receipt/router.py (가칭)

기존 daily_report / weekly_report와 같은 위치 규칙(app/reports/<기능명>/)을 따른다.
이 파일 하나에 파서·업데이트 로직 호출부만 두고, 실제 로직은
app/services/material_receipt/{order_parser,xlsx_updater}.py 에 둔다고 가정한다.
(프로젝트의 기존 폴더 구조에 맞춰 import 경로만 조정하면 된다.)

엔드포인트 2개:
  POST /api/material-receipt/preview  — 미리보기만(파일 저장 안 함), 매칭/미매칭 목록 반환
  POST /api/material-receipt/apply    — 실제 반영 후 수정된 xlsx 파일을 반환(다운로드)
"""
import io
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import openpyxl

from app.services.material_receipt.order_parser import parse_order_doc
from app.services.material_receipt.xlsx_updater import apply_order_to_workbook

router = APIRouter(prefix="/api/material-receipt", tags=["material-receipt"])


def _save_upload_to_temp(upload: UploadFile, suffix: str) -> str:
    data = upload.file.read()
    if not data:
        raise HTTPException(400, f"{upload.filename}: 빈 파일입니다.")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _result_to_dict(result) -> dict:
    return {
        "sheet_period": f"{result.sheet_year}년 {result.sheet_month}월",
        "matched": [
            {"item_code": c, "item_name": n, "row": r, "quantity": q, "cell": addr}
            for c, n, r, q, addr in result.matched
        ],
        "unmatched": [
            {"item_code": c, "item_name": n, "reason": reason}
            for c, n, reason in result.unmatched
        ],
    }


@router.post("/preview")
async def preview(order_file: UploadFile = File(...), xlsx_file: UploadFile = File(...)):
    """실제로 저장하지 않고, 이 주문서를 적용하면 무슨 일이 벌어질지만 미리 보여준다."""
    order_path = _save_upload_to_temp(order_file, ".doc")
    xlsx_path = _save_upload_to_temp(xlsx_file, ".xlsx")
    try:
        order = parse_order_doc(order_path)
        wb = openpyxl.load_workbook(xlsx_path, data_only=False)
        result = apply_order_to_workbook(wb, order)  # 메모리 상에서만 계산, wb는 저장 안 함
        return {
            "status": "ok",
            "order": {
                "vendor": order.vendor,
                "written_at": order.written_at.isoformat() if order.written_at else None,
                "mgmt_no": order.mgmt_no,
                "item_count": len(order.items),
            },
            **_result_to_dict(result),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        Path(order_path).unlink(missing_ok=True)
        Path(xlsx_path).unlink(missing_ok=True)


@router.post("/apply")
async def apply(order_file: UploadFile = File(...), xlsx_file: UploadFile = File(...)):
    """실제로 반영한 뒤, 수정된 xlsx 파일을 그대로 응답으로 돌려준다(다운로드)."""
    order_path = _save_upload_to_temp(order_file, ".doc")
    xlsx_path = _save_upload_to_temp(xlsx_file, ".xlsx")
    try:
        order = parse_order_doc(order_path)
        wb = openpyxl.load_workbook(xlsx_path, data_only=False)
        result = apply_order_to_workbook(wb, order)

        if not result.matched:
            raise HTTPException(400, "매칭된 품목이 하나도 없어 저장하지 않았습니다. 품번을 확인하세요.")

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        import urllib.parse
        out_name = xlsx_file.filename or "자재입출고_수정.xlsx"
        ascii_fallback = "material_receipt_updated.xlsx"
        encoded_name = urllib.parse.quote(out_name)
        headers = {
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{encoded_name}"
            ),
            "X-Unmatched-Count": str(len(result.unmatched)),
        }
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        Path(order_path).unlink(missing_ok=True)
        Path(xlsx_path).unlink(missing_ok=True)
