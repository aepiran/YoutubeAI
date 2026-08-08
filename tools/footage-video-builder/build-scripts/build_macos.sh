#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.0.0"
INSTALL_DEPENDENCIES=0
SKIP_TESTS=0
CLEAN=0

usage() {
  echo "Usage: $0 [--version 1.0.0] [--install-dependencies] [--skip-tests] [--clean]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="${2:?Missing version}"; shift 2 ;;
    --install-dependencies) INSTALL_DEPENDENCIES=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must run on macOS." >&2
  exit 1
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "Version must look like 1.0.0 or 1.0.0-beta.1." >&2
  exit 2
fi

cd "$PROJECT_DIR"
PYTHON="$PROJECT_DIR/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"
APP_NAME="FootageVideoBuilder"
SPEC_FILE="$PROJECT_DIR/ft-video-builder.spec"
ARCH="$(uname -m)"
BUILD_ROOT="$PROJECT_DIR/build/macos"
DIST_ROOT="$PROJECT_DIR/dist/macos"
RELEASE_ROOT="$PROJECT_DIR/release"
ARCHIVE="$RELEASE_ROOT/$APP_NAME-$VERSION-macos-$ARCH.zip"

for required_path in \
  "$SPEC_FILE" \
  "$PROJECT_DIR/main.py" \
  "$PROJECT_DIR/requirements.txt" \
  "$PROJECT_DIR/assets"; do
  if [[ ! -e "$required_path" ]]; then
    echo "Required build input is missing: $required_path" >&2
    exit 1
  fi
done

if [[ "$CLEAN" -eq 1 ]]; then
  rm -rf "$BUILD_ROOT" "$DIST_ROOT"
fi
mkdir -p "$BUILD_ROOT" "$DIST_ROOT" "$RELEASE_ROOT"

if [[ "$INSTALL_DEPENDENCIES" -eq 1 ]]; then
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
fi
"$PYTHON" -c "import PyInstaller"

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  QT_QPA_PLATFORM=offscreen PYTHONUTF8=1 \
    "$PYTHON" -m unittest discover -s tests -v
fi

PYINSTALLER_ARGS=(
  -m PyInstaller
  --noconfirm --clean
  --distpath "$DIST_ROOT"
  --workpath "$BUILD_ROOT/work"
  "$SPEC_FILE"
)
"$PYTHON" "${PYINSTALLER_ARGS[@]}"

APP_PATH="$DIST_ROOT/$APP_NAME.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "PyInstaller did not create $APP_NAME.app." >&2
  exit 1
fi
rm -f "$ARCHIVE"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ARCHIVE"

echo
echo "Build completed."
echo "Application: $APP_PATH"
echo "Release:     $ARCHIVE"
echo "Note: the app is unsigned; macOS may require local approval on first launch."
