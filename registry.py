# Author: Mrowr Purr
# Description: A CLI tool to manage a registry.json file that defines
#              C++ packages for vcpkg and xmake registries.
#
# Usage:
# > python registry.py list
# > python registry.py list some-lib
# > python registry.py add some-lib mrowr/some-lib
# > python registry.py add some-lib mrowr/some-lib --branch my-branch --registries vcpkg
# > python registry.py add-version some-lib v1.0.0
# > python registry.py add-version some-lib --latest
# > python registry.py remove-version some-lib v1.0.0
# > python registry.py remove some-lib
# > python registry.py generate
#
# Implementation notes:
#
# > This script only uses the Python standard library
# > so that it is easy to share and run on any system
# > without requiring additional dependencies.
#
# > This script is intentionally stored in a single file
# > to make it easy to copy and paste into a project.

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_REGISTRY_FILE = "registry.json"
VALID_REGISTRIES = ("vcpkg", "xmake")


# --- Registry data operations ---


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"packages": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def add_package(
    data: dict,
    name: str,
    repo: str,
    branch: str | None = None,
    registries: list[str] | None = None,
) -> dict:
    packages = data.setdefault("packages", {})
    if name in packages:
        print(f"Package '{name}' already exists.", file=sys.stderr)
        sys.exit(1)
    entry = {"repo": repo}
    if branch:
        entry["branch"] = branch
    if registries and set(registries) != set(VALID_REGISTRIES):
        entry["registries"] = registries
    packages[name] = entry
    return data


def remove_package(data: dict, name: str) -> dict:
    packages = data.get("packages", {})
    if name not in packages:
        print(f"Package '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    del packages[name]
    return data


def add_version(data: dict, name: str, version: str) -> dict:
    packages = data.get("packages", {})
    if name not in packages:
        print(f"Package '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    versions = packages[name].setdefault("versions", [])
    if version in versions:
        print(f"Version '{version}' already exists for '{name}'.", file=sys.stderr)
        sys.exit(1)
    versions.append(version)
    return data


def remove_version(data: dict, name: str, version: str) -> dict:
    packages = data.get("packages", {})
    if name not in packages:
        print(f"Package '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    versions = packages[name].get("versions", [])
    if version not in versions:
        print(f"Version '{version}' not found for '{name}'.", file=sys.stderr)
        sys.exit(1)
    versions.remove(version)
    if not versions:
        del packages[name]["versions"]
    return data


def list_packages(data: dict, name: str | None = None) -> None:
    packages = data.get("packages", {})
    if name:
        if name not in packages:
            print(f"Package '{name}' not found.", file=sys.stderr)
            sys.exit(1)
        pkg = packages[name]
        print(f"{name} ({pkg['repo']})")
        if "branch" in pkg:
            print(f"  branch: {pkg['branch']}")
        registries = pkg.get("registries", list(VALID_REGISTRIES))
        print(f"  registries: {', '.join(registries)}")
        versions = pkg.get("versions", [])
        if versions:
            print(f"  versions:")
            for v in versions:
                print(f"    - {v}")
        else:
            print(f"  versions: (none)")
    else:
        if not packages:
            print("No packages.")
            return
        for pkg_name, pkg in packages.items():
            registries = pkg.get("registries", list(VALID_REGISTRIES))
            version_count = len(pkg.get("versions", []))
            print(f"  {pkg_name} ({pkg['repo']}) [{', '.join(registries)}] ({version_count} versions)")


def parse_kv_pair(s: str):
    if "=" not in s:
        return s, True
    key, val = s.split("=", 1)
    if val.lower() == "true":
        return key, True
    if val.lower() == "false":
        return key, False
    try:
        return key, int(val)
    except ValueError:
        pass
    try:
        return key, float(val)
    except ValueError:
        pass
    return key, val


def add_dependency(data: dict, name: str, dep_name: str, configs: dict | None = None) -> dict:
    packages = data.get("packages", {})
    if name not in packages:
        print(f"Package '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    deps = packages[name].setdefault("dependencies", [])
    # Check if dep already exists
    for d in deps:
        existing_name = d if isinstance(d, str) else d["name"]
        if existing_name == dep_name:
            print(f"Dependency '{dep_name}' already exists for '{name}'.", file=sys.stderr)
            sys.exit(1)
    if configs:
        deps.append({"name": dep_name, "configs": configs})
    else:
        deps.append(dep_name)
    return data


def remove_dependency(data: dict, name: str, dep_name: str) -> dict:
    packages = data.get("packages", {})
    if name not in packages:
        print(f"Package '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    deps = packages[name].get("dependencies", [])
    new_deps = []
    found = False
    for d in deps:
        existing_name = d if isinstance(d, str) else d["name"]
        if existing_name == dep_name:
            found = True
        else:
            new_deps.append(d)
    if not found:
        print(f"Dependency '{dep_name}' not found for '{name}'.", file=sys.stderr)
        sys.exit(1)
    if new_deps:
        packages[name]["dependencies"] = new_deps
    else:
        del packages[name]["dependencies"]
    return data


def set_config(data: dict, name: str, key: str, value) -> dict:
    packages = data.get("packages", {})
    if name not in packages:
        print(f"Package '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    config = packages[name].setdefault("xmake-config", {})
    config[key] = value
    return data


def get_package_registries(pkg: dict) -> list[str]:
    return pkg.get("registries", list(VALID_REGISTRIES))


# --- GitHub API ---


def _github_request(url: str) -> Request:
    req = Request(url)
    token = os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return req


def _github_fetch_json(url: str, context: str = "") -> dict | list:
    try:
        with urlopen(_github_request(url)) as response:
            return json.load(response)
    except HTTPError as e:
        if e.code == 404:
            print(f"Repository not found: {context or url}", file=sys.stderr)
            print("Is the repository private? This tool requires public repositories (or set GH_TOKEN for private repos).", file=sys.stderr)
        elif e.code == 403:
            print(f"Access denied: {context or url}", file=sys.stderr)
            print("You may be rate-limited. Set GH_TOKEN to authenticate requests.", file=sys.stderr)
        else:
            print(f"GitHub API error ({e.code}): {context or url}", file=sys.stderr)
        sys.exit(1)


def get_latest_tag(repo: str) -> str:
    tags = _github_fetch_json(
        f"https://api.github.com/repos/{repo}/tags", context=repo
    )
    if not tags:
        print(f"No tags found for '{repo}'.", file=sys.stderr)
        sys.exit(1)
    return tags[0]["name"]


def get_repo_info(repo: str) -> dict:
    data = _github_fetch_json(
        f"https://api.github.com/repos/{repo}", context=repo
    )
    return {
        "description": data.get("description") or "",
        "license": (data.get("license") or {}).get("spdx_id") or "",
    }


def get_commit_info_for_ref(repo: str, ref: str) -> dict:
    data = _github_fetch_json(
        f"https://api.github.com/repos/{repo}/commits/{ref}", context=f"{repo}@{ref}"
    )
    return {
        "sha": data["sha"],
        "date": data["commit"]["committer"]["date"][:10],
    }


def fetch_tarball_sha256(repo: str, version: str) -> str:
    url = f"https://github.com/{repo}/archive/refs/tags/{version}.tar.gz"
    try:
        with urlopen(_github_request(url)) as response:
            data = response.read()
    except HTTPError as e:
        if e.code == 404:
            print(f"Tarball not found: {repo}@{version}", file=sys.stderr)
            print("Does this tag exist?", file=sys.stderr)
        else:
            print(f"Failed to download tarball ({e.code}): {repo}@{version}", file=sys.stderr)
        sys.exit(1)
    return hashlib.sha256(data).hexdigest()


# --- Git operations ---


def git_exec(args: list[str], working_dir: str | None = None) -> str:
    result = subprocess.run(
        ["git"] + [str(a) for a in args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=working_dir,
    )
    if result.returncode != 0:
        text_args = " ".join(str(a) for a in args)
        print(f"git {text_args} failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def git_tree_sha_for_path(path: str, working_dir: str | None = None) -> str:
    return git_exec(["rev-parse", f"HEAD:{path}"], working_dir)


# --- xmake generation ---


def xmake_package_dir(root: Path, name: str) -> Path:
    return root / "packages" / name[0].lower() / name


def _lua_value(val) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        return f'"{val}"'
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, dict):
        pairs = ", ".join(f"{k} = {_lua_value(v)}" for k, v in val.items())
        return "{ " + pairs + " }"
    return str(val)


def _format_xmake_dep(dep) -> str:
    if isinstance(dep, str):
        return f'    add_deps("{dep}")'
    name = dep["name"]
    configs = dep.get("configs", {})
    if configs:
        return f'    add_deps("{name}", {{ configs = {_lua_value(configs)} }})'
    return f'    add_deps("{name}")'


def generate_xmake_lua(
    name: str,
    repo: str,
    description: str,
    versions: list[str],
    version_hashes: dict[str, str],
    dependencies: list | None = None,
    header_only: bool = False,
    license: str = "",
    xmake_config: dict | None = None,
) -> str:
    lines = []
    lines.append(f'package("{name}")')
    lines.append(f'    set_homepage("https://github.com/{repo}")')
    lines.append(f'    set_description("{description}")')
    if license:
        lines.append(f'    set_license("{license}")')

    lines.append(f'    add_urls("https://github.com/{repo}/archive/refs/tags/$(version).tar.gz")')

    for version in versions:
        sha = version_hashes.get(version, "")
        lines.append(f'    add_versions("{version}", "{sha}")')

    if dependencies:
        for dep in dependencies:
            lines.append(_format_xmake_dep(dep))

    if header_only:
        lines.append('    on_install(function (package)')
        lines.append('        os.cp("include", package:installdir())')
        lines.append('    end)')
    else:
        lines.append('    on_install(function (package)')
        if xmake_config:
            config_str = _lua_value(xmake_config)
            lines.append(f'        import("package.tools.xmake").install(package, {config_str})')
        else:
            lines.append('        import("package.tools.xmake").install(package)')
        lines.append('    end)')

    return "\n".join(lines) + "\n"


# --- vcpkg generation ---


def vcpkg_port_name(name: str) -> str:
    name = name.replace("_", "-").lower()
    name = re.sub(r"[^a-z0-9-]", "", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name


def vcpkg_version_string(date: str, sha: str) -> str:
    return f"{date}-{sha[:7]}"


def vcpkg_port_dir(root: Path, name: str) -> Path:
    pname = vcpkg_port_name(name)
    return root / "ports" / pname


def vcpkg_version_dir(root: Path, name: str) -> Path:
    pname = vcpkg_port_name(name)
    return root / "versions" / f"{pname[0]}-"


def vcpkg_version_file(root: Path, name: str) -> Path:
    pname = vcpkg_port_name(name)
    return vcpkg_version_dir(root, name) / f"{pname}.json"


def vcpkg_baseline_file(root: Path) -> Path:
    return root / "versions" / "baseline.json"


def generate_portfile_cmake(
    repo: str,
    ref: str,
    header_only: bool = False,
    options: list[str] | None = None,
) -> str:
    options_text = ""
    if options:
        options_text = "\n    OPTIONS " + " ".join(f"-D{opt}" for opt in options)

    cleanup = ""
    if header_only:
        cleanup = """
file(REMOVE_RECURSE
    "${CURRENT_PACKAGES_DIR}/debug"
    "${CURRENT_PACKAGES_DIR}/lib"
)"""

    return f"""vcpkg_from_git(
    OUT_SOURCE_PATH SOURCE_PATH
    URL https://github.com/{repo}.git
    REF {ref}
)

vcpkg_cmake_configure(
    SOURCE_PATH ${{SOURCE_PATH}}{options_text}
)

vcpkg_cmake_install(){cleanup}

file(MAKE_DIRECTORY "${{CURRENT_PACKAGES_DIR}}/share/${{PORT}}")
file(INSTALL "${{SOURCE_PATH}}/LICENSE" DESTINATION "${{CURRENT_PACKAGES_DIR}}/share/${{PORT}}" RENAME copyright)
"""


def generate_vcpkg_json(
    name: str,
    description: str,
    version_string: str,
    dependencies: list[str] | None = None,
) -> dict:
    pname = vcpkg_port_name(name)
    vcpkg_json = {
        "name": pname,
        "version-string": version_string,
        "description": description,
        "dependencies": [
            {"name": "vcpkg-cmake", "host": True},
            {"name": "vcpkg-cmake-config", "host": True},
        ],
    }
    for dep in (dependencies or []):
        vcpkg_json["dependencies"].append(vcpkg_port_name(dep))
    return vcpkg_json


def generate_vcpkg_versions_json(versions: list[dict]) -> dict:
    return {"versions": versions}


def generate_vcpkg_baseline(packages: dict[str, str]) -> dict:
    default = {}
    for name, version_string in packages.items():
        default[name] = {"baseline": version_string, "port-version": 0}
    return {"default": default}


# --- generate orchestrator ---


def generate(data: dict, root: Path, fetch_fn=None, commit: bool = True) -> None:
    if fetch_fn is None:
        fetch_fn = _default_fetch

    packages = data.get("packages", {})
    if not packages:
        print("No packages to generate.")
        return

    working_dir = str(root)
    baseline_entries = {}

    # Load existing baseline if present
    baseline_path = vcpkg_baseline_file(root)
    if baseline_path.exists():
        with open(baseline_path, "r", encoding="utf-8") as f:
            existing_baseline = json.load(f)
        baseline_entries = existing_baseline.get("default", {})

    for name, pkg in packages.items():
        registries = get_package_registries(pkg)
        repo = pkg["repo"]
        versions = pkg.get("versions", [])
        dependencies = pkg.get("dependencies", [])
        header_only = pkg.get("header-only", False)
        options = pkg.get("options", [])

        print(f"--- {name} ---")

        repo_info = fetch_fn("repo_info", repo=repo)
        description = repo_info["description"]
        license_id = repo_info["license"]

        xmake_config = pkg.get("xmake-config", {})

        if "xmake" in registries:
            _generate_xmake(
                root, name, repo, description, versions, dependencies,
                header_only, fetch_fn, license_id, xmake_config,
            )

        if "vcpkg" in registries:
            _generate_vcpkg(
                root, name, repo, description, versions, dependencies,
                header_only, options, fetch_fn, commit, working_dir, baseline_entries
            )

    # Write baseline (all vcpkg packages)
    if baseline_entries:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump({"default": baseline_entries}, f, indent=2)
        if commit:
            git_exec(["add", str(baseline_path)], working_dir)


def _generate_xmake(root, name, repo, description, versions, dependencies, header_only, fetch_fn, license_id="", xmake_config=None):
    version_hashes = {}
    for version in versions:
        print(f"  xmake: fetching SHA256 for {version}...")
        sha256 = fetch_fn("tarball_sha256", repo=repo, version=version)
        version_hashes[version] = sha256

    xmake_lua = generate_xmake_lua(
        name, repo, description, versions, version_hashes,
        dependencies=dependencies, header_only=header_only,
        license=license_id, xmake_config=xmake_config,
    )

    pkg_dir = xmake_package_dir(root, name)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    xmake_path = pkg_dir / "xmake.lua"
    xmake_path.write_text(xmake_lua, encoding="utf-8")
    print(f"  xmake: wrote {xmake_path}")


def _generate_vcpkg(
    root, name, repo, description, versions, dependencies,
    header_only, options, fetch_fn, commit, working_dir, baseline_entries
):
    if not versions:
        print(f"  vcpkg: no versions for '{name}', skipping")
        return

    # Load existing version entries to avoid re-generating
    version_file = vcpkg_version_file(root, name)
    existing_versions = {}
    if version_file.exists():
        with open(version_file, "r", encoding="utf-8") as f:
            vdata = json.load(f)
        for entry in vdata.get("versions", []):
            existing_versions[entry["version-string"]] = entry["git-tree"]

    version_entries = []

    for version in versions:
        print(f"  vcpkg: processing {version}...")
        commit_info = fetch_fn("commit_info", repo=repo, ref=version)
        vs = vcpkg_version_string(commit_info["date"], commit_info["sha"])

        # If this version-string already has a git-tree, reuse it
        if vs in existing_versions:
            print(f"  vcpkg: {vs} already tracked, reusing git-tree")
            version_entries.append({"version-string": vs, "git-tree": existing_versions[vs]})
            continue

        # Generate port files for this version
        port_dir = vcpkg_port_dir(root, name)
        port_dir.mkdir(parents=True, exist_ok=True)

        portfile = generate_portfile_cmake(
            repo, commit_info["sha"], header_only=header_only, options=options,
        )
        (port_dir / "portfile.cmake").write_text(portfile, encoding="utf-8")

        vcpkg_json = generate_vcpkg_json(name, description, vs, dependencies)
        with open(port_dir / "vcpkg.json", "w", encoding="utf-8") as f:
            json.dump(vcpkg_json, f, indent=2)

        pname = vcpkg_port_name(name)
        if commit:
            git_exec(["add", f"ports/{pname}"], working_dir)
            git_exec(["commit", "-m", f"Update {pname} to {vs}"], working_dir)
            tree_sha = git_tree_sha_for_path(f"ports/{pname}", working_dir)
            print(f"  vcpkg: git-tree {tree_sha}")
        else:
            tree_sha = "no-commit-mode"

        version_entries.append({"version-string": vs, "git-tree": tree_sha})

    # Write versions file
    latest_vs = version_entries[-1]["version-string"]
    version_dir = vcpkg_version_dir(root, name)
    version_dir.mkdir(parents=True, exist_ok=True)
    with open(version_file, "w", encoding="utf-8") as f:
        json.dump(generate_vcpkg_versions_json(version_entries), f, indent=2)

    if commit:
        git_exec(["add", str(version_file)], working_dir)

    baseline_entries[vcpkg_port_name(name)] = {"baseline": latest_vs, "port-version": 0}
    print(f"  vcpkg: baseline -> {latest_vs}")


def _default_fetch(kind: str, **kwargs) -> str | dict:
    if kind == "repo_info":
        return get_repo_info(kwargs["repo"])
    elif kind == "tarball_sha256":
        return fetch_tarball_sha256(kwargs["repo"], kwargs["version"])
    elif kind == "commit_info":
        return get_commit_info_for_ref(kwargs["repo"], kwargs["ref"])
    raise ValueError(f"Unknown fetch kind: {kind}")


# --- CLI ---


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage a registry.json file for vcpkg and xmake C++ package registries."
    )
    parser.add_argument(
        "-f", "--file",
        default=DEFAULT_REGISTRY_FILE,
        help=f"Path to the registry JSON file (default: {DEFAULT_REGISTRY_FILE})",
    )

    subparsers = parser.add_subparsers(dest="command")

    # add
    add_parser = subparsers.add_parser("add", help="Add a package to the registry.")
    add_parser.add_argument("name", help="Package name (e.g. some-lib)")
    add_parser.add_argument("repo", help="GitHub repository (e.g. user/repo)")
    add_parser.add_argument("--branch", help="Git branch to track (default: repo default)")
    add_parser.add_argument(
        "--registries",
        default="vcpkg,xmake",
        help="Comma-separated list of registries (default: vcpkg,xmake)",
    )

    # remove
    rm_parser = subparsers.add_parser("remove", help="Remove a package from the registry.")
    rm_parser.add_argument("name", help="Package name to remove")

    # add-version
    av_parser = subparsers.add_parser("add-version", help="Add a version to a package.")
    av_parser.add_argument("name", help="Package name")
    av_parser.add_argument("version", nargs="?", help="Version string (e.g. v1.0.0)")
    av_parser.add_argument("--latest", action="store_true", help="Fetch the latest tag from GitHub")

    # remove-version
    rv_parser = subparsers.add_parser("remove-version", help="Remove a version from a package.")
    rv_parser.add_argument("name", help="Package name")
    rv_parser.add_argument("version", help="Version string to remove")

    # list
    ls_parser = subparsers.add_parser("list", help="List packages or versions.")
    ls_parser.add_argument("name", nargs="?", help="Package name (omit to list all)")

    # add-dep
    ad_parser = subparsers.add_parser("add-dep", help="Add a dependency to a package.")
    ad_parser.add_argument("name", help="Package name")
    ad_parser.add_argument("dep", help="Dependency name")
    ad_parser.add_argument("configs", nargs="*", help="Config key=value pairs (e.g. filesystem=true)")

    # remove-dep
    rd_parser = subparsers.add_parser("remove-dep", help="Remove a dependency from a package.")
    rd_parser.add_argument("name", help="Package name")
    rd_parser.add_argument("dep", help="Dependency name to remove")

    # set-config
    sc_parser = subparsers.add_parser("set-config", help="Set xmake-config values for a package.")
    sc_parser.add_argument("name", help="Package name")
    sc_parser.add_argument("values", nargs="+", help="Config key=value pairs (e.g. build_tests=false)")

    # generate
    gen_parser = subparsers.add_parser("generate", help="Generate vcpkg and xmake registry files.")
    gen_parser.add_argument(
        "--no-commit", action="store_true",
        help="Generate files without git commits (useful for testing)",
    )

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    registry_path = Path(args.file)

    if args.command == "list":
        data = load_registry(registry_path)
        list_packages(data, args.name)
        return

    if args.command == "generate":
        data = load_registry(registry_path)
        root = registry_path.parent
        generate(data, root, commit=not args.no_commit)
        if not args.no_commit:
            git_exec(["commit", "--amend", "--no-edit"], str(root))
        print("Done.")
        return

    # All other commands modify the registry file
    data = load_registry(registry_path)

    if args.command == "add":
        registries = [r.strip() for r in args.registries.split(",")]
        for r in registries:
            if r not in VALID_REGISTRIES:
                print(f"Invalid registry: '{r}'. Valid options: {', '.join(VALID_REGISTRIES)}", file=sys.stderr)
                sys.exit(1)
        add_package(data, args.name, args.repo, branch=args.branch, registries=registries)

    elif args.command == "remove":
        remove_package(data, args.name)

    elif args.command == "add-version":
        if args.latest:
            packages = data.get("packages", {})
            if args.name not in packages:
                print(f"Package '{args.name}' not found.", file=sys.stderr)
                sys.exit(1)
            repo = packages[args.name]["repo"]
            version = get_latest_tag(repo)
            print(f"Latest tag for '{repo}': {version}")
        elif args.version:
            version = args.version
        else:
            print("Provide a version string or use --latest.", file=sys.stderr)
            sys.exit(1)
        add_version(data, args.name, version)

    elif args.command == "remove-version":
        remove_version(data, args.name, args.version)

    elif args.command == "add-dep":
        configs = {}
        for pair in (args.configs or []):
            k, v = parse_kv_pair(pair)
            configs[k] = v
        add_dependency(data, args.name, args.dep, configs=configs or None)

    elif args.command == "remove-dep":
        remove_dependency(data, args.name, args.dep)

    elif args.command == "set-config":
        for pair in args.values:
            k, v = parse_kv_pair(pair)
            set_config(data, args.name, k, v)

    save_registry(registry_path, data)


if __name__ == "__main__":
    main()
