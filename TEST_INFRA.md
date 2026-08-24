# E2E Test Infra: Aternos 24/7 Keep-Alive Automation & Web Dashboard

## Test Philosophy
- **Opaque-box & Requirement-driven**: Derived directly from `ORIGINAL_REQUEST.md`. Exercises the application through HTTP REST APIs, SSE/WebSocket streaming, and browser simulation interfaces.
- **Deterministic & Offline-capable**: Executes against a dedicated high-fidelity `MockAternosServer` to enable 100% CI pass rate without live external credentials or internet connectivity dependencies.
- **Multi-Tier Testing Methodology**: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Testing.

## Feature Inventory
| # | Feature | Source (Requirement) | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|----------------------|:------:|:------:|:------:|:------:|
| 1 | Status Bar State Monitoring | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 2 | Countdown Timer Parsing (mm:ss) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 3 | Exact `+1` Button Detection & Click | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 4 | Keep-Alive Monitoring Loop | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 5 | Server Lifecycle Actions (Start/Stop/Confirm) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 6 | REST API Endpoints | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 7 | Real-Time SSE & WebSocket Streaming | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 8 | Web Dashboard UI Rendering & Controls | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 9 | Live Log Console Filtering & Export | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 10 | Session Cookie Persistence & Vaulting | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 11 | Anti-Bot Stealth Evasion | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 12 | Auto-Reconnect & Resilience | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 13 | Mock/Demo Offline Mode | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 14 | Docker Containerization & Healthchecks | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **Runner**: `pytest -v --asyncio-mode=auto tests/`
- **Directories**:
  - `tests/unit/`: Component-level unit tests.
  - `tests/integration/`: API, WebSocket/SSE, and Mock Engine integration tests.
  - `tests/e2e/`: Full multi-tier end-to-end tests:
    - `test_tier1_features.py`: Feature coverage (≥5 tests per feature = ≥70 tests)
    - `test_tier2_boundaries.py`: Boundary and corner cases (≥5 tests per feature = ≥70 tests)
    - `test_tier3_combinations.py`: Cross-feature pairwise interactions (≥15 tests)
    - `test_tier4_scenarios.py`: Real-world application workload scenarios (≥7 complex scenarios)
    - `test_tier5_adversarial.py`: Adversarial edge cases and stress testing

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Server Online Idle Lifecycle with Multi-Hour Keep-Alive | F1, F2, F3, F4, F6, F7, F8, F9 | High |
| 2 | Cold Server Start -> Queue Progression -> Auto Confirm -> Online Keep-Alive | F1, F3, F4, F5, F6, F7 | High |
| 3 | Session Expiry -> Cloudflare Challenge -> Auto-Reconnect Recovery | F1, F4, F10, F11, F12 | High |
| 4 | Web Dashboard Manual Control Under Active Automation | F3, F4, F5, F6, F7, F8 | Medium |
| 5 | Rapid Multiple Client Connections with SSE/WebSocket Log Streaming | F6, F7, F8, F9 | Medium |
| 6 | Emergency 0:05 Countdown Fast-Recovery Trigger | F2, F3, F4, F7, F9 | High |
| 7 | Full Container Boot -> Healthcheck -> Mock Simulation -> Clean Shutdown | F6, F13, F14 | Medium |

## Coverage Thresholds
- **Tier 1**: ≥5 per feature (≥70 tests)
- **Tier 2**: ≥5 per feature (≥70 tests)
- **Tier 3**: ≥15 pairwise interaction tests
- **Tier 4**: ≥7 realistic application scenarios
- **Total Minimum Target**: ~160+ test cases across all tiers
- **Pass Semantics**: 100% test pass rate with exit code 0.
