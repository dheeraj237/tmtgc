#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
DATA_DIR="$PREFIX/share/tmtgc"

echo "Uninstalling tmtgc..."

[[ -f "$BIN_DIR/tmtgc" ]] && rm -f "$BIN_DIR/tmtgc"  && echo "  Removed $BIN_DIR/tmtgc"
[[ -d "$DATA_DIR" ]]      && rm -rf "$DATA_DIR"        && echo "  Removed $DATA_DIR"

# Remove alias from shell profiles
remove_alias_from_file() {
    local file="$1"
    if [[ -f "$file" ]] && grep -q "alias tmtgc=" "$file"; then
        # Remove the alias line and the tmtgc command line if they exist
        grep -v "alias tmtgc=" "$file" | grep -v "^tmtgc$" > "$file.tmp"
        mv "$file.tmp" "$file"
        echo "  Removed alias from $file"
    fi
}

remove_alias_from_file "$HOME/.zshrc"
remove_alias_from_file "$HOME/.bashrc"

echo ""
echo "Done. If you added tmtgc to a custom config file, remove these lines manually:"
echo ""
echo "  alias tmtgc=\"\$HOME/.local/bin/tmtgc\""
echo "  tmtgc"
