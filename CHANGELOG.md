# CHANGELOG

<!-- version list -->

## v1.22.0 (2026-01-24)

### Bug Fixes

- Enhance session management and testing configuration
  ([`3ba71e7`](https://github.com/tmonk/mcp-stata/commit/3ba71e76cf2b578c0c9c542b839436f68f5dec85))

- Improve session listener management and error handling
  ([`66df105`](https://github.com/tmonk/mcp-stata/commit/66df105e75bd55d62ae9a75fae36dfbf41e8a9d5))

- Update Python version support to 3.11+ across configuration files. 3.10 is incompatible
  ([`b40244c`](https://github.com/tmonk/mcp-stata/commit/b40244cbad624296c2da94d4e1af3174f7103d1d))

### Features

- Implement session management for Stata integration - fully backwards compatible
  ([`5eeaea2`](https://github.com/tmonk/mcp-stata/commit/5eeaea2f78b034ac0a8545ce7b0e2d8980232b99))

### Testing

- Ensure async tests
  ([`04be0a0`](https://github.com/tmonk/mcp-stata/commit/04be0a02501d409f5130d791b358d6baa37ff631))


## v1.21.0 (2026-01-24)

### Bug Fixes

- Enhance graph command handling and add test for graph ready event emission
  ([`426b48f`](https://github.com/tmonk/mcp-stata/commit/426b48fd9858a7f98e91d0a60d2522cf221a001b))

- Enhance graph signature detection and improve logging in GraphCreationDetector and server
  ([`f01bedb`](https://github.com/tmonk/mcp-stata/commit/f01bedb231796503e4450bb782f4912ea38ecb5f))

- Enhance SMCL log cleaning and add regression tests for output format
  ([`67338fa`](https://github.com/tmonk/mcp-stata/commit/67338faa36a20ca0161713b71afcd66541627f05))

- Enhance SMCL output cleaning by removing additional boilerplate lines
  ([`5d973cc`](https://github.com/tmonk/mcp-stata/commit/5d973cc0ac1b8bfa8ea3b9986c11dd01a6e4ee54))

- Enhance stdout filtering and improve error handling in StataClient
  ([`933979b`](https://github.com/tmonk/mcp-stata/commit/933979bf4caf3c8fc2956b2c9ecb3f79919faae8))

- Ensure logging is fully hardened
  ([`78da711`](https://github.com/tmonk/mcp-stata/commit/78da71128e9acdae94681cb71410124dd8954c9e))

- Ensure logs get passed through
  ([`c2e1989`](https://github.com/tmonk/mcp-stata/commit/c2e1989d2a9dd43e92237011c25257bda7ebd4a7))

- Fix graph emission logic and add regression tests for graph readiness and SMCL log cleaning
  ([`1557422`](https://github.com/tmonk/mcp-stata/commit/15574229028a530b5c2de8dae356d44d49ef2f6e))

- Harden rc handling with isolation across sessions.
  ([`fbb57fe`](https://github.com/tmonk/mcp-stata/commit/fbb57fed2621af2c262d8ffdee5dd2b3b5c84e05))

- Implement graph signature caching and improve inventory retrieval in GraphCreationDetector and
  StataClient
  ([`55314f0`](https://github.com/tmonk/mcp-stata/commit/55314f0c07f8ff55196c95c3412f9f180e4209e6))

- Improve graph detection and error handling in StataClient and GraphCreationDetector
  ([`51e485a`](https://github.com/tmonk/mcp-stata/commit/51e485a302ae4f664805eb13093a96f4e6ca7332))

- Improve graph signature deduplication logic and add performance tests for user journeys
  ([`9871b4b`](https://github.com/tmonk/mcp-stata/commit/9871b4b0fc24538f921d74367e6f81de81ae3257))

- Improve SMCL log handling and enhance graph emission tests
  ([`73866ab`](https://github.com/tmonk/mcp-stata/commit/73866ab1f277c594a53de9b59fe43c82ea14f3cd))

- Optimisation of rc code gets
  ([`eb1ca1d`](https://github.com/tmonk/mcp-stata/commit/eb1ca1d638014c31b4713298ae98520e53c27ca5))

- Refactor signal handling and improve Stata mock setup in tests
  ([`88d563d`](https://github.com/tmonk/mcp-stata/commit/88d563d3e3dcb65db6d6341e3078df5e72980348))

- Refactor temp file creation to work cross-platform
  ([`70ba79c`](https://github.com/tmonk/mcp-stata/commit/70ba79c86c9489ae14b2624a859b54fedc1d8b00))

- Remove base_dir overrides to prevent log pollution in working directory
  ([`7726580`](https://github.com/tmonk/mcp-stata/commit/7726580a34ef86bf94faf83b9c3adcc6db4f79ce))

- Replace os.name checks with is_windows() for improved clarity and consistency
  ([`13b7423`](https://github.com/tmonk/mcp-stata/commit/13b7423ae357f65958237991997306ec8ace836f))

- SMCL handling and improve logging in StataClient
  ([`1c48ac5`](https://github.com/tmonk/mcp-stata/commit/1c48ac53ba350b4917442547626f281e8dcdebfe))

### Features

- Implement persistent logging and performance optimizations
  ([`d7a567a`](https://github.com/tmonk/mcp-stata/commit/d7a567a8e5e70e7f751bf6641addf9915fb6bd65))

### Testing

- Add pytest marker for Stata requirement in isolation tests
  ([`a23c7ad`](https://github.com/tmonk/mcp-stata/commit/a23c7ad9775f222c04028b997468037492469cc3))

- Add pytest marker for Stata requirement in multiple test files
  ([`d40e0b9`](https://github.com/tmonk/mcp-stata/commit/d40e0b922237baa03c492cf021d7b2a9caa2a7ba))

- Add pytest marker for Stata requirement in SMCL clamping test
  ([`0eb8672`](https://github.com/tmonk/mcp-stata/commit/0eb867213c4622150bd23806fbf0fef34b548fea))

- Add unit tests for internal SMCL cleaning and output conversion methods
  ([`9d7a3e4`](https://github.com/tmonk/mcp-stata/commit/9d7a3e4083d7a749b8a8c51646e8d0d99f44d580))

- Ensure 'invisibility'
  ([`1218918`](https://github.com/tmonk/mcp-stata/commit/1218918a844dc05612f85c8843396f11a32b9a25))


## v1.20.0 (2026-01-21)

### Bug Fixes

- Update Python version support to 3.11+ across configuration files. 3.10 is incompatible
  ([`e6026ac`](https://github.com/tmonk/mcp-stata/commit/e6026ac518767b091090047b6824e1ec89ab53f9))

### Features

- Implement session management for Stata integration - fully backwards compatible
  ([`17f4bc9`](https://github.com/tmonk/mcp-stata/commit/17f4bc9801742ebec525b6a0d8a63dd9f9928aed))


## v1.19.1 (2026-01-20)

### Bug Fixes

- Fix graph timestamp retrieval and deduplication logic in GraphCreationDetector
  ([`cdf0b47`](https://github.com/tmonk/mcp-stata/commit/cdf0b47a9a75b7a8c5278eeb3a4807fcd9ddcb78))


## v1.19.0 (2026-01-20)

### Features

- Expand Python versions supported to 3.11+
  ([`38ce3bd`](https://github.com/tmonk/mcp-stata/commit/38ce3bdb2b1bb158fce7e88d826ca398b9db8105))


## v1.18.7 (2026-01-20)


## v1.18.6 (2026-01-20)


## v1.18.5 (2026-01-20)


## v1.18.4 (2026-01-20)

### Bug Fixes

- Update release
  ([`cf745a8`](https://github.com/tmonk/mcp-stata/commit/cf745a86fb6f83efc564b46f35b7d8e8b1578e62))

### Refactoring

- Modified to exactly match python output
  ([`666d66b`](https://github.com/tmonk/mcp-stata/commit/666d66bd4e8674cee2705b0fd191c299e7b49976))

- Smcl_to_markdown and fast_scan_log functions to match Python behaviour, added unit tests.
  ([`5f04b5f`](https://github.com/tmonk/mcp-stata/commit/5f04b5fa7ef8ba70e268a9afc89bd08066b1cd6f))


## v1.18.3 (2026-01-20)


## v1.18.2 (2026-01-20)

### Bug Fixes

- Remove x86
  ([`b643a48`](https://github.com/tmonk/mcp-stata/commit/b643a4859dca5288c897758a958138176bca611d))


## v1.18.1 (2026-01-20)

### Bug Fixes

- Expand target architecture support in CI and update dependencies for compatibility
  ([`a09495a`](https://github.com/tmonk/mcp-stata/commit/a09495ae0e43ccebd57e4ea84d8cd7968a876392))

- Remove unnecessary features from numpy dependency
  ([`c81a45c`](https://github.com/tmonk/mcp-stata/commit/c81a45cffd82f4b4f8f4f2dbcb92f64a6a0edaac))


## v1.18.0 (2026-01-20)

### Features

- Refactor native sorting and logging operations, add Rust optimizations for SMCL and filtering
  ([`ea74b42`](https://github.com/tmonk/mcp-stata/commit/ea74b428687bfbad8b5a98fb553fd4942ebf36f1))


## v1.17.1 (2026-01-20)

### Bug Fixes

- Optimize sorting performance with conditional parallelization and add release profile settings
  ([`fc2c408`](https://github.com/tmonk/mcp-stata/commit/fc2c40873dcef021403315de7a3f2f986a5b6441))


## v1.17.0 (2026-01-20)

### Bug Fixes

- Fallback Polars-based sorting
  ([`3cc111d`](https://github.com/tmonk/mcp-stata/commit/3cc111d02950cb689250a403cecf2f498e82b5f5))

### Features

- Add native sorting extension using Rust and PyO3
  ([`0b5a693`](https://github.com/tmonk/mcp-stata/commit/0b5a69365955bc78cd5d95d3999d6d8771f589d4))

- Move to maturin, include in project root
  ([`f1caed9`](https://github.com/tmonk/mcp-stata/commit/f1caed9da2612c1f363deb4f23e7846710653be4))


## v1.16.8 (2026-01-20)

### Features

- Use the Rust native sorter for UI sorting with a Polars fallback, and document the decision.

### Tests

- Add unit coverage for Polars fallback sorting and update Arrow handler expectations.


## v1.16.7 (2026-01-20)

### Bug Fixes

- Update installation commands to use --refresh-package instead of --reinstall-package
  ([`15cd09f`](https://github.com/tmonk/mcp-stata/commit/15cd09f876202c05d4288b05fbc7f8e74b77c400))


## v1.16.6 (2026-01-20)

### Bug Fixes

- Update installation commands in README and run_inspector script to always reinstall latest version
  ([`f6d4417`](https://github.com/tmonk/mcp-stata/commit/f6d4417fae0033e7f6b7afb09c30381657cce45b))


## v1.16.5 (2026-01-20)

### Bug Fixes

- Release patch
  ([`a8b1d09`](https://github.com/tmonk/mcp-stata/commit/a8b1d092f2d7570775887a6b96f73f3c3e5e3772))


## v1.16.4 (2026-01-20)


## v1.16.3 (2026-01-20)

### Bug Fixes

- Improve Stata installation path detection on macOS
  ([`9c72787`](https://github.com/tmonk/mcp-stata/commit/9c72787461f0e38f778ef2bc7e387191eb6facab))


## v1.16.2 (2026-01-19)


## v1.16.1 (2026-01-19)

### Bug Fixes

- Improve graph name handling and add logging for export failures in StataClient
  ([`ffdc8f2`](https://github.com/tmonk/mcp-stata/commit/ffdc8f265e77ac70166178b6ddc78b9b4d4d11af))


## v1.16.0 (2026-01-19)

### Features

- Optimize graph signature detection and enhance command tracking in StataClient
  ([`1f28b8c`](https://github.com/tmonk/mcp-stata/commit/1f28b8c9a13541fcfad76032e820dd5d96070fe9))


## v1.15.0 (2026-01-19)

### Features

- Improve task completion notifications and background graph caching in StataClient
  ([`79b87b1`](https://github.com/tmonk/mcp-stata/commit/79b87b12fd74a5332fcd0dedac6240c0f85de51f))


## v1.14.0 (2026-01-18)

### Features

- Enhance logging and implement background task handling in MCP Stata
  ([`38e07a6`](https://github.com/tmonk/mcp-stata/commit/38e07a6e8b798e8d592c2b87e12ac559f5aca6f6))


## v1.13.0 (2026-01-18)

### Features

- **server**: Add async callback support and improve error handling
  ([`3cd0341`](https://github.com/tmonk/mcp-stata/commit/3cd03413ff642c89c36bd53651601c27666f7152))


## v1.12.2 (2026-01-16)

### Bug Fixes

- **server**: Add graph-ready notifications and streaming improvements
  ([`6968f4f`](https://github.com/tmonk/mcp-stata/commit/6968f4fabfe5fbf413888d3896b4e165f90b7955))


## v1.12.1 (2026-01-15)

### Bug Fixes

- **tools**: Deprecate polling in favor of task_done notifications
  ([`10ea881`](https://github.com/tmonk/mcp-stata/commit/10ea881dd88408d8fca8d5992980b05e508f1f0c))

### Chores

- **release**: Allow manual PyPI publishes
  ([`5c0a4ce`](https://github.com/tmonk/mcp-stata/commit/5c0a4cebb418ed59be56bd50beb95b67282584f1))

- **release**: Trigger PyPI publish
  ([`a57516e`](https://github.com/tmonk/mcp-stata/commit/a57516eac1b1c372376116847f73c13b4a5bb4b8))


## v1.12.0 (2026-01-15)

### Chores

- Sync server.json version
  ([`47990ae`](https://github.com/tmonk/mcp-stata/commit/47990aec66c82b91f364cefa7f93d53347f714e4))

- **release**: Migrate to python-semantic-release
  ([`a90acb6`](https://github.com/tmonk/mcp-stata/commit/a90acb6faca55eb744ba4113f395495dcdba6a80))

### Features

- Implement release workflow and configuration for semantic-release
  ([`8f1c7c6`](https://github.com/tmonk/mcp-stata/commit/8f1c7c618bee0f23379ef03eb9ea31835701436e))

- **release**: Update release workflow to use semantic-release version and add build command
  ([`d48150b`](https://github.com/tmonk/mcp-stata/commit/d48150b8a694181c861c64bb0703993a510c940b))

- **server**: Add logging decorators for MCP tool and resource calls
  ([`c8b7e79`](https://github.com/tmonk/mcp-stata/commit/c8b7e79b141e73b3434835ca7d1083d0a5a46254))


## v1.11.1 (2026-01-15)

### Chores

- Sync server.json version
  ([`0fa1659`](https://github.com/tmonk/mcp-stata/commit/0fa1659bd9bf2eca49651f0faffc715bf6466c51))

### Features

- **tools**: Add task completion notifications and improve background task documentation
  ([`8fcd6a3`](https://github.com/tmonk/mcp-stata/commit/8fcd6a37d65fce895d3ab61d9b4503775a0b1d4f))


## v1.11.0 (2026-01-15)

### Chores

- Sync server.json version
  ([`5904a85`](https://github.com/tmonk/mcp-stata/commit/5904a853f074319ffd950fb844d9a9598206d60a))

### Features

- **tools**: Add background task execution for long-running Stata commands and do-files
  ([`8ccf440`](https://github.com/tmonk/mcp-stata/commit/8ccf440df548e31c0724d82928067d38f8d47c8a))


## v1.10.0 (2026-01-15)

### Chores

- Sync server.json version
  ([`10e1ad0`](https://github.com/tmonk/mcp-stata/commit/10e1ad04164573f32d1035c2b28582703c465b65))

### Features

- **tools**: Add `find_in_log` tool for searching log files with context windows
  ([`c69edc9`](https://github.com/tmonk/mcp-stata/commit/c69edc9a495a14da8f9f0c46e2d0491d44cb0595))


## v1.9.1 (2026-01-12)

### Chores

- Sync server.json version
  ([`83780eb`](https://github.com/tmonk/mcp-stata/commit/83780eb3a61f73238663f1633c2dad146ed802d4))

### Refactoring

- **discovery**: Add multi-candidate discovery with version-aware sorting
  ([`3a7a58a`](https://github.com/tmonk/mcp-stata/commit/3a7a58a044b5977b2422643f8ee74a25a9989d4a))


## v1.9.0 (2026-01-06)

### Chores

- Sync server.json version
  ([`79c2a6f`](https://github.com/tmonk/mcp-stata/commit/79c2a6f05bb0b68052177f9f67ac17960cfc9b25))

### Refactoring

- **logging**: Encapsulate logging setup in a dedicated function and enhance error handling during
  Stata initialization
  ([`df8c0ab`](https://github.com/tmonk/mcp-stata/commit/df8c0ab193cf60781df6a06e9c761fa170026099))


## v1.8.2 (2025-12-29)

### Bug Fixes

- **windows**: Resolve file locking and path issues in SMCL handling
  ([`40162b7`](https://github.com/tmonk/mcp-stata/commit/40162b7e208c02b635e776e7593b80068829d485))

### Chores

- Sync server.json version
  ([`8d07403`](https://github.com/tmonk/mcp-stata/commit/8d074032d9a81b41125b999b17d142a7467ab710))

### Refactoring

- Optimize build integration tests using `uv` and session-scoped fixtures and adjust Windows
  discovery test skip logic.
  ([`1aaf904`](https://github.com/tmonk/mcp-stata/commit/1aaf9043b54084aa4d04b95d1f4f6c995833398d))

### Testing

- Add `requires_stata` marker to Linux discovery tests
  ([`6d79cb3`](https://github.com/tmonk/mcp-stata/commit/6d79cb39b4eccd1751ed257251e6133ade68f05f))


## v1.8.1 (2025-12-28)

### Chores

- Sync server.json version
  ([`622bd8e`](https://github.com/tmonk/mcp-stata/commit/622bd8e5efaa04748c1f079974dd71c8a3c003b8))

### Features

- Add end-to-end benchmarking script for Stata MCP HTTP Arrow stream and update .gitignore to
  exclude node_modules
  ([`a90a875`](https://github.com/tmonk/mcp-stata/commit/a90a875265ffd43b26f44f654fc75bb2a82f3837))

- Optimize `get_arrow_stream` with Polars for faster Arrow IPC stream generation and add a
  performance benchmarking script.
  ([`857bbd0`](https://github.com/tmonk/mcp-stata/commit/857bbd006174e1b22c1d35597fc8f0a2fc39aaa7))


## v1.8.0 (2025-12-28)

### Bug Fixes

- Update maxVars limit from 500 to 32,767 in UIChannelManager and test for consistency
  ([`72e67b4`](https://github.com/tmonk/mcp-stata/commit/72e67b4720042ef6494e396154f9d8ccc4f5b4d4))

### Chores

- Sync server.json version
  ([`085b3ea`](https://github.com/tmonk/mcp-stata/commit/085b3ea3dc69f5cc07775c94bb54e7a2f225f9dc))

### Features

- Implement Arrow IPC stream support and update related configurations and tests
  ([`17aacc1`](https://github.com/tmonk/mcp-stata/commit/17aacc165db6787a61cba493fa761019214a97aa))


## v1.7.9 (2025-12-27)

### Bug Fixes

- Update maxVars limit from 200 to 500 in README and UIChannelManager for consistency
  ([`8c36935`](https://github.com/tmonk/mcp-stata/commit/8c3693541e25777aa536454b956ae0fa0bd6b8f1))

### Chores

- Sync server.json version
  ([`b727ff1`](https://github.com/tmonk/mcp-stata/commit/b727ff196f7937a664a7b072262ff49b3ad888b2))


## v1.7.8 (2025-12-27)

### Bug Fixes

- Enhance Stata return code parsing in `stata_client.py` with more robust regex patterns and add
  comprehensive unit tests.
  ([`48251bf`](https://github.com/tmonk/mcp-stata/commit/48251bf57c5609be2fb442e27455657dd49d5937))

### Chores

- Sync server.json version
  ([`4726357`](https://github.com/tmonk/mcp-stata/commit/4726357cd78eb01cac356aac19f45589abcf9f4e))

### Refactoring

- Streamline log monitoring in StataClient by consolidating log streaming functions and ensuring
  accurate path references for SMCL logs, enhancing error handling and progress tracking during
  command execution.
  ([`b9af543`](https://github.com/tmonk/mcp-stata/commit/b9af5436d541f2ae90440a9de92ad91eb5f3bb24))


## v1.7.7 (2025-12-23)

### Chores

- Sync server.json version
  ([`6016aef`](https://github.com/tmonk/mcp-stata/commit/6016aef085f77f975d3c6c6b3b9a935d1c3daba0))

### Features

- Optimize Stata path discovery with fast checks during auto-discovery and targeted retry logic for
  user-provided paths, improve SMCL-based error extraction with named log capture and {err} tag
  parsing, and enhance logging configuration with immediate stderr flushing for MCP transport.
  ([`afa33e1`](https://github.com/tmonk/mcp-stata/commit/afa33e1d9c687c075ca5755db3fe1b45455a0517))

- Remove `_select_stata_error_message` and its tests, and populate `CommandResponse.stderr` with the
  extracted error context.
  ([`baf5a27`](https://github.com/tmonk/mcp-stata/commit/baf5a277733747ca7a24fed0a1b68b452a75e864))


## v1.7.6 (2025-12-23)

### Chores

- Sync server.json version
  ([`66cacdc`](https://github.com/tmonk/mcp-stata/commit/66cacdc9ec468c7f0956eeaac84862e6597fbd4d))


## v1.7.5 (2025-12-23)

### Chores

- Sync server.json version
  ([`ff4e34a`](https://github.com/tmonk/mcp-stata/commit/ff4e34a965de77a4a9d004ef1aeb2e8b84a27469))

### Features

- Improve Stata error message extraction by preserving SMCL tags, capturing multi-line error blocks,
  and providing broader log context.
  ([`1334217`](https://github.com/tmonk/mcp-stata/commit/1334217b3d4021e9b4b78132c3f6bbb9951553b9))


## v1.7.4 (2025-12-23)

### Chores

- Sync server.json version
  ([`e3831c2`](https://github.com/tmonk/mcp-stata/commit/e3831c20074b6e584a76b529eaf9c2d2786f5b4e))

### Features

- Refactor Stata error handling and return code retrieval, improving error message extraction from
  SMCL logs and removing redundant test files.
  ([`3f8ad91`](https://github.com/tmonk/mcp-stata/commit/3f8ad917e52766e65e2b7f7b70fccdb8c8f80bc4))


## v1.7.3 (2025-12-23)

### Chores

- Sync server.json version
  ([`642ec2b`](https://github.com/tmonk/mcp-stata/commit/642ec2b17012800a398c8c864a1578b2ed7de64b))

### Features

- Improve Stata error message parsing by prioritizing specific error keywords and preceding lines,
  adding robust log tail reading, and enhancing fallback messages.
  ([`35b75c6`](https://github.com/tmonk/mcp-stata/commit/35b75c6d5a94045f21f98080971acbd0393e3d2e))


## v1.7.2 (2025-12-22)

### Chores

- Sync server.json version
  ([`b7c8282`](https://github.com/tmonk/mcp-stata/commit/b7c8282ec61febbb2c3d23da12159298453aeb56))

### Features

- Implement robust Stata error message parsing with a new utility method and dedicated unit tests.
  ([`d41fd1a`](https://github.com/tmonk/mcp-stata/commit/d41fd1a53eb65346475198287dce0946488b68b9))


## v1.7.1 (2025-12-22)

### Chores

- Sync server.json version
  ([`00dd9b7`](https://github.com/tmonk/mcp-stata/commit/00dd9b72dcae133ff202e8223f358ac57ce19d3d))


## v1.7.0 (2025-12-22)

### Chores

- Sync server.json version
  ([`0110e5f`](https://github.com/tmonk/mcp-stata/commit/0110e5f95fb89c6992a3d9c14707b3ea390526a8))

### Features

- Add data sorting to `/v1/page` API, update capabilities, and enhance filtered view index
  management.
  ([`9fe23ec`](https://github.com/tmonk/mcp-stata/commit/9fe23ecd13b119d30eb9931c994a2ff36ef508cb))


## v1.6.9 (2025-12-22)

### Chores

- Sync server.json version
  ([`5deb486`](https://github.com/tmonk/mcp-stata/commit/5deb486244b641dafc4d3356f8634cffde07508e))


## v1.6.8 (2025-12-22)

### Chores

- Sync server.json version
  ([`2baf514`](https://github.com/tmonk/mcp-stata/commit/2baf514dcae4af163f0afb3aaa32d4805048c9ce))

### Refactoring

- Enhance request parameter validation in handle_page_request function
  ([`88cffc8`](https://github.com/tmonk/mcp-stata/commit/88cffc837c570ea7149b29511b56a3b308d28def))


## v1.6.7 (2025-12-22)

### Chores

- Sync server.json version
  ([`896bb37`](https://github.com/tmonk/mcp-stata/commit/896bb37e8bd3bf38219b99a9f568bfb80db8fb9d))

### Refactoring

- Consolidate test fixtures to use shared Stata client across test modules
  ([`de1f13d`](https://github.com/tmonk/mcp-stata/commit/de1f13d988719330ca3be99a6faa1e8e12f482e1))

- Enhance test fixtures and improve Stata discovery handling
  ([`9331b34`](https://github.com/tmonk/mcp-stata/commit/9331b34fcd4f047458860afb2d1ccfebdff569b1))

- Implement cached Stata discovery and enhance error handling
  ([`32da1ff`](https://github.com/tmonk/mcp-stata/commit/32da1ffa90fe92e33f31307b73b0546905b2f715))

### Testing

- Add pytestmark for Stata requirement in test files
  ([`ebc2461`](https://github.com/tmonk/mcp-stata/commit/ebc2461a99a5a5d2d6f2d5efbeffd33b216eb799))


## v1.6.6 (2025-12-21)

### Chores

- Sync server.json version
  ([`d4bd605`](https://github.com/tmonk/mcp-stata/commit/d4bd6055bcd433cba8fc5144cdee766203abb155))

### Refactoring

- Enhance Stata path detection and improve error handling in discovery module
  ([`52422a5`](https://github.com/tmonk/mcp-stata/commit/52422a504bacee15f63e2c527b55955a6d2314dc))


## v1.6.5 (2025-12-21)

### Chores

- Sync server.json version
  ([`6da0e5d`](https://github.com/tmonk/mcp-stata/commit/6da0e5d20e3d96cb7318b3d7526e230dae35d77b))


## v1.6.4 (2025-12-21)

### Chores

- Sync server.json version
  ([`4a3e2b6`](https://github.com/tmonk/mcp-stata/commit/4a3e2b6256be4ee1f53ab74680d5518718fc1897))


## v1.6.3 (2025-12-21)

### Chores

- Sync server.json version
  ([`1cd6280`](https://github.com/tmonk/mcp-stata/commit/1cd628030028a5aa43ffcabd6712a2116239725c))


## v1.6.2 (2025-12-21)

### Chores

- Sync server.json version
  ([`d5e33b6`](https://github.com/tmonk/mcp-stata/commit/d5e33b6e3431ba05280e4510abf1a99f092b1de4))


## v1.6.1 (2025-12-21)

### Chores

- Sync server.json version
  ([`0346d26`](https://github.com/tmonk/mcp-stata/commit/0346d266d4a4ef90aa4af913f4e87791c9b5c474))


## v1.6.0 (2025-12-20)

### Bug Fixes

- Update import statements and error handling for Stata dependencies in tests
  ([`d05eae5`](https://github.com/tmonk/mcp-stata/commit/d05eae598f1ce053160af569239da46d9a3e079c))

### Chores

- Sync server.json version
  ([`9a74c5b`](https://github.com/tmonk/mcp-stata/commit/9a74c5b768bffa1b4d1adc54ece8c99d4286a449))

### Refactoring

- Update import statements and mock dependencies in test files
  ([`487bb52`](https://github.com/tmonk/mcp-stata/commit/487bb522902ff431409acb527ff567830078517e))

### Testing

- Mark all tests as requiring Stata in graph integration and streaming cache tests
  ([`8a66e4d`](https://github.com/tmonk/mcp-stata/commit/8a66e4d284a299ff10fa43b5b105cbaa8c9a16c6))


## v1.5.1 (2025-12-19)

### Chores

- Sync server.json version
  ([`04a10bc`](https://github.com/tmonk/mcp-stata/commit/04a10bccdaff83af330055ea7269e205c081d0fc))

### Features

- Add support for cwd in run_command and run_do_file functions
  ([`18b63a9`](https://github.com/tmonk/mcp-stata/commit/18b63a940616acc556ad3085909fbddc3bb61d3b))

- Implement UI HTTP server and enhance streaming
  ([`0e3f71e`](https://github.com/tmonk/mcp-stata/commit/0e3f71e64b188a41b5578156aff0536dd876f0c3))


## v1.5.0 (2025-12-19)

### Chores

- Sync server.json version
  ([`ef4e1ae`](https://github.com/tmonk/mcp-stata/commit/ef4e1aee2a25c66dc74afd7359800c201b667010))

### Features

- Add streaming support for run_command and run_do_file functions
  ([`3c54054`](https://github.com/tmonk/mcp-stata/commit/3c54054665e0081173a251fd7b77ceec350e26e7))


## v1.4.0 (2025-12-17)

### Chores

- Sync server.json version
  ([`f8baf87`](https://github.com/tmonk/mcp-stata/commit/f8baf87c491bcefd50381269ab672db005d82f75))


## v1.4.0-alpha.1 (2025-12-17)

### Chores

- Sync server.json version
  ([`6cbbc15`](https://github.com/tmonk/mcp-stata/commit/6cbbc150ec1ecf7a072a94c5da8bae3e3d4536ec))

- Update Python version requirements and CI configurations to support Python 3.12
  ([`8f63347`](https://github.com/tmonk/mcp-stata/commit/8f63347d6d88809540628fcf5a59703b8b55be90))

### Documentation

- Add badge for test status in README
  ([`52ffca8`](https://github.com/tmonk/mcp-stata/commit/52ffca80750859997933ac0fce08d550acf0ae1a))

### Features

- Add build integration tests and CI workflow for package validation
  ([`4846b2a`](https://github.com/tmonk/mcp-stata/commit/4846b2aac242675516d18ba3c469f4bbb32ce250))

- Mark tests requiring Stata and update CI workflow for improved testing
  ([`589f0b6`](https://github.com/tmonk/mcp-stata/commit/589f0b61f1e821ba27600653d4de6ec163c7dcef))


## v1.4.0 (2025-12-17)

### Chores

- Sync server.json version
  ([`f533238`](https://github.com/tmonk/mcp-stata/commit/f533238a450ffcf8ddbe1760f0ef5b25597076ea))

### Features

- Enhance token efficiency and output handling in Stata commands
  ([`7d7e6fc`](https://github.com/tmonk/mcp-stata/commit/7d7e6fc1d603678280a1c392e94db4ce955649da))


## v1.3.3 (2025-12-17)

### Chores

- Sync server.json version
  ([`5c081d4`](https://github.com/tmonk/mcp-stata/commit/5c081d43f4df7ed28d888137a65204216789323a))


## v1.3.2 (2025-12-15)

### Chores

- Sync server.json version
  ([`638359f`](https://github.com/tmonk/mcp-stata/commit/638359fcf489b0804b5f5a1960e1daeadd2e82f8))


## v1.3.1 (2025-12-15)

### Chores

- Sync server.json version
  ([`5e65337`](https://github.com/tmonk/mcp-stata/commit/5e65337cc56e0ed5598d8af6f6310a91a23fa358))


## v1.3.0 (2025-12-15)

### Chores

- Sync server.json version
  ([`2cdde11`](https://github.com/tmonk/mcp-stata/commit/2cdde11fb0d39ff9ae5890b5ef5021c135cb1e5c))


## v1.2.3 (2025-12-15)

### Chores

- Sync server.json version
  ([`cac6ef3`](https://github.com/tmonk/mcp-stata/commit/cac6ef39c3d17fec4de368e86ecdb38a98726698))


## v1.2.2 (2025-12-15)

### Chores

- Sync server.json version
  ([`7b12d80`](https://github.com/tmonk/mcp-stata/commit/7b12d800ea21feaa42674c30dcf027662eab0bea))

### Features

- Enhance Stata path detection for Linux and add corresponding tests
  ([`3ef3d85`](https://github.com/tmonk/mcp-stata/commit/3ef3d85cd3be91dfb4e81e56cafcafa793cd1679))


## v1.2.1 (2025-12-14)

### Chores

- Update server.json version to 1.2.0 and enhance version sync workflow for better branch handling
  ([`899f106`](https://github.com/tmonk/mcp-stata/commit/899f1065f5b0f7de4be0c2917169f15171d37d38))

### Refactoring

- Change get_variable_list to a tool and add resource wrapper for variable list
  ([`5f640c6`](https://github.com/tmonk/mcp-stata/commit/5f640c6d9fafe81ee97b868605d9f9f7b1908498))


## v1.2.0 (2025-12-14)


## v1.1.0 (2025-12-12)

### Chores

- Sync server.json version
  ([`f8ef75f`](https://github.com/tmonk/mcp-stata/commit/f8ef75f93ee89ed2dc281701b280a11a7b739e3c))


## v1.0.4 (2025-12-12)


## v1.0.3 (2025-12-12)


## v1.0.2 (2025-12-12)


## v1.0.1 (2025-12-12)


## v1.0.0 (2025-12-12)

- Initial Release
