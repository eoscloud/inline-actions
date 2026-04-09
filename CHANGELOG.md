# Changelog

## [1.2.5](https://github.com/eoscloud/inline-actions/compare/v1.2.4...v1.2.5) (2026-04-09)


### Bug Fixes

* replace input references in implicit expression contexts ([#26](https://github.com/eoscloud/inline-actions/issues/26)) ([9f3489c](https://github.com/eoscloud/inline-actions/commit/9f3489c9f5536f509a7c6685b4ccb1b5e36ace93))

## [1.2.4](https://github.com/eoscloud/inline-actions/compare/v1.2.3...v1.2.4) (2026-04-09)


### Bug Fixes

* replace input references inside complex expressions ([#24](https://github.com/eoscloud/inline-actions/issues/24)) ([e189013](https://github.com/eoscloud/inline-actions/commit/e189013852d2aca9582ade30a847bf1f0953a172))

## [1.2.3](https://github.com/eoscloud/inline-actions/compare/v1.2.2...v1.2.3) (2026-04-09)


### Bug Fixes

* parse step output references in complex expressions ([#22](https://github.com/eoscloud/inline-actions/issues/22)) ([5cfe1f6](https://github.com/eoscloud/inline-actions/commit/5cfe1f6706a62ff847997dc93c9614d559158954))

## [1.2.2](https://github.com/eoscloud/inline-actions/compare/v1.2.1...v1.2.2) (2026-03-16)


### Bug Fixes

* also map internal output names in parse_output_mapping ([#17](https://github.com/eoscloud/inline-actions/issues/17)) ([b1dcae0](https://github.com/eoscloud/inline-actions/commit/b1dcae02075c97a3e02c6a8e4778ce046c790497))

## [1.2.1](https://github.com/eoscloud/inline-actions/compare/v1.2.0...v1.2.1) (2026-03-16)


### Bug Fixes

* rewrite job-level outputs to use mangled step IDs ([#15](https://github.com/eoscloud/inline-actions/issues/15)) ([67550b0](https://github.com/eoscloud/inline-actions/commit/67550b0ee4ac85439d209c88bdf489d51e019c0a))

## [1.2.0](https://github.com/eoscloud/inline-actions/compare/v1.1.1...v1.2.0) (2026-03-16)


### Features

* add step ID mangling and output mapping for composite actions ([0474021](https://github.com/eoscloud/inline-actions/commit/0474021bbc253b974f49f8ca7f7133ad2acc792d))
* add step ID mangling and output mapping for composite actions ([7193401](https://github.com/eoscloud/inline-actions/commit/719340154242ee5396a39f0b3d179623332e167c))


### Bug Fixes

* **ci:** add missing issues write permission to release workflow ([b287b5c](https://github.com/eoscloud/inline-actions/commit/b287b5c6ee1e6ed1b0a9b9c3e5fc2a5189d18a18))
* **ci:** add missing issues write permission to release workflow ([cc0632b](https://github.com/eoscloud/inline-actions/commit/cc0632b85a38f9bd8bec4e27c69b92ba45d16223))
* Drop duplicate prefix from release names ([#13](https://github.com/eoscloud/inline-actions/issues/13)) ([e67ba79](https://github.com/eoscloud/inline-actions/commit/e67ba79000dc1fe7c846c4039f2e9865ef37ab1e))


### Testing

* add pytest-based integration test suite ([7ab4d91](https://github.com/eoscloud/inline-actions/commit/7ab4d91aa8bf10d85649ba84d4b10dec6069dd21))
* add unit tests for step ID mangling and output mapping ([f951262](https://github.com/eoscloud/inline-actions/commit/f951262a3f1e40a821bfaaac9c6a27cc679001ac))
* improve coverage for scalar types and list refs in mangling ([73a6002](https://github.com/eoscloud/inline-actions/commit/73a6002c43cff0bf95f97aa8574ef5f2d51ec2ea))

## [1.2.0](https://github.com/eoscloud/inline-actions/compare/inline-actions-v1.1.1...inline-actions-v1.2.0) (2026-03-16)


### Features

* add step ID mangling and output mapping for composite actions ([0474021](https://github.com/eoscloud/inline-actions/commit/0474021bbc253b974f49f8ca7f7133ad2acc792d))
* add step ID mangling and output mapping for composite actions ([7193401](https://github.com/eoscloud/inline-actions/commit/719340154242ee5396a39f0b3d179623332e167c))
* add unit tests with 94% coverage and CI integration ([26ffb2d](https://github.com/eoscloud/inline-actions/commit/26ffb2db2c1c0350d77b4e557658305bebe8d33f))
* switch coverage reporting to codecov.io ([fc16c85](https://github.com/eoscloud/inline-actions/commit/fc16c85ba26381376026a8247c07ef8252054184))
* turn metadata file into a lock file with revision pinning ([a35f2ce](https://github.com/eoscloud/inline-actions/commit/a35f2cea6d40e4b16a68775fe8f6f8a1b1fbcc08))
* turn metadata file into a lock file with revision pinning ([6c779c5](https://github.com/eoscloud/inline-actions/commit/6c779c52a7d5c56cebf0f495cfb53b9206d95ea1))
* vendor remote action sources by default ([7a55624](https://github.com/eoscloud/inline-actions/commit/7a55624cfd35def7ff85c00a3e7f8e145373b684))


### Bug Fixes

* abort when revision cannot be determined for lock file ([6c7371b](https://github.com/eoscloud/inline-actions/commit/6c7371b3bfe0ee1dadb05ac4dc9408b58ffc82ab))
* abort when revision cannot be determined for lock file ([429377e](https://github.com/eoscloud/inline-actions/commit/429377e08882e6113013ec3bcf6b9c07ebe04da1))
* allow empty and missing lock files in --frozen mode ([2aa1e95](https://github.com/eoscloud/inline-actions/commit/2aa1e9504c5174ca61ae17c689d454e3028b5172))
* allow empty and missing lock files in --frozen mode ([d2beb7d](https://github.com/eoscloud/inline-actions/commit/d2beb7d8ab728478c099ba6fdf3ac81865db4a17))
* **ci:** add missing issues write permission to release workflow ([b287b5c](https://github.com/eoscloud/inline-actions/commit/b287b5c6ee1e6ed1b0a9b9c3e5fc2a5189d18a18))
* **ci:** add missing issues write permission to release workflow ([cc0632b](https://github.com/eoscloud/inline-actions/commit/cc0632b85a38f9bd8bec4e27c69b92ba45d16223))
* derive vendoring path from output-dir instead of hardcoding it ([3cdd809](https://github.com/eoscloud/inline-actions/commit/3cdd809be3847d9dd33f61ec405cf8d4dd0e0a9e))
* preserve YAML list indentation from source files ([e54df9b](https://github.com/eoscloud/inline-actions/commit/e54df9bd2ac0f2e13eff5f4eb5055b0a7dbce975))
* replace coverage badge action with we-cli/coverage-badge-action ([021d4cf](https://github.com/eoscloud/inline-actions/commit/021d4cf058f96978e8c99e08e949411be7786ce2))
* set permissions option in pre-commit-autoupdate CI workflow ([d8061ae](https://github.com/eoscloud/inline-actions/commit/d8061aeed93a380bd32a2747cd69efa87bfee975))
* strip trailing whitespace from generated YAML files ([48e1332](https://github.com/eoscloud/inline-actions/commit/48e133258911d328438632e04d7449536cbbcce7))
* use correct version tag for coverage badge action ([d273716](https://github.com/eoscloud/inline-actions/commit/d273716595ef3afb71b2f40cdb69b9f6726e6ae9))


### Documentation

* add getting started guide and use uvx for usage examples ([aed2cd8](https://github.com/eoscloud/inline-actions/commit/aed2cd8ad2aaffd28376411030ced4e23d74ad19))
* add getting started guide and use uvx for usage examples ([540d7bf](https://github.com/eoscloud/inline-actions/commit/540d7bf7152efa7dfec0b7a28c5d6d00ec161c43))


### Testing

* add pytest-based integration test suite ([7ab4d91](https://github.com/eoscloud/inline-actions/commit/7ab4d91aa8bf10d85649ba84d4b10dec6069dd21))
* add unit tests for step ID mangling and output mapping ([f951262](https://github.com/eoscloud/inline-actions/commit/f951262a3f1e40a821bfaaac9c6a27cc679001ac))
* improve coverage for scalar types and list refs in mangling ([73a6002](https://github.com/eoscloud/inline-actions/commit/73a6002c43cff0bf95f97aa8574ef5f2d51ec2ea))
