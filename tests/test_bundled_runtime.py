"""Run the app's copied, ad-hoc signed Python, including native extensions.

Checking the source runtime alone missed a build signing regression that
made dyld reject libpython before the engine could start.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    sys.platform != "darwin"
    or shutil.which("codesign") is None
    or not (REPO / "python-runtime/bin/python3.12").exists(),
    reason="Requires macOS and the fetched bundled Python runtime",
)
@pytest.mark.parametrize("signing_allowed", ["YES", "NO"])
def test_app_bundled_python_starts(tmp_path, signing_allowed):
    env = dict(os.environ, SRCROOT=str(REPO / "ZoomNotesApp"),
               BUILT_PRODUCTS_DIR=str(tmp_path), PRODUCT_NAME="Runtime Smoke",
               CODE_SIGNING_ALLOWED=signing_allowed, EXPANDED_CODE_SIGN_IDENTITY="-")
    subprocess.run(["bash", str(REPO / "scripts/copy-python-runtime.sh")],
                   env=env, check=True, capture_output=True, text=True, timeout=60)
    python = tmp_path / "Runtime Smoke.app/Contents/Resources/python-runtime/bin/python3.12"
    result = subprocess.run(
        [str(python), "-I", "-c",
         "import sys, sqlite3, ssl, zlib, ctypes; "
         "assert sys.version_info >= (3, 10); "
         "assert sqlite3.connect(':memory:').execute('select 42').fetchone()[0] == 42; "
         "assert zlib.decompress(zlib.compress(b'ok')) == b'ok'; print('ok')"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    assert result.stdout.strip() == "ok"


def test_signing_failure_stops_runtime_build(tmp_path):
    source = tmp_path / "source"
    runtime = source / "python-runtime"
    (source / "ZoomNotesApp").mkdir(parents=True)
    (runtime / "bin").mkdir(parents=True)
    python = runtime / "bin/python3.12"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    (runtime / "lib").mkdir()
    (runtime / "lib/libpython3.12.dylib").touch()
    tools = tmp_path / "tools"
    tools.mkdir()
    signer = tools / "codesign"
    signer.write_text("#!/bin/sh\necho 'Signing failed' >&2\nexit 23\n")
    signer.chmod(0o755)
    env = dict(os.environ, SRCROOT=str(source / "ZoomNotesApp"),
               BUILT_PRODUCTS_DIR=str(tmp_path / "products"), PRODUCT_NAME="Failure",
               CODE_SIGNING_ALLOWED="YES", EXPANDED_CODE_SIGN_IDENTITY="-",
               PATH=str(tools) + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run(["bash", str(REPO / "scripts/copy-python-runtime.sh")],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 23
    assert "Signing failed" in result.stderr
    assert "copied and signed" not in result.stdout
