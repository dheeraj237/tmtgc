# tmtgc

Random intros from the [Soft Skills Engineering](https://softskills.audio) podcast, plus some humorous ones.

> It takes more than great code to be a great engineer.

Real podcast intros, hand-written jokes, and AI-generated riffs. All in one place.

## Quick Start

```bash
# Install
curl -sL https://raw.githubusercontent.com/dheeraj237/tmtgc/main/install.sh | bash

# Run
tmtgc              # random intro (default: real + generated mix)
tmtgc -o           # podcast episodes only
tmtgc -g           # jokes only
tmtgc --help       # see all options
```

## Setup

The installer asks if you want to add a `tmtgc` alias to your shell — just press Enter to say yes. Done.

## Installation

```bash
# One-liner
curl -sL https://raw.githubusercontent.com/dheeraj237/tmtgc/main/install.sh | bash

# Or from a clone
git clone https://github.com/dheeraj237/tmtgc.git
cd tmtgc && bash install.sh
```

Installs to `~/.local/bin/tmtgc`. No sudo needed.

Custom location? Use `PREFIX=/opt/mytools bash install.sh`

## Usage

```bash
tmtgc           # random (real + jokes)
tmtgc -o        # podcast only
tmtgc -g        # jokes only
tmtgc --update  # refresh data from GitHub
```

Want it on startup? The installer asks — just say yes.

## Show it on every new shell

Add to `~/.zshrc` or `~/.bashrc`:

```bash
alias tmtgc="$HOME/.local/bin/tmtgc"
tmtgc
```

## Uninstall

```bash
curl -sL https://raw.githubusercontent.com/dheeraj237/tmtgc/main/uninstall.sh | bash
```

## Data

- `data/tmtgc.txt` — Real podcast intros
- `data/tmtgc-gen.txt` — Jokes and AI variants

Also works with `fortune`:
```bash
fortune ~/.local/share/tmtgc/tmtgc.txt
```

## Developing

### Update intros from podcast

```bash
python3 scripts/build_fortunes.py
```

### Generate new jokes with Ollama

```bash
ollama pull mistral
ollama serve &
python3 scripts/generate_oneliners.py
```

Copy ones you like into `data/tmtgc-gen.txt` (use `%` separator).

Then reinstall: `bash install.sh`

## Troubleshooting

**Command not found?**
```bash
export PATH="$HOME/.local/bin:$PATH"
source ~/.zshrc  # or ~/.bashrc
```

**Missing data files?**
```bash
bash install.sh
```

**Custom data location?**
```bash
export TMTGC_DATA="/path/to/data"
tmtgc
```

## How it works

- Uses AWK reservoir sampling (memory efficient, no temp files)
- Reads from fortune-mod format files
- Bash/Zsh compatible, POSIX AWK
- Falls back between curl/wget

---

## License

Data sourced from the [Soft Skills Engineering](https://softskills.audio) podcast by Jameson Dance and Dave Smith.
