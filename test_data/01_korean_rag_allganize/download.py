"""
Allganize RAG-Evaluation-Dataset-KO 다운로드 스크립트

주의: 이 파일은 huggingface.co에 접근 가능한 본인 PC/서버에서 실행해야 합니다.
(현재 작업 환경은 보안상 huggingface.co 접근이 차단되어 있어 이 스크립트를 대신 실행해드릴 수 없습니다.)

사용법:
    pip install huggingface_hub
    python download.py
"""
from huggingface_hub import snapshot_download

if __name__ == "__main__":
    local_dir = snapshot_download(
        repo_id="allganize/RAG-Evaluation-Dataset-KO",
        repo_type="dataset",
        local_dir="./allganize_rag_ko_data",
    )
    print(f"다운로드 완료: {local_dir}")
