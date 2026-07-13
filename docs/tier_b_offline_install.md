# Tier B: offline install (self-extracting executable)

For machines with no internet access at install time -- shared lab servers behind a
firewall, air-gapped compute, or just avoiding a repeat multi-GB download per machine.
Unlike [Tier A](../README.md#one-time-setup) (`./install.sh`, which needs network to
solve and fetch packages), Tier B ships one self-extracting shell script per platform
with the entire environment already inside it. The end machine needs no `pixi`, no
`conda`, and no network to extract and run it.

## Building a pack

Requires [`pixi`](https://pixi.sh) and `pixi-pack` (`pixi global install pixi-pack`) on
the *building* machine -- not the machine that will run BoltzMaker. Packs can be
cross-built: you don't need a Linux machine to produce the `linux-64` pack.

```bash
pixi-pack --platform osx-arm64 --ignore-pypi-non-wheel --create-executable \
    -o dist/boltzmaker-installer-osx-arm64.sh

pixi-pack --platform linux-64 --ignore-pypi-non-wheel --create-executable \
    -o dist/boltzmaker-installer-linux-64.sh
```

Each pack is the whole conda+PyPI dependency tree (PyTorch, RDKit, OpenBabel, PyMOL,
...) as prebuilt binaries, not source -- `osx-arm64` built at ~618 MiB, `linux-64` at
~4.1 GiB (CUDA-enabled `torch` bundles its own CUDA/cuDNN runtime libraries, which the
macOS MPS build doesn't need since it uses the OS's native Metal framework instead).

## Installing from a pack

```bash
./boltzmaker-installer-osx-arm64.sh -o ./boltzmaker-env
source ./boltzmaker-env/activate.sh
export KMP_DUPLICATE_LIB_OK=TRUE   # see caveat below
python3 BoltzMaker.py preflight my_campaign.md
```

Copy `BoltzMaker.py` itself (plus `vendor/` and `sse_comparison/` if you need
`compare-sse`) alongside the extracted `boltzmaker-env/` directory -- the pack contains
the *environment*, not BoltzMaker's own source.

## Known caveats (all confirmed empirically against a real extracted pack, not assumed)

### `KMP_DUPLICATE_LIB_OK=TRUE` needed on macOS

`pixi.toml`'s `[activation.env]` sets this automatically for `pixi run`/`pixi shell`
(Tier A), but a pack's plain `source activate.sh` doesn't carry pixi's own activation
hooks -- export it yourself, as shown above, or every import will abort with `OMP:
Error #15: Initializing libomp.dylib, but found libomp.dylib already initialized`
(conda-forge's own libomp and PyPI's torch wheel's bundled libomp colliding -- a known,
common conda+pip-PyTorch interaction on macOS, not specific to BoltzMaker). Verified the
actual computation (a real MPS matmul) still produces a correct result with this set.

### `fairscale` needs one more `pip install` after unpacking

`pixi-pack --ignore-pypi-non-wheel` silently drops any PyPI package that's sdist-only
(no prebuilt wheel) -- confirmed by finding three of these the hard way (`ihm`,
`modelcif`, `antlr4-python3-runtime`), each of which crashed the packed `boltz` CLI with
a `ModuleNotFoundError` on **any** invocation. All three now ship via conda-forge
instead (see `pixi.toml`'s `[dependencies]` comments), so they're not a problem anymore.

`fairscale==0.4.13` (also boltz-pinned, also sdist-only on PyPI) is the one exception
left unresolved by design: conda-forge's own `fairscale` build hard-requires conda's own
`pytorch>=2.1,<2.2`, which conflicts with boltz's pip-managed `torch>=2.2` (the MPS/
CUDA-capable build this whole environment is built around) -- using it would mean two
incompatible torch installs in one environment. Fix, after extracting the pack (needs
network once, but *not* a compiler -- it turned out to build as a pure-Python wheel,
confirmed directly):

```bash
python3 -m pip install fairscale==0.4.13
```

`BoltzMaker.py preflight`'s `boltz_cli` check will FAIL with
`ModuleNotFoundError: No module named 'fairscale'` (surfaced via boltz's own `--help`
failing) until this is done.

### PLIP is not in the pack at all -- same as Tier A

Exactly like Tier A's `postinstall` task, `plip`/`pdb-tools`/OpenBabel's Python bindings
aren't part of the conda-then-pypi solve pixi-pack exports (see `pixi.toml`'s own
comment on why: plip's PyPI metadata requires `openbabel>=3.1.1` as a normal
dependency, and uv's two-stage solver kept trying to build a broken from-source
OpenBabel sdist even with `no-build-isolation` and an explicit `conda-pypi-map` entry,
both tried). After extracting the pack:

```bash
python3 -m pip install --no-build-isolation plip pdb-tools
```

`BoltzMaker.py preflight`'s `plip_env` check always PASSes (PLIP is optional and
additive, never blocks a run) but will tell you this exact command if it's missing --
`BoltzMaker.py` detects there's no `pixi` CLI at all in an extracted-pack environment
and prints the raw `pip` command directly, rather than pointing at `pixi run
postinstall` (which wouldn't exist here).

### Boltz-2's own model weights are never bundled

Boltz downloads several GB of model weights (plus the CCD cache) into `~/.boltz` on the
**first** `boltz predict` call, regardless of Tier A or Tier B -- bundling them would add
several more GB on top of the pack sizes above for something that's the same across
every BoltzMaker install anyway. A real air-gapped machine needs that weights cache
transferred in separately (e.g. `rsync`/copy an already-populated `~/.boltz` from a
machine that has run a prediction once with network access). There's no BoltzMaker
command for this yet -- see the README's To-Do list.

## Testing a pack

Before distributing a pack, verify it actually works end-to-end by extracting it
somewhere with the machine's normal `.venv`/`.plip_env`/`pixi`/`PATH` state hidden from
it (a fresh temp directory, nothing else on `PATH` pointing at Python) -- this is the
only way to catch a silently-dropped dependency (like `ihm`/`modelcif`/`antlr4` were)
rather than accidentally testing against your own dev machine's already-complete
environment:

```bash
./boltzmaker-installer-<platform>.sh -o /tmp/pack_test/env
cd /tmp/pack_test
cp /path/to/BoltzMaker.py .
source env/activate.sh
export KMP_DUPLICATE_LIB_OK=TRUE
python3 -c "import boltz.main"   # should succeed with no ModuleNotFoundError
python3 BoltzMaker.py preflight <some boltz_input.md>
```
