#!/bin/bash
# .agents/team_dashboard.sh - 에이전트 팀 상태 대시보드
# 사용: ./.agents/team_dashboard.sh 또는 watch -n 5 ./.agents/team_dashboard.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[1;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# 에이전트 정의
declare -A AGENTS=(
  [pm]="프로젝트 관리자"
  [planner]="기획자"
  [senior]="시니어 개발자"
  [coder]="코드 작업자"
  [tester]="테스트 코드 작업자"
  [infra]="인프라 관리자"
  [archivist]="데이터 라이브러리언"
)

declare -A MODELS=(
  [pm]="claude-sonnet-4-6"
  [planner]="claude-sonnet-4-6"
  [senior]="claude-sonnet-4-6"
  [coder]="claude-haiku-4-5"
  [tester]="claude-haiku-4-5"
  [infra]="claude-sonnet-4-6"
  [archivist]="claude-haiku-4-5"
)

declare -A COLORS=(
  [pm]="$CYAN"
  [planner]="$CYAN"
  [senior]="$CYAN"
  [coder]="$YELLOW"
  [tester]="$YELLOW"
  [infra]="$MAGENTA"
  [archivist]="$GREEN"
)

# 헤더 출력
clear
printf "${CYAN}"
printf '╔═══════════════════════════════════════════════════════════════════════════════════════════════════════╗\n'
printf '║%*s║\n' 113 '  MCPER AGENT TEAMS DASHBOARD'
printf '║%*s║\n' 113 "  $(date '+%Y-%m-%d %H:%M:%S')"
printf '╚═══════════════════════════════════════════════════════════════════════════════════════════════════════╝\n'
printf "${NC}\n"

# 각 에이전트 정보 출력
for agent in pm planner senior coder tester infra archivist; do
  color=${COLORS[$agent]}
  role=${AGENTS[$agent]}
  model=${MODELS[$agent]}

  printf "${color}┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐${NC}\n"
  printf "${color}│${NC} 🤖 ${color}@$agent${NC} - ${role}\n"
  printf "${color}│${NC} 📦 모델: ${model}\n"
  printf "${color}├────────────────────────────────────────────────────────────────────────────────────────────────────────┤${NC}\n"

  # 지침 파일에서 역할/책임 추출
  if [ -f ".agents/$agent.md" ]; then
    printf "${color}│${NC} 📋 지침:\n"
    grep -A 2 "^## 역할" ".agents/$agent.md" | tail -1 | sed "s/^/${color}│${NC}   /" | head -1

    # 핵심 책임 추출 (3줄만)
    printf "${color}│${NC} 📌 핵심 책임:\n"
    grep -A 10 "^## 핵심" ".agents/$agent.md" | grep "^[0-9]\." | head -3 | sed "s/^/${color}│${NC}   /"
  fi

  # 최근 작업 로그 확인
  if grep -q "@$agent" "docs/dev_log.md" 2>/dev/null; then
    printf "${color}│${NC} 📝 최근 작업:\n"
    grep "@$agent" "docs/dev_log.md" | head -2 | sed "s/^/${color}│${NC}   /"
  else
    printf "${color}│${NC} 📝 최근 작업: (없음)\n"
  fi

  # 파일 통계
  file_count=$(ls -1 ".agents/$agent.md" 2>/dev/null | wc -l)
  if [ $file_count -gt 0 ]; then
    line_count=$(wc -l < ".agents/$agent.md")
    printf "${color}│${NC} 📄 지침 파일: $line_count 줄\n"
  fi

  printf "${color}└────────────────────────────────────────────────────────────────────────────────────────────────────────┘${NC}\n"
  printf "\n"
done

# 요약 통계
printf "${BLUE}┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐${NC}\n"
printf "${BLUE}│${NC} 📊 팀 통계\n"
printf "${BLUE}├────────────────────────────────────────────────────────────────────────────────────────────────────────┤${NC}\n"

# 전체 지침 파일 라인 수
total_lines=0
for agent in pm planner senior coder tester infra archivist; do
  if [ -f ".agents/$agent.md" ]; then
    lines=$(wc -l < ".agents/$agent.md")
    total_lines=$((total_lines + lines))
  fi
done
printf "${BLUE}│${NC} 📝 전체 지침 라인 수: $total_lines줄\n"

# dev_log 작업 수
if [ -f "docs/dev_log.md" ]; then
  work_count=$(grep -c "^##" "docs/dev_log.md" 2>/dev/null || echo "0")
  printf "${BLUE}│${NC} ✅ 완료된 작업: $work_count개\n"
fi

# 기록관 메모 수
if [ -d ".claude/archivist_notes" ]; then
  memo_count=$(ls -1 ".claude/archivist_notes"/*.md 2>/dev/null | wc -l)
  printf "${BLUE}│${NC} 📚 기록관 메모: $memo_count개\n"
fi

# 프로젝트 평가 파일
if [ -f "docs/project_assessment.md" ]; then
  printf "${BLUE}│${NC} 📋 프로젝트 평가: ✅ 완료 ($(wc -l < docs/project_assessment.md)줄)\n"
fi

printf "${BLUE}└────────────────────────────────────────────────────────────────────────────────────────────────────────┘${NC}\n"
printf "\n"

# 빠른 명령어
printf "${GREEN}🔧 빠른 명령어:${NC}\n"
printf "${GREEN}  ./.agents/team.sh${NC}                    # tmux 분할 터미널 시작\n"
printf "${GREEN}  watch -n 5 ./.agents/team_dashboard.sh${NC} # 대시보드 자동 갱신 (5초)\n"
printf "${GREEN}  cat .agents/@[이름].md${NC}               # 에이전트 지침 전체 보기\n"
printf "${GREEN}  cat docs/dev_log.md${NC}                  # 작업 로그 보기\n"
printf "${GREEN}  cat docs/project_assessment.md${NC}        # 프로젝트 평가 보기\n"
printf "\n"
