import json

import pytest
from assertpy import assert_that

from registry import (
    add_package,
    add_version,
    list_packages,
    load_registry,
    remove_package,
    remove_version,
    save_registry,
)


@pytest.fixture
def empty_registry():
    return {"packages": {}}


@pytest.fixture
def registry_with_one_package():
    return {
        "packages": {
            "some-lib": {
                "repo": "mrowr/some-lib",
            }
        }
    }


@pytest.fixture
def registry_with_versions():
    return {
        "packages": {
            "some-lib": {
                "repo": "mrowr/some-lib",
                "versions": ["v1.0.0", "v2.0.0"],
            }
        }
    }


# --- load / save ---


class TestLoadSave:
    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        data = load_registry(tmp_path / "nope.json")
        assert_that(data).is_equal_to({"packages": {}})

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "registry.json"
        original = {"packages": {"foo": {"repo": "user/foo"}}}
        save_registry(path, original)
        loaded = load_registry(path)
        assert_that(loaded).is_equal_to(original)

    def test_save_writes_pretty_json(self, tmp_path):
        path = tmp_path / "registry.json"
        save_registry(path, {"packages": {}})
        content = path.read_text()
        assert_that(content).contains("\n")
        assert_that(content).ends_with("\n")


# --- add_package ---


class TestAddPackage:
    def test_add_minimal(self, empty_registry):
        data = add_package(empty_registry, "my-lib", "user/my-lib")
        assert_that(data["packages"]).contains_key("my-lib")
        assert_that(data["packages"]["my-lib"]["repo"]).is_equal_to("user/my-lib")

    def test_add_with_branch(self, empty_registry):
        data = add_package(empty_registry, "my-lib", "user/my-lib", branch="develop")
        assert_that(data["packages"]["my-lib"]["branch"]).is_equal_to("develop")

    def test_add_without_branch_omits_key(self, empty_registry):
        data = add_package(empty_registry, "my-lib", "user/my-lib")
        assert_that(data["packages"]["my-lib"]).does_not_contain_key("branch")

    def test_add_both_registries_omits_key(self, empty_registry):
        data = add_package(
            empty_registry, "my-lib", "user/my-lib", registries=["vcpkg", "xmake"]
        )
        assert_that(data["packages"]["my-lib"]).does_not_contain_key("registries")

    def test_add_single_registry_includes_key(self, empty_registry):
        data = add_package(
            empty_registry, "my-lib", "user/my-lib", registries=["vcpkg"]
        )
        assert_that(data["packages"]["my-lib"]["registries"]).is_equal_to(["vcpkg"])

    def test_add_duplicate_exits(self, registry_with_one_package):
        with pytest.raises(SystemExit):
            add_package(registry_with_one_package, "some-lib", "other/repo")


# --- remove_package ---


class TestRemovePackage:
    def test_remove_existing(self, registry_with_one_package):
        data = remove_package(registry_with_one_package, "some-lib")
        assert_that(data["packages"]).does_not_contain_key("some-lib")

    def test_remove_nonexistent_exits(self, empty_registry):
        with pytest.raises(SystemExit):
            remove_package(empty_registry, "nope")


# --- add_version ---


class TestAddVersion:
    def test_add_first_version(self, registry_with_one_package):
        data = add_version(registry_with_one_package, "some-lib", "v1.0.0")
        assert_that(data["packages"]["some-lib"]["versions"]).is_equal_to(["v1.0.0"])

    def test_add_second_version(self, registry_with_versions):
        data = add_version(registry_with_versions, "some-lib", "v3.0.0")
        assert_that(data["packages"]["some-lib"]["versions"]).is_equal_to(
            ["v1.0.0", "v2.0.0", "v3.0.0"]
        )

    def test_add_duplicate_version_exits(self, registry_with_versions):
        with pytest.raises(SystemExit):
            add_version(registry_with_versions, "some-lib", "v1.0.0")

    def test_add_version_nonexistent_package_exits(self, empty_registry):
        with pytest.raises(SystemExit):
            add_version(empty_registry, "nope", "v1.0.0")


# --- remove_version ---


class TestRemoveVersion:
    def test_remove_version(self, registry_with_versions):
        data = remove_version(registry_with_versions, "some-lib", "v1.0.0")
        assert_that(data["packages"]["some-lib"]["versions"]).is_equal_to(["v2.0.0"])

    def test_remove_last_version_removes_key(self, registry_with_one_package):
        add_version(registry_with_one_package, "some-lib", "v1.0.0")
        data = remove_version(registry_with_one_package, "some-lib", "v1.0.0")
        assert_that(data["packages"]["some-lib"]).does_not_contain_key("versions")

    def test_remove_nonexistent_version_exits(self, registry_with_versions):
        with pytest.raises(SystemExit):
            remove_version(registry_with_versions, "some-lib", "v9.9.9")

    def test_remove_version_nonexistent_package_exits(self, empty_registry):
        with pytest.raises(SystemExit):
            remove_version(empty_registry, "nope", "v1.0.0")


# --- list_packages ---


class TestListPackages:
    def test_list_empty(self, empty_registry, capsys):
        list_packages(empty_registry)
        assert_that(capsys.readouterr().out).contains("No packages")

    def test_list_all(self, registry_with_versions, capsys):
        list_packages(registry_with_versions)
        output = capsys.readouterr().out
        assert_that(output).contains("some-lib")
        assert_that(output).contains("mrowr/some-lib")

    def test_list_specific_package(self, registry_with_versions, capsys):
        list_packages(registry_with_versions, "some-lib")
        output = capsys.readouterr().out
        assert_that(output).contains("some-lib")
        assert_that(output).contains("v1.0.0")
        assert_that(output).contains("v2.0.0")

    def test_list_nonexistent_package_exits(self, empty_registry):
        with pytest.raises(SystemExit):
            list_packages(empty_registry, "nope")


# --- CLI integration (via main) ---


class TestCLI:
    def test_add_via_cli(self, tmp_path):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib"])

        data = json.loads(registry_file.read_text())
        assert_that(data["packages"]).contains_key("my-lib")

    def test_add_then_list_via_cli(self, tmp_path, capsys):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib"])
        main(["-f", str(registry_file), "list"])

        output = capsys.readouterr().out
        assert_that(output).contains("my-lib")

    def test_add_version_via_cli(self, tmp_path):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib"])
        main(["-f", str(registry_file), "add-version", "my-lib", "v1.0.0"])

        data = json.loads(registry_file.read_text())
        assert_that(data["packages"]["my-lib"]["versions"]).contains("v1.0.0")

    def test_remove_version_via_cli(self, tmp_path):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib"])
        main(["-f", str(registry_file), "add-version", "my-lib", "v1.0.0"])
        main(["-f", str(registry_file), "remove-version", "my-lib", "v1.0.0"])

        data = json.loads(registry_file.read_text())
        assert_that(data["packages"]["my-lib"]).does_not_contain_key("versions")

    def test_remove_via_cli(self, tmp_path):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib"])
        main(["-f", str(registry_file), "remove", "my-lib"])

        data = json.loads(registry_file.read_text())
        assert_that(data["packages"]).does_not_contain_key("my-lib")

    def test_no_command_exits(self):
        from registry import main

        with pytest.raises(SystemExit):
            main([])

    def test_add_with_branch_via_cli(self, tmp_path):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib", "--branch", "develop"])

        data = json.loads(registry_file.read_text())
        assert_that(data["packages"]["my-lib"]["branch"]).is_equal_to("develop")

    def test_add_with_single_registry_via_cli(self, tmp_path):
        from registry import main

        registry_file = tmp_path / "registry.json"
        main(["-f", str(registry_file), "add", "my-lib", "user/my-lib", "--registries", "vcpkg"])

        data = json.loads(registry_file.read_text())
        assert_that(data["packages"]["my-lib"]["registries"]).is_equal_to(["vcpkg"])
