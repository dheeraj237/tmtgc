#!/usr/bin/env bash
set -euo pipefail

REPO_USER="dheeraj237"
REPO_NAME="tmtgc"
BRANCH="main"
RAW_BASE="https://raw.githubusercontent.com/${REPO_USER}/${REPO_NAME}/${BRANCH}"

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
DATA_DIR="$PREFIX/share/tmtgc"

info()    { echo "  [install] $*"; }
success() { echo "  [✓] $*"; }
error()   { echo "  [✗] $*" >&2; exit 1; }

need_cmd() { command -v "$1" &>/dev/null || error "Required command not found: $1"; }

download() {
    local url="$1" dest="$2"
    if command -v curl &>/dev/null; then
        curl -fsSL "$url" -o "$dest"
    elif command -v wget &>/dev/null; then
        wget -qO "$dest" "$url"
    else
        error "Neither curl nor wget found. Install one and retry."
    fi
}

# Detect if running from a cloned repo or via curl | bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-install.sh}")" 2>/dev/null && pwd || echo "")"
LOCAL_DATA=""
if [[ -n "$SCRIPT_DIR" && -d "$SCRIPT_DIR/data" ]]; then
    LOCAL_DATA="$SCRIPT_DIR/data"
    LOCAL_BIN="$SCRIPT_DIR/bin/tmtgc"
fi

echo ""
echo "Installing tmtgc → $PREFIX"
echo ""

need_cmd awk

mkdir -p "$DATA_DIR" "$BIN_DIR"

if [[ -n "$LOCAL_DATA" ]]; then
    info "Copying data files from local repo..."
    cp "$LOCAL_DATA/tmtgc.txt"    "$DATA_DIR/"
    cp "$LOCAL_DATA/tmtgc-gen.txt" "$DATA_DIR/"
    cp "$LOCAL_BIN" "$BIN_DIR/tmtgc"
else
    info "Downloading data files..."
    tmpdir="$(mktemp -d)"
    download "${RAW_BASE}/data/tmtgc.txt"    "$tmpdir/tmtgc.txt"
    download "${RAW_BASE}/data/tmtgc-gen.txt" "$tmpdir/tmtgc-gen.txt"
    download "${RAW_BASE}/bin/tmtgc"               "$tmpdir/tmtgc"
    cp "$tmpdir/tmtgc.txt"    "$DATA_DIR/"
    cp "$tmpdir/tmtgc-gen.txt" "$DATA_DIR/"
    cp "$tmpdir/tmtgc"              "$BIN_DIR/tmtgc"
    rm -rf "$tmpdir"
fi

chmod +x "$BIN_DIR/tmtgc"

echo ""
success "tmtgc installed to $BIN_DIR/tmtgc"
success "Data files in $DATA_DIR/"
echo ""
echo "  Try it:  tmtgc"
echo "           tmtgc --gen"
echo "           tmtgc --all"
echo ""

# Detect shell profile
SHELL_PROFILE="$HOME/.zshrc"
[[ "$SHELL" == */bash ]] && SHELL_PROFILE="$HOME/.bashrc"

# Remind user to add bin to PATH if needed
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
    echo "  Add $BIN_DIR to your PATH:"
    echo ""
    echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> $SHELL_PROFILE"
    echo "    source $SHELL_PROFILE"
    echo ""
fi

# Offer to add alias to shell profile
echo ""
read -p "Add 'tmtgc' alias to $SHELL_PROFILE? (Y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]?$ ]]; then
    ALIAS_LINE="alias tmtgc=\"\$HOME/.local/bin/tmtgc\""

    # Check if alias already exists
    if grep -q "alias tmtgc=" "$SHELL_PROFILE" 2>/dev/null; then
        info "tmtgc alias already exists in $SHELL_PROFILE"
    else
        # Ensure file ends with newline before appending
        [[ -n $(tail -c 1 "$SHELL_PROFILE") ]] && echo "" >> "$SHELL_PROFILE"
        echo "$ALIAS_LINE" >> "$SHELL_PROFILE"
        success "Added tmtgc alias to $SHELL_PROFILE"
        echo ""
        echo "  Reload your shell or run: source $SHELL_PROFILE"
        echo ""
    fi
fi
