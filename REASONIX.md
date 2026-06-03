# DeepTutor Project

## Stack
- **Python 3.11+** — core language
- **DeepTutor** — teaching engine with multi-agent collaboration + RAG
- **FastAPI + Uvicorn** — API layer (platform API on 3782)
- **Hermes Agent** — WeChat iLink dual-gateway message router
- **Docker Compose** — multi-container deployment (hermes_agent, deeptutor, rkllama, chromadb, pocketbase)
- **Ruff** — linter + formatter (replaces isort + flake8 + black)
- **pytest + pytest-asyncio** — test runner

## Layout
| Dir | Role |
|-----|------|
| `vendor/deeptutor/` | Teaching engine core (HKUDS upstream) — do not edit |
| `vendor/hermes-agent/` | WeChat iLink dual-gateway — do not edit |
| `tutor_platform/` | Project-owned platform code (providers, RAG, sessions, storage) |
| `domains/` | Subject curriculum logic (chemistry, math, physics) |
| `web/` | Next.js frontend (DT Web UI on port 3782) |
| `docker/` + `docker-compose*.yml` | Container configs (dev, prod, ghcr) |
| `config/` | YAML configs for domains, hermes gateways, intent rules |
| `patches/` | Git patch files tracking vendor modifications |
| `tests/` | pytest suites (agents/, api/, core/, knowledge/, capabilities/) |
| `scripts/` | Utility scripts |
| `requirements/` | Layered pip requirements (tutorbot, matrix, dev, math-animator) |

## Commands
| Purpose | Command |
|---------|---------|
| Dev environment | `make dev` (4 containers) |
| Production | `make prod` |
| Stop containers | `make down` |
| Run tests | `make test` → `python -m pytest tests/ -x -q` |
| Tests verbose | `make test-v` → `python -m pytest tests/ -x -v` |
| Lint all | `make lint` → `pre-commit run --all-files` |
| Lint Python | `make lint-ruff` → `ruff check --fix .` |
| Format Python | `make lint-ruff-format` → `ruff format .` |
| Setup hooks | `make setup` → `pip install pre-commit && pre-commit install` |
| Clean caches | `make clean` |
| Install (source) | `pip install -e ".[dev]"` |
| Container shell | `make shell` → `docker exec -it deeptutor bash` |

## Conventions
- **Line length**: 100 (Black + Ruff)
- **Quote style**: double quotes (Ruff)
- **Import sorting**: isort via Ruff, known first-party: `deeptutor`, `deeptutor_cli`, `scripts`
- **Pre-commit**: ruff fix + format, prettier (web/), bandit, mypy, detect-secrets
- **pytest**: async tests via `pytest-asyncio`, strict markers (`--strict-markers`)

## Watch out for
- **`vendor/` dirs are read-only.** Modify via external config or tracked patches. Never change function signatures.
- **Patches are the upgrade path.** Reapply with `git apply patches/*.patch` after upstream pull.
- **CLAUDE.md is authoritative** — vendor permissions, branch strategy, test rules live there.
- **Containerized deployment.** Local dev without Docker needs chromadb, rkllama, pocketbase; use `make dev`.
- **pyproject.toml is the dependency source of truth**; `requirements/` mirrors subsets for Docker/CI.
