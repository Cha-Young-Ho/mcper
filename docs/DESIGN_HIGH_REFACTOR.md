# HIGH 우선순위 리팩터링 3개 항목 기술 설계서

**작성일**: 2026-03-30
**작성자**: @senior (아키텍처 설계)
**범위**: admin.py 모듈 분리, CodeNode 자동 파서 (AST 기반), Celery 모니터링

---

## 1. admin.py 모듈 분리 (1293줄 → 200줄씩)

### 1.1 문제 정의 (Why)

**현재 상태**:
- `app/routers/admin.py` 단일 파일에 1293줄
- 60+ 엔드포인트 혼재 (규칙, 스펙, 도구, 대시보드)
- 파일 유지보수 어려움, 함수 검색/수정 시간 증가
- 각 기능별 테스트 격리 어려움

**요구사항**:
- admin.py를 5개 라우터 모듈로 분리
- 각 모듈 200-300줄 범위 유지
- 공통 로직은 admin_base.py에 집중
- main.py의 라우터 등록 로직은 깔끔하게 유지

---

### 1.2 솔루션 아키텍처

#### 1.2.1 신규 파일 구조

```
app/routers/
├── admin_base.py          (신규, ~150줄) — 공통 헬퍼, 응답 포맷
├── admin_dashboard.py     (신규, ~200줄) — 대시보드, 통계
├── admin_rules.py         (신규, ~250줄) — 글로벌, 앱, 레포 규칙
├── admin_specs.py         (신규, ~350줄) — 기획서 CRUD, 검색, 업로드
├── admin_tools.py         (신규, ~150줄) — MCP 도구 카탈로그, 호출 통계
└── admin.py               (기존, 리다이렉트만 유지)
```

#### 1.2.2 공통 로직 분리: admin_base.py

```python
"""Admin 라우터 공통 헬퍼 및 응답 포맷."""

from typing import Any
from fastapi import Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.auth.dependencies import require_admin_user
from app.db.database import get_db
from app.templates import templates as global_templates

# 공통 의존성 번들
class AdminContext:
    """모든 admin 엔드포인트가 공유하는 의존성."""
    def __init__(
        self,
        user: str = Depends(require_admin_user),
        db: Session = Depends(get_db),
    ):
        self.user = user
        self.db = db

# 응답 포맷 표준화
def render_admin_html(
    template_name: str,
    context: dict[str, Any],
    status_code: int = 200,
):
    """Admin UI 템플릿 렌더링 (공통)."""
    context.setdefault("user", "admin")
    return global_templates.TemplateResponse(
        f"admin/{template_name}",
        context,
        status_code=status_code,
    )

def json_response(data: dict[str, Any], status_code: int = 200):
    """JSON 응답 포맷 (공통)."""
    return {"data": data, "status": "ok" if status_code < 400 else "error"}

# 에러 핸들러
class AdminError(Exception):
    """Admin 라우터 전용 예외."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

# 페이지네이션 헬퍼
def paginate(query, page: int = 1, per_page: int = 20):
    """ORM 쿼리 객체를 페이지네이션."""
    offset = (page - 1) * per_page
    total = query.count()
    items = query.offset(offset).limit(per_page).all()
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page,
    }
```

#### 1.2.3 admin_dashboard.py

```python
"""Admin 대시보드 + 통계."""

from fastapi import APIRouter, Request
from sqlalchemy import select, func
from app.routers.admin_base import AdminContext, render_admin_html
from app.db.models import Spec, SpecChunk
from app.db.rag_models import CodeNode, CodeEdge
from app.db.rule_models import GlobalRuleVersion, AppRuleVersion, RepoRuleVersion
from app.db.auth_models import User
from app.db.mcp_tool_stats import McpToolCallStat

router = APIRouter(prefix="/admin", tags=["admin_dashboard"])

@router.get("", name="admin_dashboard")
async def dashboard(request: Request, ctx: AdminContext):
    """Main dashboard page."""
    db = ctx.db

    # 통계 수집
    spec_count = db.scalar(select(func.count(Spec.id))) or 0
    chunk_count = db.scalar(select(func.count(SpecChunk.id))) or 0
    code_node_count = db.scalar(select(func.count(CodeNode.id))) or 0
    code_edge_count = db.scalar(select(func.count(CodeEdge.id))) or 0
    user_count = db.scalar(select(func.count(User.id))) or 0
    global_rule_version = db.scalar(
        select(func.max(GlobalRuleVersion.version))
    ) or 0

    # 최근 스펙
    recent_specs = db.scalars(
        select(Spec).order_by(Spec.created_at.desc()).limit(5)
    ).all()

    # 상위 MCP 도구
    top_tools = db.scalars(
        select(McpToolCallStat).order_by(McpToolCallStat.call_count.desc()).limit(10)
    ).all()

    return render_admin_html("index.html", {
        "request": request,
        "user": ctx.user,
        "stats": {
            "spec_count": spec_count,
            "chunk_count": chunk_count,
            "code_node_count": code_node_count,
            "code_edge_count": code_edge_count,
            "user_count": user_count,
            "global_rule_version": global_rule_version,
        },
        "recent_specs": recent_specs,
        "top_tools": top_tools,
    })

@router.get("/health", name="admin_health")
async def health_check(ctx: AdminContext):
    """헬스 체크 엔드포인트 (어드민 전용)."""
    db = ctx.db
    try:
        db.execute(select(1))
        return {"ok": True, "db": "connected"}
    except Exception as e:
        return {"ok": False, "db": str(e)}, 503
```

#### 1.2.4 admin_rules.py

```python
"""Admin 규칙 관리 (글로벌, 앱, 레포)."""

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.routers.admin_base import AdminContext, render_admin_html
from app.db.rule_models import GlobalRuleVersion, AppRuleVersion, RepoRuleVersion
from app.services.versioned_rules import (
    get_rules_markdown,
    publish_global,
    publish_app,
    publish_repo,
)

router = APIRouter(prefix="/admin", tags=["admin_rules"])

@router.get("/global-rules", name="admin_global_rules")
async def view_global_rules(request: Request, ctx: AdminContext):
    """View and edit global rules."""
    db = ctx.db
    latest = db.scalar(
        select(GlobalRuleVersion).order_by(GlobalRuleVersion.version.desc()).limit(1)
    )
    history = db.scalars(
        select(GlobalRuleVersion).order_by(GlobalRuleVersion.version.desc()).limit(20)
    ).all()

    return render_admin_html("global_rule_board.html", {
        "request": request,
        "user": ctx.user,
        "current": latest,
        "history": history,
    })

@router.post("/global-rules/publish", name="admin_publish_global_rule")
async def publish_global_rule(request: Request, ctx: AdminContext):
    """Publish new global rule version."""
    form = await request.form()
    body = form.get("body", "").strip()

    if not body:
        raise AdminError("Rule body cannot be empty")

    version = publish_global(ctx.db, body)
    return render_admin_html("global_rule_board.html", {
        "request": request,
        "user": ctx.user,
        "success": f"Published version {version}",
    })

@router.get("/app-rules", name="admin_app_rules")
async def list_app_rules(request: Request, ctx: AdminContext):
    """List all app rules."""
    db = ctx.db
    # 각 앱별 최신 버전만
    apps = db.scalars(
        select(AppRuleVersion).distinct(AppRuleVersion.app_name)
        .order_by(AppRuleVersion.app_name, AppRuleVersion.version.desc())
    ).all()

    return render_admin_html("app_rules_cards.html", {
        "request": request,
        "user": ctx.user,
        "apps": apps,
    })

@router.get("/app-rules/{app_name}", name="admin_app_rule_edit")
async def edit_app_rule(app_name: str, request: Request, ctx: AdminContext):
    """Edit specific app rule."""
    db = ctx.db
    latest = db.scalar(
        select(AppRuleVersion)
        .where(AppRuleVersion.app_name == app_name)
        .order_by(AppRuleVersion.version.desc())
        .limit(1)
    )

    return render_admin_html("app_rule_board.html", {
        "request": request,
        "user": ctx.user,
        "app_name": app_name,
        "current": latest,
    })

@router.post("/app-rules/{app_name}/publish", name="admin_publish_app_rule")
async def publish_app_rule(app_name: str, request: Request, ctx: AdminContext):
    """Publish new app rule version."""
    form = await request.form()
    body = form.get("body", "").strip()

    if not body:
        raise AdminError("Rule body cannot be empty")

    app_name, version = publish_app(ctx.db, app_name, body)
    return render_admin_html("app_rule_board.html", {
        "request": request,
        "user": ctx.user,
        "app_name": app_name,
        "success": f"Published version {version}",
    })

@router.get("/repo-rules", name="admin_repo_rules")
async def list_repo_rules(request: Request, ctx: AdminContext):
    """List all repo rule patterns."""
    db = ctx.db
    # 각 패턴별 최신 버전만
    patterns = db.scalars(
        select(RepoRuleVersion).distinct(RepoRuleVersion.pattern)
        .order_by(RepoRuleVersion.pattern, RepoRuleVersion.version.desc())
    ).all()

    return render_admin_html("repo_rules_cards.html", {
        "request": request,
        "user": ctx.user,
        "patterns": patterns,
    })

# (repo-rules/{pattern} 에디터 유사하게 구현)
```

#### 1.2.5 admin_specs.py

```python
"""Admin 기획서 관리 (CRUD, 검색, 업로드)."""

from fastapi import APIRouter, Request, File, UploadFile
from sqlalchemy import select
from app.routers.admin_base import AdminContext, render_admin_html, paginate
from app.db.models import Spec
from app.services.document_parser import parse_uploaded_file
from app.services.celery_client import enqueue_or_index_sync
from app.services.search_hybrid import hybrid_spec_search

router = APIRouter(prefix="/admin", tags=["admin_specs"])

@router.get("/specs", name="admin_specs_list")
async def list_specs(
    request: Request,
    ctx: AdminContext,
    app_target: str = None,
    page: int = 1,
):
    """List specs with optional app filter."""
    db = ctx.db
    query = select(Spec)
    if app_target:
        query = query.where(Spec.app_target == app_target)

    query = query.order_by(Spec.created_at.desc())
    result = paginate(query, page=page, per_page=20)

    return render_admin_html("specs_list_by_app.html", {
        "request": request,
        "user": ctx.user,
        "specs": result["items"],
        "pagination": result,
        "app_target": app_target,
    })

@router.get("/specs/{spec_id}", name="admin_spec_detail")
async def detail_spec(spec_id: int, request: Request, ctx: AdminContext):
    """View single spec."""
    db = ctx.db
    spec = db.get(Spec, spec_id)
    if not spec:
        raise AdminError(f"Spec {spec_id} not found", 404)

    return render_admin_html("plan_detail.html", {
        "request": request,
        "user": ctx.user,
        "spec": spec,
    })

@router.post("/specs", name="admin_create_spec")
async def create_spec(request: Request, ctx: AdminContext):
    """Create new spec."""
    form = await request.form()
    title = form.get("title", "").strip()
    content = form.get("content", "").strip()
    app_target = form.get("app_target", "").strip()

    spec = Spec(title=title, content=content, app_target=app_target)
    ctx.db.add(spec)
    ctx.db.commit()
    ctx.db.refresh(spec)

    # 비동기 인덱싱
    result = enqueue_or_index_sync(spec.id)

    return render_admin_html("plan_detail.html", {
        "request": request,
        "user": ctx.user,
        "spec": spec,
        "index_result": result,
    })

@router.delete("/specs/{spec_id}", name="admin_delete_spec")
async def delete_spec(spec_id: int, ctx: AdminContext):
    """Delete spec."""
    spec = ctx.db.get(Spec, spec_id)
    if not spec:
        raise AdminError(f"Spec {spec_id} not found", 404)

    ctx.db.delete(spec)  # cascade delete SpecChunk
    ctx.db.commit()

    return {"message": "Deleted"}

@router.get("/specs/search", name="admin_search_specs")
async def search_specs(
    request: Request,
    ctx: AdminContext,
    q: str = "",
    app_target: str = None,
):
    """Hybrid search specs."""
    if not q:
        return render_admin_html("specs_list_by_app.html", {
            "request": request,
            "user": ctx.user,
            "specs": [],
        })

    results, mode = hybrid_spec_search(ctx.db, q, app_target, top_n=10)
    return render_admin_html("specs_list_by_app.html", {
        "request": request,
        "user": ctx.user,
        "specs": results,
        "search_mode": mode,
        "query": q,
    })

@router.get("/specs/bulk-upload", name="admin_bulk_upload_form")
async def bulk_upload_form(request: Request, ctx: AdminContext):
    """Bulk upload form."""
    return render_admin_html("plan_bulk_upload.html", {
        "request": request,
        "user": ctx.user,
    })

@router.post("/specs/bulk-upload", name="admin_bulk_upload")
async def bulk_upload(request: Request, ctx: AdminContext):
    """Upload multiple spec files."""
    form = await request.form()
    files = form.getlist("files")

    results = []
    for file in files:
        if not isinstance(file, UploadFile):
            continue

        try:
            content = await file.read()
            text = parse_uploaded_file(file.filename, content)

            # Spec 생성
            spec = Spec(
                title=file.filename.rsplit(".", 1)[0],
                content=text,
                app_target=form.get("app_target", "").strip() or None,
            )
            ctx.db.add(spec)
            ctx.db.flush()

            # 인덱싱
            idx_result = enqueue_or_index_sync(spec.id)

            results.append({
                "filename": file.filename,
                "status": "ok",
                "spec_id": spec.id,
                "index": idx_result,
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e),
            })

    ctx.db.commit()

    return render_admin_html("plan_bulk_upload.html", {
        "request": request,
        "user": ctx.user,
        "results": results,
    })
```

#### 1.2.6 admin_tools.py

```python
"""Admin MCP 도구 카탈로그 + 호출 통계."""

from fastapi import APIRouter, Request
from sqlalchemy import select
from app.routers.admin_base import AdminContext, render_admin_html
from app.db.mcp_tool_stats import McpToolCallStat
from app.mcp_tools_docs import TOOL_DOCS

router = APIRouter(prefix="/admin", tags=["admin_tools"])

@router.get("/tools", name="admin_tools_list")
async def list_tools(request: Request, ctx: AdminContext):
    """View MCP tools catalog and stats."""
    db = ctx.db

    # 모든 도구 메타데이터
    tools = TOOL_DOCS

    # DB에서 호출 통계
    stats = {
        row.tool_name: row.call_count
        for row in db.scalars(select(McpToolCallStat)).all()
    }

    # 도구에 통계 추가
    for tool in tools:
        tool["call_count"] = stats.get(tool["name"], 0)

    return render_admin_html("tools.html", {
        "request": request,
        "user": ctx.user,
        "tools": tools,
    })
```

#### 1.2.7 기존 admin.py는 라우터 컬렉션으로 변환

```python
"""Admin 라우터 통합 (하위 모듈 import)."""

from fastapi import APIRouter
from .admin_dashboard import router as dashboard_router
from .admin_rules import router as rules_router
from .admin_specs import router as specs_router
from .admin_tools import router as tools_router

# 모든 라우터를 하나의 "admin" 라우터에 포함
router = APIRouter()
router.include_router(dashboard_router)
router.include_router(rules_router)
router.include_router(specs_router)
router.include_router(tools_router)

# main.py에서는 그냥 app.include_router(router) 호출
```

---

### 1.3 main.py 라우터 등록 (변경사항 최소)

```python
from app.routers import admin

# ...

if _ADMIN_ENABLED:
    # 기존: app.include_router(admin_router, prefix="/admin", ...)
    # 신규: 모든 라우터이 이미 /admin 프리픽스를 가짐
    app.include_router(admin.router)
```

---

### 1.4 신규/수정 파일

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/routers/admin_base.py` | 신규 | 공통 헬퍼, AdminContext, 응답 포맷 |
| `app/routers/admin_dashboard.py` | 신규 | GET /admin, 통계, 헬스 체크 |
| `app/routers/admin_rules.py` | 신규 | 규칙 관리 (글로벌, 앱, 레포) |
| `app/routers/admin_specs.py` | 신규 | 스펙 CRUD, 검색, 업로드 |
| `app/routers/admin_tools.py` | 신규 | MCP 도구 카탈로그 |
| `app/routers/admin.py` | 수정 | 하위 라우터 import, 통합 |
| `app/main.py` | 수정 | 라우터 등록 로직 단순화 |

---

### 1.5 구현 체크리스트

- [ ] admin_base.py 생성 (AdminContext, render_admin_html, 공통 함수)
- [ ] admin_dashboard.py 생성 (GET /admin, 통계, 헬스 체크)
- [ ] admin_rules.py 생성 (규칙 관리 엔드포인트)
- [ ] admin_specs.py 생성 (스펙 CRUD, 검색, 업로드)
- [ ] admin_tools.py 생성 (도구 카탈로그)
- [ ] admin.py 수정 (하위 라우터 포함)
- [ ] main.py의 라우터 등록 로직 단순화
- [ ] 각 라우터별 테스트 추가

---

### 1.6 테스트 시나리오

#### 정상 케이스
1. GET /admin → 대시보드 렌더링
2. GET /admin/rules → 규칙 목록
3. GET /admin/specs → 기획서 목록
4. POST /admin/specs → 기획서 생성
5. GET /admin/tools → 도구 카탈로그

#### 엣지 케이스
1. 존재하지 않는 spec_id 조회
   - 예상: 404
2. 빈 규칙 본문 제출
   - 예상: 400 "Rule body cannot be empty"

---

### 1.7 위험 및 완화 전략

| 위험 | 완화 방법 |
|------|----------|
| 라우터 등록 순서 실수 (경로 충돌) | 각 라우터의 prefix가 명확, include_router 순서는 상관없음 |
| 공통 의존성 (AdminContext) 미사용 | 표준화된 AdminContext 사용으로 일관성 보장 |
| 기존 템플릿 경로 변경 | "admin/..." 경로는 동일하게 유지 |

---

---

## 2. CodeNode 자동 파서 (AST 기반)

### 2.1 문제 정의 (Why)

**현재 상태**:
- CodeNode 테이블 존재하지만 자동 인덱싱 파서 없음
- push_code_index는 이미 파싱된 노드를 수동으로 받음
- AST 크롤러 부재 → MCP 클라이언트가 직접 파싱 후 전송해야 함
- 코드 언어별 파싱 전략 부재

**요구사항**:
- Python, JavaScript, Java 자동 파싱 (AST 또는 정적 분석)
- 심볼 추출 (클래스, 함수, 변수)
- 의존성 그래프 생성 (CodeEdge)
- 언어별 플러그인 아키텍처

---

### 2.2 솔루션 아키텍처

#### 2.2.1 파서 인터페이스

**`app/services/code_parser.py`** (통합 인터페이스):

```python
"""코드 파서 인터페이스 및 팩토리."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum

class CodeKind(str, Enum):
    """코드 심볼 종류."""
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"
    CONSTANT = "constant"

@dataclass
class CodeSymbol:
    """추출된 코드 심볼."""
    stable_id: str          # 버전 안정적 ID (e.g., module.ClassName.method_name)
    symbol_name: str        # 심볼 이름 (e.g., method_name)
    kind: CodeKind
    file_path: str
    line_start: int
    line_end: int
    content: str            # 원본 코드
    docstring: Optional[str] = None
    metadata: dict = None

@dataclass
class CodeDependency:
    """코드 간 의존성."""
    source_stable_id: str   # 호출하는 쪽
    target_stable_id: str   # 호출되는 쪽
    relation: str           # "CALLS", "IMPORTS", "INHERITS"
    metadata: dict = None

class CodeParserBase(ABC):
    """파서 기본 클래스."""

    @abstractmethod
    def parse(self, file_path: str, content: str) -> tuple[list[CodeSymbol], list[CodeDependency]]:
        """
        파일 내용을 파싱해서 심볼과 의존성 반환.
        Returns: (symbols, dependencies)
        """
        pass

    def supports_language(self, file_ext: str) -> bool:
        """파일 확장자 지원 여부."""
        return False
```

#### 2.2.2 Python 파서

**`app/services/code_parser_python.py`**:

```python
"""Python AST 기반 파서."""

import ast
from typing import Optional
from app.services.code_parser import (
    CodeParserBase, CodeSymbol, CodeDependency, CodeKind
)

class PythonCodeParser(CodeParserBase):
    """Python AST 파서."""

    def supports_language(self, file_ext: str) -> bool:
        return file_ext.lower() == ".py"

    def parse(self, file_path: str, content: str) -> tuple[list[CodeSymbol], list[CodeDependency]]:
        """AST 파싱."""
        symbols = []
        dependencies = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return [], []  # 파싱 실패 → 빈 결과

        # 1) 심볼 추출
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # 클래스
                stable_id = f"{file_path}:{node.name}"
                docstring = ast.get_docstring(node)
                content_lines = content.splitlines()[node.lineno-1:node.end_lineno]
                symbol_content = "\n".join(content_lines)

                symbols.append(CodeSymbol(
                    stable_id=stable_id,
                    symbol_name=node.name,
                    kind=CodeKind.CLASS,
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    content=symbol_content,
                    docstring=docstring,
                ))

                # 클래스 메서드
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_stable_id = f"{stable_id}.{item.name}"
                        method_docstring = ast.get_docstring(item)
                        method_lines = content.splitlines()[item.lineno-1:item.end_lineno]
                        method_content = "\n".join(method_lines)

                        symbols.append(CodeSymbol(
                            stable_id=method_stable_id,
                            symbol_name=item.name,
                            kind=CodeKind.METHOD,
                            file_path=file_path,
                            line_start=item.lineno,
                            line_end=item.end_lineno or item.lineno,
                            content=method_content,
                            docstring=method_docstring,
                        ))

            elif isinstance(node, ast.FunctionDef) and not isinstance(getattr(node, '_parent', None), ast.ClassDef):
                # 모듈 수준 함수
                stable_id = f"{file_path}:{node.name}"
                docstring = ast.get_docstring(node)
                content_lines = content.splitlines()[node.lineno-1:node.end_lineno]
                symbol_content = "\n".join(content_lines)

                symbols.append(CodeSymbol(
                    stable_id=stable_id,
                    symbol_name=node.name,
                    kind=CodeKind.FUNCTION,
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    content=symbol_content,
                    docstring=docstring,
                ))

            elif isinstance(node, ast.Import):
                # import 문
                for alias in node.names:
                    dependencies.append(CodeDependency(
                        source_stable_id=file_path,
                        target_stable_id=alias.name,
                        relation="IMPORTS",
                    ))

            elif isinstance(node, ast.ImportFrom):
                # from X import Y
                module = node.module or ""
                for alias in node.names:
                    dependencies.append(CodeDependency(
                        source_stable_id=file_path,
                        target_stable_id=f"{module}.{alias.name}",
                        relation="IMPORTS",
                    ))

        return symbols, dependencies
```

#### 2.2.3 JavaScript 파서

**`app/services/code_parser_js.py`**:

```python
"""JavaScript 정규식 기반 간단한 파서."""

import re
from typing import Optional
from app.services.code_parser import (
    CodeParserBase, CodeSymbol, CodeDependency, CodeKind
)

class JavaScriptCodeParser(CodeParserBase):
    """JavaScript 파서 (정규식 기반, 완전한 AST는 아님)."""

    def supports_language(self, file_ext: str) -> bool:
        return file_ext.lower() in [".js", ".ts", ".jsx", ".tsx"]

    def parse(self, file_path: str, content: str) -> tuple[list[CodeSymbol], list[CodeDependency]]:
        """정규식 기반 파싱."""
        symbols = []
        dependencies = []
        lines = content.splitlines()

        # 1) 클래스 추출
        class_pattern = r'class\s+(\w+)(?:\s+extends\s+(\w+))?'
        for match in re.finditer(class_pattern, content):
            class_name = match.group(1)
            parent_class = match.group(2)
            line_no = content[:match.start()].count('\n') + 1

            symbols.append(CodeSymbol(
                stable_id=f"{file_path}:{class_name}",
                symbol_name=class_name,
                kind=CodeKind.CLASS,
                file_path=file_path,
                line_start=line_no,
                line_end=line_no + 10,  # 근사값
                content=match.group(0),
            ))

            if parent_class:
                dependencies.append(CodeDependency(
                    source_stable_id=f"{file_path}:{class_name}",
                    target_stable_id=parent_class,
                    relation="INHERITS",
                ))

        # 2) 함수 추출 (async function / function / arrow)
        function_patterns = [
            r'(?:async\s+)?function\s+(\w+)',
            r'const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
        ]
        for pattern in function_patterns:
            for match in re.finditer(pattern, content):
                func_name = match.group(1)
                line_no = content[:match.start()].count('\n') + 1

                symbols.append(CodeSymbol(
                    stable_id=f"{file_path}:{func_name}",
                    symbol_name=func_name,
                    kind=CodeKind.FUNCTION,
                    file_path=file_path,
                    line_start=line_no,
                    line_end=line_no + 5,
                    content=match.group(0),
                ))

        # 3) import/require 추출
        import_patterns = [
            r"import\s+(?:\{[^}]*\}\s+)?from\s+['\"]([^'\"]+)['\"]",
            r"require\(['\"]([^'\"]+)['\"]\)",
        ]
        for pattern in import_patterns:
            for match in re.finditer(pattern, content):
                module = match.group(1)
                dependencies.append(CodeDependency(
                    source_stable_id=file_path,
                    target_stable_id=module,
                    relation="IMPORTS",
                ))

        return symbols, dependencies
```

#### 2.2.4 파서 팩토리

**`app/services/code_parser_factory.py`**:

```python
"""파서 선택 팩토리."""

from pathlib import Path
from app.services.code_parser import CodeParserBase
from app.services.code_parser_python import PythonCodeParser
from app.services.code_parser_js import JavaScriptCodeParser

class CodeParserFactory:
    """파일 확장자에 따라 적절한 파서 선택."""

    _parsers = [
        PythonCodeParser(),
        JavaScriptCodeParser(),
        # 향후: JavaCodeParser(), etc.
    ]

    @staticmethod
    def get_parser(file_path: str) -> CodeParserBase | None:
        """파일 확장자에 맞는 파서 반환."""
        ext = Path(file_path).suffix
        for parser in CodeParserFactory._parsers:
            if parser.supports_language(ext):
                return parser
        return None

    @staticmethod
    def parse(file_path: str, content: str) -> tuple[list, list]:
        """파일 내용 파싱."""
        parser = CodeParserFactory.get_parser(file_path)
        if not parser:
            return [], []
        return parser.parse(file_path, content)
```

#### 2.2.5 MCP 도구 개선

**`app/tools/rag_tools.py` → push_code_index_impl 수정**:

```python
from app.services.code_parser_factory import CodeParserFactory
from app.db.database import SessionLocal
from app.db.rag_models import CodeNode, CodeEdge

async def push_code_index_impl(
    app_target: str,
    file_paths: list[str],
    nodes: list[dict] = None,  # 선택: 수동 입력
    edges: list[dict] = None,  # 선택: 수동 입력
    auto_parse: bool = True,   # ✨ 신규: 자동 파싱
) -> str:
    """
    코드 인덱스 푸시.
    auto_parse=True: 파일 내용에서 자동 파싱 (nodes/edges 무시)
    auto_parse=False: 수동 입력 nodes/edges 사용
    """
    db = SessionLocal()
    try:
        if auto_parse and nodes is None:
            # ✨ 자동 파싱 모드
            symbols, dependencies = [], []
            for file_path in file_paths:
                # 파일 읽기 (클라이언트에서 전송받은 내용 또는 로컬)
                # 여기서는 MCP 규약상 클라이언트가 content 제공해야 함
                # 따라서 수정: file_contents dict 추가
                pass
        else:
            # 수동 입력 모드 (기존 로직)
            symbols = nodes or []
            dependencies = edges or []

        # (기존 DB 저장 로직)
        return json.dumps({"ok": True, "queued": False})

    finally:
        db.close()
```

더 정확하게, 파일 내용을 MCP 요청에 포함시키는 방식:

```python
# MCP 도구 스펙 수정
async def push_code_index_impl(
    app_target: str,
    file_contents: list[dict],  # [{"path": "...", "content": "..."}]
    auto_parse: bool = True,
) -> str:
    """
    코드 인덱스 푸시 (자동 파싱 지원).

    auto_parse=True: 파일 내용에서 자동 파싱
    auto_parse=False: 클라이언트가 이미 파싱한 결과를 수동 입력
    """
    db = SessionLocal()
    try:
        symbols_all = []
        dependencies_all = []

        for file_dict in file_contents:
            file_path = file_dict["path"]
            content = file_dict["content"]

            if auto_parse:
                # ✨ 자동 파싱
                symbols, dependencies = CodeParserFactory.parse(file_path, content)
                symbols_all.extend(symbols)
                dependencies_all.extend(dependencies)
            else:
                # 수동 입력은 별도 MCP 도구로 제공
                pass

        # CodeNode, CodeEdge 저장
        # (기존 로직)

        return json.dumps({"ok": True, "nodes_count": len(symbols_all), ...})

    finally:
        db.close()
```

---

### 2.3 신규/수정 파일

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/services/code_parser.py` | 신규 | 파서 인터페이스, 기본 클래스 |
| `app/services/code_parser_python.py` | 신규 | Python AST 파서 |
| `app/services/code_parser_js.py` | 신규 | JavaScript 정규식 파서 |
| `app/services/code_parser_factory.py` | 신규 | 파서 팩토리 |
| `app/tools/rag_tools.py` | 수정 | push_code_index_impl에 auto_parse 파라미터 추가 |

---

### 2.4 API 스펙

#### MCP 도구: push_code_index

**요청**:
```json
{
  "app_target": "my-app",
  "file_contents": [
    {
      "path": "src/main.py",
      "content": "class MyClass:\n    def method(self): pass"
    },
    {
      "path": "src/utils.js",
      "content": "function helper() { }"
    }
  ],
  "auto_parse": true
}
```

**응답 (200 OK)**:
```json
{
  "ok": true,
  "nodes_count": 5,
  "edges_count": 3,
  "languages": ["python", "javascript"]
}
```

---

### 2.5 구현 체크리스트

- [ ] CodeParserBase 인터페이스 정의
- [ ] PythonCodeParser 구현 (AST)
- [ ] JavaScriptCodeParser 구현 (정규식)
- [ ] CodeParserFactory 구현
- [ ] push_code_index_impl에 auto_parse 로직 추가
- [ ] 파일 내용 수신 방식 결정 (base64 인코딩?)
- [ ] CodeNode, CodeEdge 저장 로직 구현
- [ ] 테스트: 각 언어별 파싱 정확도

---

### 2.6 테스트 시나리오

#### 정상 케이스
1. Python 파일 자동 파싱
   - 예상: 클래스 2개, 함수 3개, import 5개 추출
2. JavaScript 파일 자동 파싱
   - 예상: 클래스 1개, 함수 4개, import 2개 추출
3. 다중 파일 배치 처리
   - 예상: 모든 파일 처리, 의존성 병합

#### 엣지 케이스
1. 문법 오류가 있는 파일
   - 예상: 그 파일은 스킵, 다른 파일은 처리
2. 지원하지 않는 언어 (.go, .rs)
   - 예상: 파서 없음 → 스킵

#### 실패 케이스
1. 빈 파일
   - 예상: 심볼 0개, 의존성 0개 반환

---

### 2.7 위험 및 완화 전략

| 위험 | 완화 방법 |
|------|----------|
| Python AST 파싱 오류 → 서버 크래시 | try-except로 SyntaxError 포착 |
| JS 정규식이 완전하지 않음 | 정규식으로 "최대한" 추출, 부정확은 인정 |
| 파일 크기가 크면 메모리 문제 | 대용량 파일은 청크 처리 (향후) |
| 의존성 그래프가 순환 참조 포함 | BFS 탐색에서 visited 세트 사용 |

---

---

## 3. Celery 모니터링 (실패 추적 + 대시보드)

### 3.1 문제 정의 (Why)

**현재 상태**:
- Celery 태스크 실패 시 DB 기록 없음
- 모니터링 대시보드 부재
- Redis 연결 끊김 시 폴백 없음
- 큐 깊이, 작업 상태 추적 불가

**요구사항**:
- FailedTask 테이블: 실패 스펙 + 에러 메시지 저장
- 재시도 로직: 실패 스펙 수동 재시도 버튼
- Admin UI: 실패 목록, 통계, 재시도 관리
- 헬스 체크: Redis, Celery 상태 모니터링

---

### 3.2 솔루션 아키텍처

#### 3.2.1 DB 스키마

**`app/db/celery_models.py`** (신규):

```python
"""Celery 모니터링 모델."""

from datetime import datetime
from sqlalchemy import Integer, String, Text, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.database import Base
import enum

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    REVOKED = "revoked"

class FailedTask(Base):
    """실패한 Celery 태스크 기록."""

    __tablename__ = "failed_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)  # "index_spec"

    # 실패 대상 (spec_id, code_app 등)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "spec", "code_batch"
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # 에러 정보
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 재시도
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    # 상태
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus),
        default=TaskStatus.FAILED,
        nullable=False
    )

    # 타임스탬프
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 메타데이터
    metadata: Mapped[dict | None] = mapped_column(
        sqlalchemy.JSON, nullable=True
    )
```

#### 3.2.2 Celery 태스크 개선

**`app/worker/tasks.py`** 수정:

```python
from app.db.celery_models import FailedTask, TaskStatus
from datetime import datetime, timezone

@celery_app.task(name="index_spec", bind=True, max_retries=3)
def index_spec_task(self, spec_id: int) -> dict:
    """
    기획서 인덱싱 (실패 추적 포함).
    """
    db = SessionLocal()
    try:
        # 기존 로직
        result = index_spec_synchronously(db, spec_id)

        # 성공 시: 기존 실패 기록 resolve
        failed_task = db.scalar(
            select(FailedTask)
            .where(FailedTask.task_id == self.request.id)
        )
        if failed_task:
            failed_task.status = TaskStatus.SUCCESS
            failed_task.resolved_at = datetime.now(timezone.utc)
            db.add(failed_task)

        db.commit()
        return result

    except Exception as exc:
        # ✨ 실패 로깅
        error_message = str(exc)
        import traceback
        tb_str = traceback.format_exc()

        # FailedTask 생성/업데이트
        failed_task = db.scalar(
            select(FailedTask)
            .where(FailedTask.task_id == self.request.id)
        )
        if not failed_task:
            failed_task = FailedTask(
                task_id=self.request.id,
                task_name="index_spec",
                entity_type="spec",
                entity_id=spec_id,
                error_message=error_message,
                traceback=tb_str,
                max_retries=self.max_retries,
            )
        else:
            failed_task.retry_count += 1
            failed_task.error_message = error_message
            failed_task.traceback = tb_str
            failed_task.failed_at = datetime.now(timezone.utc)

        db.add(failed_task)
        db.commit()

        # 재시도
        if self.request.retries < self.max_retries:
            failed_task.status = TaskStatus.RETRYING
            db.add(failed_task)
            db.commit()

            raise self.retry(exc=exc, countdown=60)  # 60초 후 재시도
        else:
            failed_task.status = TaskStatus.FAILED
            db.add(failed_task)
            db.commit()
            logger.error(f"Task {self.request.id} failed after {self.max_retries} retries: {error_message}")
            raise

    finally:
        db.close()

    return {"ok": True, "error": "unreachable"}
```

#### 3.2.3 모니터링 서비스

**`app/services/celery_monitoring.py`** (신규):

```python
"""Celery 모니터링."""

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.db.celery_models import FailedTask, TaskStatus
from app.worker.celery_app import celery_app
import logging

logger = logging.getLogger(__name__)

def get_failed_tasks(db: Session, limit: int = 50) -> list[FailedTask]:
    """최근 실패 태스크 조회."""
    return db.scalars(
        select(FailedTask)
        .where(FailedTask.status == TaskStatus.FAILED)
        .order_by(FailedTask.failed_at.desc())
        .limit(limit)
    ).all()

def get_failed_task_by_entity(db: Session, entity_type: str, entity_id: int) -> FailedTask | None:
    """특정 엔티티의 실패 기록 조회."""
    return db.scalar(
        select(FailedTask)
        .where(
            (FailedTask.entity_type == entity_type) &
            (FailedTask.entity_id == entity_id) &
            (FailedTask.status == TaskStatus.FAILED)
        )
        .order_by(FailedTask.failed_at.desc())
        .limit(1)
    )

def retry_failed_task(db: Session, failed_task_id: int) -> bool:
    """실패한 태스크 재시도."""
    failed_task = db.get(FailedTask, failed_task_id)
    if not failed_task:
        return False

    # 태스크 유형에 따라 재시도 큐에 추가
    if failed_task.task_name == "index_spec":
        celery_app.send_task(
            "index_spec",
            args=(failed_task.entity_id,),
            queue="celery",
        )
        failed_task.retry_count += 1
        failed_task.status = TaskStatus.RETRYING
        db.add(failed_task)
        db.commit()
        return True

    return False

def get_celery_stats(db: Session) -> dict:
    """Celery 통계."""
    stats = {
        "total_failed": db.scalar(select(func.count(FailedTask.id))) or 0,
        "failed_by_status": {},
        "avg_retry_count": 0,
    }

    # 상태별 집계
    by_status = db.execute(
        select(FailedTask.status, func.count(FailedTask.id))
        .group_by(FailedTask.status)
    ).all()
    stats["failed_by_status"] = {str(status): count for status, count in by_status}

    # 평균 재시도
    avg = db.scalar(select(func.avg(FailedTask.retry_count)))
    stats["avg_retry_count"] = float(avg) if avg else 0

    # Redis 상태 (선택)
    try:
        from app.services.celery_client import celery_app
        celery_stats = celery_app.control.inspect().active()
        stats["active_tasks"] = sum(len(v) for v in celery_stats.values()) if celery_stats else 0
    except Exception as e:
        logger.warning(f"Failed to get Celery active tasks: {e}")
        stats["active_tasks"] = None

    return stats
```

#### 3.2.4 Admin 라우터

**`app/routers/admin_monitoring.py`** (신규):

```python
"""Admin 모니터링 대시보드."""

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from app.routers.admin_base import AdminContext, render_admin_html, paginate
from app.db.celery_models import FailedTask
from app.services.celery_monitoring import (
    get_failed_tasks,
    get_celery_stats,
    retry_failed_task,
)

router = APIRouter(prefix="/admin", tags=["admin_monitoring"])

@router.get("/monitoring", name="admin_monitoring")
async def monitoring_dashboard(request: Request, ctx: AdminContext):
    """Celery 모니터링 대시보드."""
    failed_tasks = get_failed_tasks(ctx.db, limit=20)
    stats = get_celery_stats(ctx.db)

    return render_admin_html("monitoring.html", {
        "request": request,
        "user": ctx.user,
        "failed_tasks": failed_tasks,
        "stats": stats,
    })

@router.get("/monitoring/failed", name="admin_failed_tasks")
async def list_failed_tasks(request: Request, ctx: AdminContext, page: int = 1):
    """실패 태스크 목록 (페이지네이션)."""
    query = select(FailedTask).order_by(FailedTask.failed_at.desc())
    result = paginate(query, page=page, per_page=20)

    return render_admin_html("monitoring_failed.html", {
        "request": request,
        "user": ctx.user,
        "tasks": result["items"],
        "pagination": result,
    })

@router.post("/monitoring/failed/{failed_task_id}/retry", name="admin_retry_failed_task")
async def retry_task(failed_task_id: int, ctx: AdminContext):
    """실패 태스크 재시도."""
    if not retry_failed_task(ctx.db, failed_task_id):
        raise HTTPException(status_code=404, detail="Task not found")

    return {"message": "Task queued for retry"}

@router.delete("/monitoring/failed/{failed_task_id}", name="admin_delete_failed_task")
async def delete_failed_task(failed_task_id: int, ctx: AdminContext):
    """실패 태스크 레코드 삭제."""
    task = ctx.db.get(FailedTask, failed_task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ctx.db.delete(task)
    ctx.db.commit()

    return {"message": "Deleted"}
```

#### 3.2.5 헬스 체크 확장

**`app/main.py` → GET /health/rag** 수정:

```python
@app.get("/health/rag", name="health_rag")
async def health_rag(db: Session = Depends(get_db)):
    """RAG + Celery 헬스 체크."""
    try:
        # DB
        db.execute(select(1))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Celery 큐 깊이
    try:
        from app.worker.celery_app import celery_app
        inspect = celery_app.control.inspect()

        # 활성 태스크
        active = inspect.active()
        active_count = sum(len(v) for v in active.values()) if active else 0

        # 예약된 태스크 (큐)
        reserved = inspect.reserved()
        reserved_count = sum(len(v) for v in reserved.values()) if reserved else 0

        celery_status = {
            "ok": True,
            "active_tasks": active_count,
            "reserved_tasks": reserved_count,
        }
    except Exception as e:
        celery_status = {"ok": False, "error": str(e)}

    # 실패 태스크
    failed_count = db.scalar(
        select(func.count(FailedTask.id))
        .where(FailedTask.status == TaskStatus.FAILED)
    ) or 0

    return {
        "db": db_status,
        "celery": celery_status,
        "failed_tasks": failed_count,
    }
```

---

### 3.3 신규/수정 파일

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/db/celery_models.py` | 신규 | FailedTask, TaskStatus 모델 |
| `app/services/celery_monitoring.py` | 신규 | 실패 추적, 재시도 로직 |
| `app/routers/admin_monitoring.py` | 신규 | 모니터링 대시보드 라우터 |
| `app/worker/tasks.py` | 수정 | index_spec_task에 실패 로깅 로직 |
| `app/main.py` | 수정 | GET /health/rag 확장, FailedTask import |
| `app/db/database.py` | 수정 | _apply_lightweight_migrations에 FailedTask 테이블 생성 |
| `app/templates/admin/monitoring.html` | 신규 | 모니터링 대시보드 |
| `app/templates/admin/monitoring_failed.html` | 신규 | 실패 목록 |

---

### 3.4 API 스펙

#### GET /admin/monitoring
**응답 (200 OK)**:
```html
<div>
  <h2>Celery Statistics</h2>
  <dl>
    <dt>Total Failed</dt>
    <dd>15</dd>
    <dt>Active Tasks</dt>
    <dd>3</dd>
    <dt>Reserved Tasks</dt>
    <dd>8</dd>
  </dl>
  <table>
    <tr><th>Task</th><th>Entity</th><th>Error</th><th>Action</th></tr>
    <!-- 실패 목록 -->
  </table>
</div>
```

#### POST /admin/monitoring/failed/{failed_task_id}/retry
**응답 (200 OK)**:
```json
{
  "message": "Task queued for retry"
}
```

#### DELETE /admin/monitoring/failed/{failed_task_id}
**응답 (200 OK)**:
```json
{
  "message": "Deleted"
}
```

---

### 3.5 구현 체크리스트

- [ ] FailedTask 모델 정의
- [ ] TaskStatus enum 정의
- [ ] app/db/database.py에 테이블 생성 마이그레이션
- [ ] index_spec_task에 실패 로깅 로직 추가
- [ ] celery_monitoring.py 구현
- [ ] admin_monitoring.py 라우터 구현
- [ ] GET /health/rag 확장
- [ ] monitoring.html 템플릿 작성
- [ ] 재시도 로직 테스트

---

### 3.6 테스트 시나리오

#### 정상 케이스
1. 스펙 인덱싱 성공 → DB에 실패 기록 없음
2. 스펙 인덱싱 실패 → FailedTask 생성, 상태=FAILED
3. 재시도 버튼 클릭 → 태스크 재큐, 상태=RETRYING
4. 대시보드에서 실패 목록 조회 → 페이지네이션

#### 엣지 케이스
1. 최대 재시도 초과
   - 예상: 상태=FAILED, retry_count >= max_retries
2. Celery 브로커 다운
   - 예상: /health/rag에서 celery.ok=false
3. FailedTask 수동 삭제
   - 예상: 레코드 제거, 대시보드에서 사라짐

#### 실패 케이스
1. 존재하지 않는 failed_task_id로 재시도
   - 예상: 404

---

### 3.7 위험 및 완화 전략

| 위험 | 완화 방법 |
|------|----------|
| Traceback 저장 시 DB 크기 증가 | TEXT 컬럼 제한 (일정 자 수 초과 시 truncate) |
| 실패 레코드 정리 안 함 → DB 폭증 | 일정 기간(예: 30일) 경과 후 자동 정리 |
| 재시도가 무한 루프 | max_retries로 제한, 성공 시 resolved_at 설정 |
| Redis 연결 문제 시 Celery 사용 불가 | 동기 인덱싱으로 폴백 (기존 기능) |

---

---

## 종합 우선순위 및 구현 순서

**순서**:
1. **Celery 모니터링** (DB 스키마만 추가, 기존 코드 최소 수정)
2. **CodeNode 자동 파서** (새로운 기능, 기존 코드와 독립적)
3. **admin.py 모듈 분리** (리팩터, 가장 신중하게)

**병렬 작업**: 파일 변경이 겹치지 않으므로 @coder가 3개를 동시 진행 가능.

---

**문서 작성일**: 2026-03-30
**담당자**: @senior (설계), @coder (구현), @tester (검증)
