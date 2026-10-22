# 프론트엔드 협업 문서

이 폴더는 UI 담당의 설계·검토·백엔드 인계 문서입니다. 실제 API 원본은 `backend/app/models.py`와 `contracts/openapi.json`입니다.

- [RSS 스키마 점검과 팀원 전달 사항](RSS_SCHEMA_REVIEW.md)
- [라이브 RSS 필드 관측 기록](rss-field-observations.json)
- [8개 피드 후보 목록](rss-source-candidates.json): 활성 수집 설정이 아닌 검토 자료
- [타임라인 UI와 API 연결 범위](TIMELINE_UI.md)
- [작업 로그 안내](../worklogs/README.md)

화면만 적용할 때는 `frontend/src/`의 이번 변경 파일을 반영하세요. `backend/`, `database/`, `contracts/`를 덮어쓸 필요가 없습니다. 의존성이나 API 계약은 이번 UI 작업에서 변경하지 않았습니다.
