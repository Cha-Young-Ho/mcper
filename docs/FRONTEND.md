# docs/FRONTEND.md — 프론트엔드 관례

---

## 기술 스택

- **템플릿**: Jinja2 (FastAPI)
- **스타일**: Bootstrap 5
- **상호작용**: HTMX + vanilla JS
- **번들 크기**: ~55KB (Bootstrap 30KB + HTMX 15KB + admin.js 10KB)

---

## 디렉터리 구조

```
app/templates/
├── base.html              # 레이아웃
├── admin/
│   ├── dashboard.html     # 대시보드 (통계 카드 + 최근 활동 + 시스템 상태)
│   ├── specs.html         # 기획서 CRUD (검색, 정렬, 페이지네이션)
│   ├── rules.html         # 규칙 발행 (Global/Repo/App 탭 + 버전 이력)
│   ├── tools.html         # MCP 도구 통계
│   └── settings.html      # 패스워드 변경, Host 화이트리스트
└── static/
    ├── css/ (bootstrap.min.css, admin.css)
    └── js/ (htmx.min.js, admin.js)
```

---

## UI 패턴

- **폼**: `hx-post` + `hx-target` (HTMX 서버 렌더링)
- **모달**: Bootstrap 5 modal + `hx-get` 로딩
- **테이블**: 서버 렌더링 + `hx-get` 정렬/페이지네이션
- **갱신**: 대시보드 5초 간격 (SSE 또는 polling)
- **CSS 네이밍**: BEM (`.admin__header--active`)
- **반응형**: Mobile First (Bootstrap breakpoints)

---

## 접근성

- Alt 텍스트 (모든 이미지), ARIA 레이블 (폼 필드)
- 키보드 네비게이션, 색 대비 WCAG AA 이상

## 브라우저 호환성

Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
