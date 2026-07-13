#!/usr/bin/env bash
# BoltzMaker installer (Tier A) -- installs pixi if needed, then solves and
# installs the unified environment declared in pixi.toml/pixi.lock (boltz,
# rdkit, PLIP/OpenBabel/PyMOL, everything else). Safe to re-run.
#
# Usage: ./install.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

BLUE='\033[38;2;30;115;190m'
GREEN='\033[38;2;0;208;132m'
AMBER='\033[38;2;252;185;0m'
RESET='\033[0m'
BOLD='\033[1m'

info()  { printf "${BLUE}ℹ${RESET} %s\n" "$1"; }
ok()    { printf "${GREEN}✓${RESET} %s\n" "$1"; }
step()  { printf "${BLUE}→${RESET} %s\n" "$1"; }
warn()  { printf "${AMBER}⚠${RESET} %s\n" "$1"; }

printf "\n${BOLD}${BLUE}   ___       ____      __  ___     __${RESET}\n"
printf "${BOLD}${BLUE}  / _ )___  / / /____ /  |/  /__ _/ /_____ ____${RESET}\n"
printf "${BOLD}${BLUE} / _  / _ \\\\/ / __/_ // /|_/ / _ \`/  '_/ -_) __/${RESET}\n"
printf "${BOLD}${BLUE}/____/\\___/_/\\__//__/_/  /_/\\_,_/_/\\_\\\\__/_/${RESET}\n\n"

case "$(uname -s)" in
    Darwin) ;;
    Linux)  ;;
    *)
        warn "unrecognized platform '$(uname -s)' -- BoltzMaker targets macOS (Apple Silicon) and Linux (x86-64/CUDA) only."
        ;;
esac

if ! command -v pixi >/dev/null 2>&1; then
    step "pixi not found -- installing it (https://pixi.sh)"
    curl -fsSL https://pixi.sh/install.sh | sh
    # The installer adds pixi to shell rc files for future sessions; make it available
    # in this one without requiring the user to restart their shell first.
    export PATH="$HOME/.pixi/bin:$PATH"
    if ! command -v pixi >/dev/null 2>&1; then
        warn "pixi installed but not yet on PATH in this shell."
        info "Run: source ~/.zshrc  (or restart your terminal), then re-run ./install.sh"
        exit 1
    fi
else
    ok "pixi already installed ($(pixi --version))"
fi

step "solving and installing the BoltzMaker environment (this pulls PyTorch, RDKit, OpenBabel, PyMOL -- several GB, one-time)"
pixi install

step "installing plip/pdb-tools (kept out of the main solve -- see pixi.toml for why)"
pixi run postinstall

echo
ok "install complete."
info "Next: pixi run preflight <boltz_input.md>"
info "Or open a shell in the environment directly: pixi shell"
echo
info "Boltz-2's own model weights (several GB) download automatically on the first"
info "'pixi run run <boltz_input.md>' -- not bundled by this installer."
