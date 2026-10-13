#!/bin/bash
# Xcode build phase: copy Python and sign its native code consistently.
set -euo pipefail

RUNTIME="$SRCROOT/../python-runtime"
DEST="$BUILT_PRODUCTS_DIR/$PRODUCT_NAME.app/Contents/Resources/python-runtime"

if [ ! -x "$RUNTIME/bin/python3.12" ]; then
    echo "error: Bundled Python not found. Run scripts/fetch-python-runtime.sh first." >&2
    exit 1
fi

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$RUNTIME" "$DEST"

if [ "${CODE_SIGNING_ALLOWED:-YES}" = "NO" ]; then
    echo "Bundled Python copied (code signing disabled)"
    exit 0
fi

IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:--}"
SIGN_ARGS=(--force --sign "$IDENTITY")
if [ "$IDENTITY" = "-" ]; then
    # Ad-hoc signatures have no Team ID. Hardened runtime library validation
    # would reject Python's own dylib, even when both are ad-hoc signed.
    SIGN_ARGS+=(--options 0 --timestamp=none)
else
    SIGN_ARGS+=(--options runtime --timestamp)
fi

while IFS= read -r -d '' binary; do
    codesign "${SIGN_ARGS[@]}" "$binary"
done < <(find "$DEST" -type f \( -name '*.dylib' -o -name '*.so' \) -print0)
codesign "${SIGN_ARGS[@]}" "$DEST/bin/python3.12"
echo "Bundled Python copied and signed"
