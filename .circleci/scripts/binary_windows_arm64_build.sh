#!/bin/bash
set -eux -o pipefail

source "${BINARY_ENV_FILE:-/c/w/env}"
mkdir -p "$PYTORCH_FINAL_PACKAGE_DIR"

export USE_SCCACHE=1
export SCCACHE_BUCKET=ossci-compiler-cache
export SCCACHE_REGION=us-east-1
export SCCACHE_LOG_LEVEL=debug
export SCCACHE_IGNORE_SERVER_IO_ERROR=1
export AWS_DEFAULT_REGION=us-east-1

echo "Free space on filesystem before build:"
df -h

export NIGHTLIES_PYTORCH_ROOT="$PYTORCH_ROOT"

if [[ "$PACKAGE_TYPE" == 'libtorch' ]]; then
    C:/a/pytorch/pytorch/builder/windows/arm64/build_libtorch.bat
elif [[ "$PACKAGE_TYPE" == 'wheel' ]]; then    
    C:/a/pytorch/pytorch/builder/windows/arm64/build_pytorch.bat
fi

echo "Free space on filesystem after build:"
df -h
