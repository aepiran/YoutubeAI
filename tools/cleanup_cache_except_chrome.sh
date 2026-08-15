#!/usr/bin/env zsh
set -euo pipefail

# Cache cleanup for macOS.
# Default mode is dry-run. Use --execute to actually delete.
# Chrome is intentionally excluded.

setopt NULL_GLOB

RUN_MODE="dry-run"
if [[ "${1:-}" == "--execute" ]]; then
  RUN_MODE="execute"
elif [[ "${1:-}" != "" ]]; then
  echo "Usage: $0 [--execute]"
  exit 2
fi

USER_HOME_DIR="${HOME:?}"
USER_CACHE_DIR="$USER_HOME_DIR/Library/Caches"

print_size() {
  local target_path="$1"
  if [[ -e "$target_path" ]]; then
    du -sh "$target_path" 2>/dev/null || true
  fi
}

remove_path() {
  local target_path="$1"

  if [[ ! -e "$target_path" ]]; then
    return 0
  fi

  print_size "$target_path"

  if [[ "$RUN_MODE" == "execute" ]]; then
    rm -rf -- "$target_path"
  fi
}

echo "Mode: $RUN_MODE"
echo "Chrome is excluded: Google Chrome cache/profile folders will not be removed."
echo

if [[ "$RUN_MODE" == "execute" ]]; then
  echo "This will delete selected cache folders now."
  printf "Type DELETE to continue: "
  read -r CONFIRM_DELETE
  if [[ "$CONFIRM_DELETE" != "DELETE" ]]; then
    echo "Cancelled."
    exit 0
  fi
  echo
fi

echo "1) User Library/Caches, excluding Chrome-related folders"
if [[ -d "$USER_CACHE_DIR" ]]; then
  for cache_item in "$USER_CACHE_DIR"/* "$USER_CACHE_DIR"/.[!.]* "$USER_CACHE_DIR"/..?*; do
    [[ -e "$cache_item" ]] || continue

    case "$(basename "$cache_item")" in
      Google|com.google.Chrome|com.google.Keystone|GoogleSoftwareUpdate|Chromium|com.googlecode.iterm2)
        echo "SKIP $(print_size "$cache_item" | tr -s '[:space:]' ' ')"
        ;;
      *)
        remove_path "$cache_item"
        ;;
    esac
  done
fi
echo

echo "2) Xcode and simulator caches"
remove_path "$USER_HOME_DIR/Library/Developer/Xcode/DerivedData"
remove_path "$USER_HOME_DIR/Library/Developer/CoreSimulator/Caches"
echo

echo "3) Package manager caches"
remove_path "$USER_HOME_DIR/Library/Caches/Homebrew"
remove_path "$USER_HOME_DIR/Library/Caches/pip"
remove_path "$USER_HOME_DIR/.npm/_cacache"
echo

if command -v npm >/dev/null 2>&1; then
  echo "4) npm cache verify"
  if [[ "$RUN_MODE" == "execute" ]]; then
    npm cache verify || true
  else
    echo "Would run: npm cache verify"
  fi
  echo
fi

echo "Done."
if [[ "$RUN_MODE" == "dry-run" ]]; then
  echo "Dry-run only. Run with --execute to delete."
fi
