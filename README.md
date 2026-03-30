# C++ Package Registry Util 🔨 <!-- omit in toc -->

A single-file, zero-dependency Python tool for managing custom C++ package registries for both **xmake** and **vcpkg**.

Define your packages in a `registry.json` file, then run `generate` to produce all the registry files idempotently.

---

- [Using a Registry](#using-a-registry)
  - [xmake](#xmake)
  - [vcpkg](#vcpkg)
    - [vcpkg-configuration.json](#vcpkg-configurationjson)
    - [vcpkg.json](#vcpkgjson)
    - [Updating the Baseline](#updating-the-baseline)
- [Managing a Registry](#managing-a-registry)
  - [Getting Started](#getting-started)
  - [Setup](#setup)
  - [registry.json](#registryjson)
  - [Commands](#commands)
    - [Add a package](#add-a-package)
    - [Add a version](#add-a-version)
    - [List packages](#list-packages)
    - [Remove a version](#remove-a-version)
    - [Remove a package](#remove-a-package)
    - [Generate registry files](#generate-registry-files)

---

# Using a Registry

## xmake

Add the registry and install packages in your `xmake.lua`:

```lua
add_repositories("my-registry https://github.com/your-user/your-registry.git")

add_requires("some-library")

target("my-project")
    set_kind("binary")
    add_files("src/*.cpp")
    add_packages("some-library")
```

That's it.

## vcpkg

Custom registries for vcpkg require two configuration files in your project.

### vcpkg-configuration.json

This tells vcpkg where to find packages:

```json
{
    "default-registry": {
        "kind": "git",
        "repository": "https://github.com/microsoft/vcpkg.git",
        "baseline": "<latest-vcpkg-commit-hash>"
    },
    "registries": [
        {
            "kind": "git",
            "repository": "https://github.com/your-user/your-registry.git",
            "baseline": "<latest-registry-commit-hash>",
            "packages": ["some-library", "another-library"]
        }
    ]
}
```

> You must list every package you want to use from the custom registry in the `packages` array.

### vcpkg.json

This is your project manifest where you declare dependencies:

```json
{
    "name": "my-project",
    "version-string": "0.0.1",
    "dependencies": [
        "some-library",
        "another-library"
    ]
}
```

### Updating the Baseline

The `baseline` in `vcpkg-configuration.json` is a git commit hash. vcpkg uses it to determine which versions of packages are available.

**If you update your registry** (add new packages or versions), consumers need to update the baseline to the latest commit hash of your registry to see the changes.

To get the latest baseline for the main vcpkg registry:

```
git ls-remote https://github.com/microsoft/vcpkg.git HEAD
```

To get the latest baseline for your custom registry:

```
git ls-remote https://github.com/your-user/your-registry.git HEAD
```

> This is the most common source of "package not found" errors with vcpkg. When in doubt, update your baselines.

---

# Managing a Registry

## Getting Started

Download [`registry.py`](https://raw.githubusercontent.com/BuildWithCollab/cpp-package-registry-util/main/registry.py) and place it in the root of your registry's git repository. That's the only file you need — zero dependencies, just Python 3.11+.

## Setup

Drop `registry.py` into the root of your registry's git repository. It has zero dependencies — just Python 3.11+.

```
your-registry/
    registry.py
    registry.json
```

## registry.json

This is the source of truth. All commands (except `generate`) just edit this file.

```json
{
  "packages": {
    "some-library": {
      "repo": "your-user/some-library",
      "versions": ["v1.0.0", "v2.0.0"]
    },
    "header-only-lib": {
      "repo": "your-user/header-only-lib",
      "branch": "develop",
      "versions": ["v1.0.0"],
      "header-only": true,
      "registries": ["xmake"]
    }
  }
}
```

| Field | Required | Description |
|---|---|---|
| `repo` | yes | GitHub repository (`user/repo`) |
| `versions` | no | List of version tags |
| `branch` | no | Git branch to track (default: repo default branch) |
| `registries` | no | `["vcpkg", "xmake"]` (default: both) |
| `header-only` | no | `true` for header-only libraries |
| `dependencies` | no | List of package dependencies |
| `options` | no | CMake options (e.g. `["BUILD_TESTS=OFF"]`) |

## Commands

### Add a package

```sh
python registry.py add some-library your-user/some-library
python registry.py add some-library your-user/some-library --branch develop
python registry.py add some-library your-user/some-library --registries vcpkg
python registry.py add some-library your-user/some-library --registries vcpkg,xmake
```

### Add a version

```sh
python registry.py add-version some-library v1.0.0
python registry.py add-version some-library --latest   # fetches latest tag from GitHub
```

### List packages

```sh
python registry.py list                # all packages
python registry.py list some-library   # details for one package
```

### Remove a version

```sh
python registry.py remove-version some-library v1.0.0
```

### Remove a package

```sh
python registry.py remove some-library
```

### Generate registry files

```sh
python registry.py generate
```

This reads `registry.json` and idempotently generates all the files needed by vcpkg and xmake:

- **xmake**: `packages/<letter>/<name>/xmake.lua` with versioned tarball hashes
- **vcpkg**: `ports/<name>/portfile.cmake`, `ports/<name>/vcpkg.json`, `versions/<letter>-/<name>.json`, and `versions/baseline.json`

For vcpkg, this also handles the git commits required for version tracking (the `git-tree` SHA that vcpkg uses to resolve versions).

Running `generate` again after adding new versions will only process the new versions — existing ones are left untouched.

```sh
python registry.py generate --no-commit   # generate files without git commits (for testing)
```
