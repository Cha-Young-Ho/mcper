#!/bin/bash
# .agents/team.sh - 에이전트 팀 tmux 분할 터미널 실행
# 사용: ./.agents/team.sh 또는 ./team (alias 설정 시)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="mcper-team"
AGENTS=(
  "pm:프로젝트 관리자:claude-sonnet-4-6"
  "planner:기획자:claude-sonnet-4-6"
  "senior:시니어 개발자:claude-sonnet-4-6"
  "coder:코드 작업자:claude-haiku-4-5"
  "tester:테스트 코드 작업자:claude-haiku-4-5"
  "infra:인프라 관리자:claude-sonnet-4-6"
  "archivist:데이터 라이브러리언:claude-haiku-4-5"
)

# 기존 세션 확인 및 삭제
if tmux has-session -t $SESSION 2>/dev/null; then
  echo "기존 세션 정리 중..."
  tmux kill-session -t $SESSION
fi

echo "🚀 MCPER 에이전트 팀 터미널 시작..."
echo ""

# 메인 세션 생성 (첫 번째 에이전트용)
agent=${AGENTS[0]%:*}
role=${AGENTS[0]#*:}
role=${role%:*}
model=${AGENTS[0]##*:}

tmux new-session -d -s $SESSION -x 220 -y 55 -c "$SCRIPT_DIR"
tmux set-option -t $SESSION default-shell /bin/zsh

# 첫 번째 창 설정 (@pm)
tmux send-keys -t $SESSION:0 "clear" Enter
sleep 0.1
tmux send-keys -t $SESSION:0 "printf '\\n\\033[1;36m╔════════════════════════════════════════════════════════════════╗\\033[0m\\n'" Enter
tmux send-keys -t $SESSION:0 "printf '\\033[1;36m║\\033[0m %*s \\033[1;36m║\\033[0m\\n' 62 '@pm - 프로젝트 관리자'" Enter
tmux send-keys -t $SESSION:0 "printf '\\033[1;36m║\\033[0m 모델: claude-sonnet-4-6 %-46s \\033[1;36m║\\033[0m\\n' ''" Enter
tmux send-keys -t $SESSION:0 "printf '\\033[1;36m╠════════════════════════════════════════════════════════════════╣\\033[0m\\n'" Enter
tmux send-keys -t $SESSION:0 "printf '\\033[1;36m║\\033[0m 역할: 프로젝트 타당성 검토, 범위 정의, 절차 결정             \\033[1;36m║\\033[0m\\n'" Enter
tmux send-keys -t $SESSION:0 "printf '\\033[1;36m╚════════════════════════════════════════════════════════════════╝\\033[0m\\n\\n'" Enter
tmux send-keys -t $SESSION:0 "cat .agents/pm.md | head -25" Enter

# 나머지 에이전트 창 생성 (인덱스 1부터 6까지)
for i in {1..6}; do
  agent=${AGENTS[$i]%:*}
  role=${AGENTS[$i]#*:}
  role=${role%:*}
  model=${AGENTS[$i]##*:}

  tmux new-window -t $SESSION -n $agent -c "$SCRIPT_DIR"

  # 각 창 헤더 설정
  tmux send-keys -t $SESSION:$i "clear" Enter
  sleep 0.1

  case $i in
    1)
      header="@planner - 기획자"
      role_desc="역할: 유저 스토리, 수용 기준, QA 시나리오 작성"
      ;;
    2)
      header="@senior - 시니어 개발자"
      role_desc="역할: 아키텍처 설계, API/DB 스펙, 작업 순서"
      ;;
    3)
      header="@coder - 코드 작업자"
      role_desc="역할: 설계 기반 코드 구현 (@tester와 병렬)"
      ;;
    4)
      header="@tester - 테스트 코드 작업자"
      role_desc="역할: 테스트 케이스 작성 (@coder와 협력)"
      ;;
    5)
      header="@infra - 인프라 관리자"
      role_desc="역할: 보안, 성능, 배포 최종 검수"
      ;;
    6)
      header="@archivist - 데이터 라이브러리언"
      role_desc="역할: 대용량 파일 읽기 → 메모 작성"
      ;;
  esac

  tmux send-keys -t $SESSION:$i "printf '\\n\\033[1;33m╔════════════════════════════════════════════════════════════════╗\\033[0m\\n'" Enter
  tmux send-keys -t $SESSION:$i "printf '\\033[1;33m║\\033[0m %*s \\033[1;33m║\\033[0m\\n' 62 '$header'" Enter
  tmux send-keys -t $SESSION:$i "printf '\\033[1;33m║\\033[0m 모델: $model %-$(( 62 - ${#model} ))s \\033[1;33m║\\033[0m\\n' ''" Enter
  tmux send-keys -t $SESSION:$i "printf '\\033[1;33m╠════════════════════════════════════════════════════════════════╣\\033[0m\\n'" Enter
  tmux send-keys -t $SESSION:$i "printf '\\033[1;33m║\\033[0m $role_desc %-$(( 62 - ${#role_desc} ))s \\033[1;33m║\\033[0m\\n'" Enter
  tmux send-keys -t $SESSION:$i "printf '\\033[1;33m╚════════════════════════════════════════════════════════════════╝\\033[0m\\n\\n'" Enter
  tmux send-keys -t $SESSION:$i "cat .agents/$agent.md | head -25" Enter
done

# 세션 사이즈 최적화
tmux select-layout -t $SESSION:0 tiled

echo ""
echo "✅ 에이전트 팀 터미널 준비 완료!"
echo ""
echo "📋 구성:"
for i in "${!AGENTS[@]}"; do
  agent=${AGENTS[$i]%:*}
  role=${AGENTS[$i]#*:}
  role=${role%:*}
  echo "   [$i] @$agent - $role"
done
echo ""
echo "🎮 단축키:"
echo "   Ctrl+B → N : 다음 창"
echo "   Ctrl+B → P : 이전 창"
echo "   Ctrl+B → [0-6] : 특정 창으로 이동"
echo "   Ctrl+B → Z : 현재 창 전체 화면"
echo "   Ctrl+B → D : 세션 분리 (터미널 유지)"
echo ""
echo "ℹ️  팁: 각 창의 에이전트 지침 전체 보려면:"
echo "   cat .agents/@[이름].md"
echo ""

# tmux 세션 시작
tmux attach-session -t $SESSION
