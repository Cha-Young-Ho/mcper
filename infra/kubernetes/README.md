# MCPER — Kubernetes 배포 가이드 (사내망)

## 사전 준비

- `kubectl` 설치 및 클러스터 접근 설정
- NGINX Ingress Controller 사내 클러스터에 설치
- Container registry에 `mcper` 이미지 push (`your-registry/mcper:VERSION`)
- 사내 DNS에 `mcper.corp.internal`, `mcper-admin.corp.internal` 등록

## 배포 순서

### 1. 이미지 빌드 및 push

```bash
# 루트에서
docker build -t your-registry/mcper:v1.0.0 .
docker push your-registry/mcper:v1.0.0
```

deployment YAML의 `image: your-registry/mcper:VERSION`을 실제 태그로 교체.

### 2. Namespace 생성

```bash
kubectl apply -f namespace.yaml
```

### 3. ConfigMap 적용

```bash
# 사내 환경에 맞게 configmap.yaml 수정 후
kubectl apply -f configmap.yaml
```

### 4. Secret 생성

**방법 A — env 파일에서 생성 (권장):**
```bash
# secret.yaml.example을 참고해서 .env 파일 작성
kubectl create secret generic mcper-secret \
  --namespace mcper \
  --from-env-file=.env
```

**방법 B — YAML로 직접 (값을 base64 인코딩):**
```bash
cp secret.yaml.example secret.yaml
# secret.yaml 편집 후
kubectl apply -f secret.yaml
rm secret.yaml  # 적용 후 즉시 삭제
```

### 5. 배포 (순서 준수)

```bash
# PostgreSQL + Redis는 별도 사내 인프라 사용 권장 (또는 StatefulSet으로 직접 배포)

# Worker 먼저 (DB 마이그레이션 완료 후)
kubectl apply -f worker-deployment.yaml

# Web Pod (MCP 엔드포인트)
kubectl apply -f web-deployment.yaml

# Admin Pod (어드민 UI, replicas=1 고정)
kubectl apply -f admin-deployment.yaml

# Services
kubectl apply -f service.yaml

# Ingress
kubectl apply -f ingress.yaml

# HPA
kubectl apply -f hpa.yaml
```

### 6. 배포 확인

```bash
kubectl get pods -n mcper
kubectl get svc -n mcper
kubectl get ingress -n mcper
kubectl logs -n mcper deployment/mcper-web -f
```

## 어드민 접근

**사내 DNS 설정 완료 후:**
```
http://mcper-admin.corp.internal/admin
```

**포트포워딩으로 임시 접근:**
```bash
kubectl port-forward -n mcper svc/mcper-admin-svc 8080:80
# http://localhost:8080/admin
```

## 롤링 업데이트

```bash
# 새 이미지 배포
kubectl set image deployment/mcper-web mcper-web=your-registry/mcper:v1.1.0 -n mcper
kubectl set image deployment/mcper-admin mcper-admin=your-registry/mcper:v1.1.0 -n mcper
kubectl set image deployment/mcper-worker mcper-worker=your-registry/mcper:v1.1.0 -n mcper

# 업데이트 상태 확인
kubectl rollout status deployment/mcper-web -n mcper
```

## 사내망 보안 주의사항

- `ingress.yaml`의 `whitelist-source-range`를 사내 IP 대역으로 설정
- `MCPER_AUTH_ENABLED=true` 유지 (configmap.yaml)
- Secret은 Vault, AWS Secrets Manager, K8s External Secrets Operator 등 외부 시크릿 관리 도구 연동 권장
- DB/Redis는 사내 클러스터 내부에만 노출 (외부 NodePort/LoadBalancer 금지)
