# Changelog

## [0.2.0](https://github.com/lhoupert/claude-vault-capture/compare/v0.1.0...v0.2.0) (2026-06-05)


### ⚠ BREAKING CHANGES

* log/index schema bumped to version 2 — path_b, skip_reason_b, tokens_in_b, tokens_out_b, cost_usd_b dropped; session-index loses its path_b column. Inbox/raw/ is no longer written; external triage extensions reading it must tolerate its absence. The 'per-path failure isolation' invariant is removed (only one path remains).

### Features

* **curate:** retry Path A once on null to recover non-deterministic misses ([d346921](https://github.com/lhoupert/claude-vault-capture/commit/d3469218ccaf534c87cb84090827766cd97349e6))


### Documentation

* document Pro/Max subscription mode with a macOS Keychain recipe ([baf99ec](https://github.com/lhoupert/claude-vault-capture/commit/baf99ec1fea67b7be45b7993733aa9324bc46557))
* document subscription mode with a macOS Keychain token recipe ([dc85234](https://github.com/lhoupert/claude-vault-capture/commit/dc8523464435d1a51e9c6116a255d6190aef4ab6))
* **readme:** fix stale Path B references missed in the removal ([806ca0e](https://github.com/lhoupert/claude-vault-capture/commit/806ca0eaf4eb6537eec8fecc8c39672152d407a2))


### Code Refactoring

* retire Path B (Haiku raw baseline) — single-path capture ([4c9cfdc](https://github.com/lhoupert/claude-vault-capture/commit/4c9cfdcb3ee8968ae9bdf220eed3737ea822c693))
