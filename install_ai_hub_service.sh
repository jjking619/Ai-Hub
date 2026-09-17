#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="ai-hub.service"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${REPO_ROOT}/systemd/${SERVICE_NAME}"
USER_SYSTEMD_DIR="${HOME}/.config/systemd/user"
SERVICE_DST="${USER_SYSTEMD_DIR}/${SERVICE_NAME}"

usage() {
  cat <<'EOF'
用法:
  ./install_ai_hub_service.sh install   # 安装/更新 service，启用并重启
  ./install_ai_hub_service.sh uninstall # 停止并卸载 service
  ./install_ai_hub_service.sh status    # 查看 service 状态

说明:
  - 请先将 service 模板放到: systemd/ai-hub.service
  - 脚本只操作当前用户的 systemd (--user)，不需要 sudo
EOF
}

ensure_source_exists() {
  if [[ ! -f "${SERVICE_SRC}" ]]; then
    echo "错误: 未找到 service 模板: ${SERVICE_SRC}" >&2
    echo "请先创建该文件，再执行安装。" >&2
    exit 1
  fi
}

install_service() {
  ensure_source_exists
  mkdir -p "${USER_SYSTEMD_DIR}"
  cp "${SERVICE_SRC}" "${SERVICE_DST}"

  systemctl --user daemon-reload
  systemctl --user enable "${SERVICE_NAME}"
  systemctl --user restart "${SERVICE_NAME}"

  echo "安装完成: ${SERVICE_DST}"
  systemctl --user status "${SERVICE_NAME}" --no-pager -l || true
}

uninstall_service() {
  systemctl --user stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
  systemctl --user disable "${SERVICE_NAME}" >/dev/null 2>&1 || true

  if [[ -f "${SERVICE_DST}" ]]; then
    rm -f "${SERVICE_DST}"
  fi

  systemctl --user daemon-reload
  systemctl --user reset-failed "${SERVICE_NAME}" >/dev/null 2>&1 || true

  echo "已卸载: ${SERVICE_NAME}"
}

status_service() {
  systemctl --user status "${SERVICE_NAME}" --no-pager -l || true
  echo
  systemctl --user is-enabled "${SERVICE_NAME}" 2>/dev/null || echo "disabled"
}

main() {
  local cmd="${1:-install}"
  case "${cmd}" in
    install)
      install_service
      ;;
    uninstall)
      uninstall_service
      ;;
    status)
      status_service
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "未知命令: ${cmd}" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"