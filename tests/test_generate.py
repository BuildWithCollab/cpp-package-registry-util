import json

import pytest
from assertpy import assert_that

from registry import (
    generate,
    generate_portfile_cmake,
    generate_vcpkg_json,
    generate_vcpkg_versions_json,
    generate_vcpkg_baseline,
    generate_xmake_lua,
    vcpkg_port_dir,
    vcpkg_port_name,
    vcpkg_version_dir,
    vcpkg_version_file,
    vcpkg_baseline_file,
    vcpkg_version_string,
    xmake_package_dir,
)


# --- xmake naming (uses literal name) ---


class TestXmakeNaming:
    def test_preserves_dashes(self, tmp_path):
        result = xmake_package_dir(tmp_path, "my-cool-lib")
        assert_that(result.parts[-2:]).is_equal_to(("m", "my-cool-lib"))

    def test_preserves_underscores(self, tmp_path):
        result = xmake_package_dir(tmp_path, "my_cool_lib")
        assert_that(result.parts[-2:]).is_equal_to(("m", "my_cool_lib"))

    def test_package_dir(self, tmp_path):
        result = xmake_package_dir(tmp_path, "my-cool-lib")
        assert_that(result.parts[-3:]).is_equal_to(("packages", "m", "my-cool-lib"))


# --- vcpkg naming (sanitized) ---


class TestVcpkgNaming:
    def test_port_name_passthrough(self):
        assert_that(vcpkg_port_name("my-lib")).is_equal_to("my-lib")

    def test_port_name_underscores_to_dashes(self):
        assert_that(vcpkg_port_name("my_cool_lib")).is_equal_to("my-cool-lib")

    def test_port_name_lowercase(self):
        assert_that(vcpkg_port_name("MyLib")).is_equal_to("mylib")

    def test_port_name_strips_invalid_chars(self):
        assert_that(vcpkg_port_name("my@lib!")).is_equal_to("mylib")

    def test_port_name_collapses_repeated_dashes(self):
        assert_that(vcpkg_port_name("my--lib")).is_equal_to("my-lib")

    def test_port_name_strips_leading_trailing_dashes(self):
        assert_that(vcpkg_port_name("-my-lib-")).is_equal_to("my-lib")

    def test_port_name_combined(self):
        assert_that(vcpkg_port_name("My_Cool__Lib!")).is_equal_to("my-cool-lib")

    def test_version_string(self):
        assert_that(vcpkg_version_string("2024-01-03", "40506ba5cbd2fe0fabe22017cfa7e9d0d0f7b182")).is_equal_to(
            "2024-01-03-40506ba"
        )

    def test_port_dir(self, tmp_path):
        result = vcpkg_port_dir(tmp_path, "some-lib")
        assert_that(result.parts[-2:]).is_equal_to(("ports", "some-lib"))

    def test_port_dir_sanitizes(self, tmp_path):
        result = vcpkg_port_dir(tmp_path, "some_lib")
        assert_that(result.parts[-2:]).is_equal_to(("ports", "some-lib"))

    def test_version_dir(self, tmp_path):
        result = vcpkg_version_dir(tmp_path, "some-lib")
        assert_that(result.parts[-2:]).is_equal_to(("versions", "s-"))

    def test_version_file(self, tmp_path):
        result = vcpkg_version_file(tmp_path, "some-lib")
        assert_that(result.parts[-3:]).is_equal_to(("versions", "s-", "some-lib.json"))

    def test_baseline_file(self, tmp_path):
        result = vcpkg_baseline_file(tmp_path)
        assert_that(result.parts[-2:]).is_equal_to(("versions", "baseline.json"))


# --- generate_xmake_lua (uses literal name) ---


class TestGenerateXmakeLua:
    def test_basic_with_dashes(self):
        result = generate_xmake_lua(
            name="my-lib",
            repo="user/my-lib",
            description="A cool library",
            versions=["v1.0.0"],
            version_hashes={"v1.0.0": "abc123"},
        )
        assert_that(result).contains('package("my-lib")')
        assert_that(result).contains('set_homepage("https://github.com/user/my-lib")')
        assert_that(result).contains('set_description("A cool library")')
        assert_that(result).contains('add_urls("https://github.com/user/my-lib/archive/refs/tags/$(version).tar.gz")')
        assert_that(result).contains('add_versions("v1.0.0", "abc123")')

    def test_basic_with_underscores(self):
        result = generate_xmake_lua(
            name="my_lib",
            repo="user/my-lib",
            description="desc",
            versions=["v1.0.0"],
            version_hashes={"v1.0.0": "abc123"},
        )
        assert_that(result).contains('package("my_lib")')

    def test_multiple_versions(self):
        result = generate_xmake_lua(
            name="my-lib",
            repo="user/my-lib",
            description="desc",
            versions=["v1.0.0", "v2.0.0"],
            version_hashes={"v1.0.0": "aaa", "v2.0.0": "bbb"},
        )
        assert_that(result).contains('add_versions("v1.0.0", "aaa")')
        assert_that(result).contains('add_versions("v2.0.0", "bbb")')

    def test_header_only(self):
        result = generate_xmake_lua(
            name="my-lib", repo="user/my-lib", description="desc",
            versions=[], version_hashes={}, header_only=True,
        )
        assert_that(result).contains('os.cp("include", package:installdir())')

    def test_cmake_install(self):
        result = generate_xmake_lua(
            name="my-lib", repo="user/my-lib", description="desc",
            versions=[], version_hashes={}, header_only=False,
        )
        assert_that(result).contains('import("package.tools.cmake").install(package)')

    def test_dependencies_literal(self):
        result = generate_xmake_lua(
            name="my-lib", repo="user/my-lib", description="desc",
            versions=[], version_hashes={},
            dependencies=["other-lib", "another_lib"],
        )
        assert_that(result).contains('add_deps("other-lib", "another_lib")')


# --- generate_portfile_cmake ---


class TestGeneratePortfileCmake:
    def test_basic(self):
        result = generate_portfile_cmake(repo="user/my-lib", ref="abc123")
        assert_that(result).contains("vcpkg_from_git(")
        assert_that(result).contains("URL https://github.com/user/my-lib.git")
        assert_that(result).contains("REF abc123")
        assert_that(result).contains("vcpkg_cmake_configure(")
        assert_that(result).contains("vcpkg_cmake_install()")
        assert_that(result).contains("LICENSE")

    def test_header_only(self):
        result = generate_portfile_cmake(repo="user/my-lib", ref="abc123", header_only=True)
        assert_that(result).contains("file(REMOVE_RECURSE")
        assert_that(result).contains("${CURRENT_PACKAGES_DIR}/debug")
        assert_that(result).contains("${CURRENT_PACKAGES_DIR}/lib")

    def test_not_header_only(self):
        result = generate_portfile_cmake(repo="user/my-lib", ref="abc123", header_only=False)
        assert_that(result).does_not_contain("REMOVE_RECURSE")

    def test_options(self):
        result = generate_portfile_cmake(
            repo="user/my-lib", ref="abc123",
            options=["BUILD_TESTS=OFF", "BUILD_EXAMPLE=OFF"],
        )
        assert_that(result).contains("OPTIONS -DBUILD_TESTS=OFF -DBUILD_EXAMPLE=OFF")


# --- generate_vcpkg_json (sanitizes names) ---


class TestGenerateVcpkgJson:
    def test_basic(self):
        result = generate_vcpkg_json("my-lib", "A cool library", "2024-01-03-40506ba")
        assert_that(result["name"]).is_equal_to("my-lib")
        assert_that(result["version-string"]).is_equal_to("2024-01-03-40506ba")
        assert_that(result["description"]).is_equal_to("A cool library")
        assert_that(result["dependencies"]).is_length(2)

    def test_sanitizes_name(self):
        result = generate_vcpkg_json("my_lib", "desc", "v1")
        assert_that(result["name"]).is_equal_to("my-lib")

    def test_with_dependencies_sanitized(self):
        result = generate_vcpkg_json(
            "my-lib", "desc", "v1", dependencies=["other_lib", "another-lib"]
        )
        assert_that(result["dependencies"]).is_length(4)
        assert_that(result["dependencies"][2]).is_equal_to("other-lib")
        assert_that(result["dependencies"][3]).is_equal_to("another-lib")


# --- generate_vcpkg_versions_json ---


class TestGenerateVcpkgVersionsJson:
    def test_basic(self):
        entries = [
            {"version-string": "2024-01-01-abc1234", "git-tree": "deadbeef"},
            {"version-string": "2024-01-02-bcd2345", "git-tree": "cafebabe"},
        ]
        result = generate_vcpkg_versions_json(entries)
        assert_that(result["versions"]).is_length(2)
        assert_that(result["versions"][0]["version-string"]).is_equal_to("2024-01-01-abc1234")


# --- generate_vcpkg_baseline ---


class TestGenerateVcpkgBaseline:
    def test_basic(self):
        result = generate_vcpkg_baseline({"my-lib": "2024-01-03-40506ba"})
        assert_that(result["default"]["my-lib"]["baseline"]).is_equal_to("2024-01-03-40506ba")
        assert_that(result["default"]["my-lib"]["port-version"]).is_equal_to(0)

    def test_multiple_packages(self):
        result = generate_vcpkg_baseline({
            "lib-a": "v1",
            "lib-b": "v2",
        })
        assert_that(result["default"]).contains_key("lib-a")
        assert_that(result["default"]).contains_key("lib-b")


# --- generate orchestrator (with fake fetch) ---


def make_fake_fetch(description="A test library", sha256="fakehash123", commit_sha="abc123def456", commit_date="2024-06-15"):
    def fake_fetch(kind, **kwargs):
        if kind == "description":
            return description
        elif kind == "tarball_sha256":
            return sha256
        elif kind == "commit_info":
            return {"sha": commit_sha, "date": commit_date}
        raise ValueError(f"Unknown: {kind}")
    return fake_fetch


class TestGenerateXmakeFiles:
    def test_generates_xmake_lua_with_literal_name(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["xmake"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        xmake_path = tmp_path / "packages" / "m" / "my-lib" / "xmake.lua"
        assert_that(xmake_path.exists()).is_true()
        content = xmake_path.read_text()
        assert_that(content).contains('package("my-lib")')
        assert_that(content).contains('add_versions("v1.0.0", "fakehash123")')

    def test_generates_with_dependencies_literal(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["xmake"],
                    "dependencies": ["other-lib"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        xmake_path = tmp_path / "packages" / "m" / "my-lib" / "xmake.lua"
        content = xmake_path.read_text()
        assert_that(content).contains('add_deps("other-lib")')

    def test_header_only_xmake(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["xmake"],
                    "header-only": True,
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        xmake_path = tmp_path / "packages" / "m" / "my-lib" / "xmake.lua"
        content = xmake_path.read_text()
        assert_that(content).contains('os.cp("include", package:installdir())')


class TestGenerateVcpkgFiles:
    def test_generates_port_files(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        portfile = tmp_path / "ports" / "my-lib" / "portfile.cmake"
        assert_that(portfile.exists()).is_true()
        content = portfile.read_text()
        assert_that(content).contains("vcpkg_from_git(")
        assert_that(content).contains("REF abc123def456")

        vcpkg_json = tmp_path / "ports" / "my-lib" / "vcpkg.json"
        assert_that(vcpkg_json.exists()).is_true()
        pkg_data = json.loads(vcpkg_json.read_text())
        assert_that(pkg_data["name"]).is_equal_to("my-lib")
        assert_that(pkg_data["version-string"]).is_equal_to("2024-06-15-abc123d")

    def test_vcpkg_sanitizes_underscore_name(self, tmp_path):
        data = {
            "packages": {
                "my_lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        # Port dir uses sanitized name
        portfile = tmp_path / "ports" / "my-lib" / "portfile.cmake"
        assert_that(portfile.exists()).is_true()

        # vcpkg.json name is sanitized
        vcpkg_json = tmp_path / "ports" / "my-lib" / "vcpkg.json"
        pkg_data = json.loads(vcpkg_json.read_text())
        assert_that(pkg_data["name"]).is_equal_to("my-lib")

        # baseline uses sanitized name
        baseline = tmp_path / "versions" / "baseline.json"
        bdata = json.loads(baseline.read_text())
        assert_that(bdata["default"]).contains_key("my-lib")
        assert_that(bdata["default"]).does_not_contain_key("my_lib")

    def test_generates_version_file(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        version_file = tmp_path / "versions" / "m-" / "my-lib.json"
        assert_that(version_file.exists()).is_true()
        vdata = json.loads(version_file.read_text())
        assert_that(vdata["versions"]).is_length(1)
        assert_that(vdata["versions"][0]["version-string"]).is_equal_to("2024-06-15-abc123d")

    def test_generates_baseline(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        baseline = tmp_path / "versions" / "baseline.json"
        assert_that(baseline.exists()).is_true()
        bdata = json.loads(baseline.read_text())
        assert_that(bdata["default"]["my-lib"]["baseline"]).is_equal_to("2024-06-15-abc123d")

    def test_header_only_portfile(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                    "header-only": True,
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        portfile = tmp_path / "ports" / "my-lib" / "portfile.cmake"
        content = portfile.read_text()
        assert_that(content).contains("REMOVE_RECURSE")

    def test_with_options(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                    "options": ["BUILD_TESTS=OFF"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        portfile = tmp_path / "ports" / "my-lib" / "portfile.cmake"
        content = portfile.read_text()
        assert_that(content).contains("-DBUILD_TESTS=OFF")

    def test_vcpkg_skips_if_no_versions(self, tmp_path, capsys):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "registries": ["vcpkg"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        portfile = tmp_path / "ports" / "my-lib" / "portfile.cmake"
        assert_that(portfile.exists()).is_false()
        assert_that(capsys.readouterr().out).contains("no versions")

    def test_with_dependencies(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                    "dependencies": ["other_lib"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        vcpkg_json = tmp_path / "ports" / "my-lib" / "vcpkg.json"
        pkg_data = json.loads(vcpkg_json.read_text())
        assert_that(pkg_data["dependencies"]).contains("other-lib")


class TestGenerateBothRegistries:
    def test_generates_both(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        # xmake uses literal name
        xmake_path = tmp_path / "packages" / "m" / "my-lib" / "xmake.lua"
        assert_that(xmake_path.exists()).is_true()

        # vcpkg uses sanitized name (same in this case)
        portfile = tmp_path / "ports" / "my-lib" / "portfile.cmake"
        assert_that(portfile.exists()).is_true()

    def test_multiple_packages(self, tmp_path):
        descriptions = {"user/lib-a": "Library A", "user/lib-b": "Library B"}

        def multi_fetch(kind, **kwargs):
            if kind == "description":
                return descriptions.get(kwargs["repo"], "desc")
            elif kind == "tarball_sha256":
                return "hash_" + kwargs["version"]
            elif kind == "commit_info":
                return {"sha": "aaa111bbb222", "date": "2024-03-15"}
            raise ValueError(kind)

        data = {
            "packages": {
                "lib-a": {"repo": "user/lib-a", "versions": ["v1.0.0"]},
                "lib-b": {"repo": "user/lib-b", "versions": ["v2.0.0"], "registries": ["xmake"]},
            }
        }
        generate(data, tmp_path, fetch_fn=multi_fetch, commit=False)

        # lib-a: both registries
        assert_that((tmp_path / "packages" / "l" / "lib-a" / "xmake.lua").exists()).is_true()
        assert_that((tmp_path / "ports" / "lib-a" / "portfile.cmake").exists()).is_true()

        # lib-b: xmake only
        assert_that((tmp_path / "packages" / "l" / "lib-b" / "xmake.lua").exists()).is_true()
        assert_that((tmp_path / "ports" / "lib-b").exists()).is_false()

        # baseline only has lib-a (lib-b is xmake-only)
        baseline = tmp_path / "versions" / "baseline.json"
        bdata = json.loads(baseline.read_text())
        assert_that(bdata["default"]).contains_key("lib-a")
        assert_that(bdata["default"]).does_not_contain_key("lib-b")


class TestGenerateIdempotent:
    def test_xmake_idempotent(self, tmp_path):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["xmake"],
                }
            }
        }
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)
        first_content = (tmp_path / "packages" / "m" / "my-lib" / "xmake.lua").read_text()

        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)
        second_content = (tmp_path / "packages" / "m" / "my-lib" / "xmake.lua").read_text()

        assert_that(first_content).is_equal_to(second_content)

    def test_vcpkg_reuses_existing_versions(self, tmp_path, capsys):
        data = {
            "packages": {
                "my-lib": {
                    "repo": "user/my-lib",
                    "versions": ["v1.0.0"],
                    "registries": ["vcpkg"],
                }
            }
        }
        # First run: creates everything
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)

        # Second run: should reuse existing git-tree
        generate(data, tmp_path, fetch_fn=make_fake_fetch(), commit=False)
        output = capsys.readouterr().out
        assert_that(output).contains("already tracked")
