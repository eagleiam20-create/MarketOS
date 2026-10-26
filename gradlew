#!/usr/bin/env sh
# Minimal Gradle bootstrap script for GitHub Actions.
# Downloads the pinned Gradle distribution and runs it without requiring gradle-wrapper.jar.
set -eu
APP_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GRADLE_VERSION="8.9"
GRADLE_HOME="${GRADLE_USER_HOME:-$HOME/.gradle}/marketos-gradle/gradle-${GRADLE_VERSION}"
if [ ! -x "$GRADLE_HOME/bin/gradle" ]; then
  mkdir -p "$(dirname "$GRADLE_HOME")"
  ZIP_PATH="$(dirname "$GRADLE_HOME")/gradle-${GRADLE_VERSION}-bin.zip"
  if [ ! -f "$ZIP_PATH" ]; then
    if command -v curl >/dev/null 2>&1; then
      curl -fL "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -o "$ZIP_PATH"
    else
      wget -O "$ZIP_PATH" "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
    fi
  fi
  unzip -q -o "$ZIP_PATH" -d "$(dirname "$GRADLE_HOME")"
fi
exec "$GRADLE_HOME/bin/gradle" -p "$APP_HOME" "$@"
