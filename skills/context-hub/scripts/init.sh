#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_NAME=""
PROJECT_ID=""
PROJECT_SUMMARY="项目全局上下文入口"
GITLAB_URL=""
ONES_URL=""
FIGMA_URL=""
OUTPUT_DIR=""
FORCE_FLAG=""
REPOS=()
TEST_SOURCES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) PROJECT_NAME="$2"; shift 2 ;;
    --id) PROJECT_ID="$2"; shift 2 ;;
    --summary) PROJECT_SUMMARY="$2"; shift 2 ;;
    --gitlab) GITLAB_URL="$2"; shift 2 ;;
    --ones) ONES_URL="$2"; shift 2 ;;
    --figma) FIGMA_URL="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    --repo) REPOS+=("$2"); shift 2 ;;
    --test|--test-source) TEST_SOURCES+=("$2"); shift 2 ;;
    --force) FORCE_FLAG="--force"; shift ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT_NAME" ]]; then
  read -r -p "项目名称: " PROJECT_NAME
fi

if [[ -z "$PROJECT_ID" ]]; then
  read -r -p "项目 ID（英文 slug）: " PROJECT_ID
fi

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$(pwd)/${PROJECT_ID}"
fi

CMD=(
  python3
  "$SCRIPT_DIR/init_context_hub.py"
  --output "$OUTPUT_DIR"
  --name "$PROJECT_NAME"
  --id "$PROJECT_ID"
  --summary "$PROJECT_SUMMARY"
)

if [[ -n "$GITLAB_URL" ]]; then
  CMD+=(--gitlab "$GITLAB_URL")
fi

if [[ -n "$ONES_URL" ]]; then
  CMD+=(--ones "$ONES_URL")
fi

if [[ -n "$FIGMA_URL" ]]; then
  CMD+=(--figma "$FIGMA_URL")
fi

if [[ ${#REPOS[@]} -gt 0 ]]; then
  for repo in "${REPOS[@]}"; do
    CMD+=(--repo "$repo")
  done
fi

if [[ ${#TEST_SOURCES[@]} -gt 0 ]]; then
  for test_source in "${TEST_SOURCES[@]}"; do
    CMD+=(--test-source "$test_source")
  done
fi

if [[ -n "$FORCE_FLAG" ]]; then
  CMD+=("$FORCE_FLAG")
fi

"${CMD[@]}"
