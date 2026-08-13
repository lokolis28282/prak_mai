from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import build_windows_package as package_builder


class WindowsPackageSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.source = self.root / "source.txt"
        self.source.write_text("portable", encoding="utf-8")

    def _single_source(self) -> mock._patch:
        return mock.patch.object(
            package_builder,
            "package_files",
            return_value=[(self.source, Path("source.txt"))],
        )

    def test_output_stem_directory_is_never_used_as_staging(self) -> None:
        victim = Path(self.temporary.name) / "victim"
        victim.mkdir()
        sentinel = victim / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self._single_source():
            archive = package_builder.build_windows_package(
                victim.with_suffix(".zip"), root=self.root
            )
        self.assertTrue(zipfile.is_zipfile(archive))
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertIn(f"{package_builder.RC_DIR_NAME}/source.txt", names)
        self.assertFalse(any(name.startswith("ODE/") for name in names))
        self.assertEqual(sentinel.read_text("utf-8"), "keep")

    def test_release_directory_must_be_exact_non_symlink_destination(self) -> None:
        external = Path(self.temporary.name) / "external"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "разрешён только"):
            package_builder.build_windows_package(
                Path(self.temporary.name) / "arbitrary.zip",
                root=self.root,
                release_dir=external,
            )
        expected = self.root / "release" / package_builder.RC_DIR_NAME
        expected.parent.mkdir()
        expected.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symbolic link"):
            package_builder.build_windows_package(
                Path(self.temporary.name) / "symlink-release.zip",
                root=self.root,
                release_dir=expected,
            )
        self.assertEqual(sentinel.read_text("utf-8"), "keep")

    def test_output_symlink_is_rejected_without_touching_target(self) -> None:
        target = Path(self.temporary.name) / "unrelated.bin"
        target.write_bytes(b"unrelated sentinel")
        output = Path(self.temporary.name) / "package.zip"
        output.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "symbolic link"):
            package_builder.build_windows_package(output, root=self.root)
        self.assertEqual(target.read_bytes(), b"unrelated sentinel")

    def test_alias_through_symlink_parent_is_rejected(self) -> None:
        real = Path(self.temporary.name) / "real-output"
        real.mkdir()
        linked = Path(self.temporary.name) / "linked-output"
        linked.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "Родительский.*symbolic link"):
            package_builder.build_windows_package(
                real / "canonical.zip",
                root=self.root,
                alias_path=linked / "alias.zip",
            )
        self.assertEqual(list(real.iterdir()), [])

    def test_source_symlink_outside_repository_is_rejected(self) -> None:
        external = Path(self.temporary.name) / "secret.txt"
        external.write_text("do not package", encoding="utf-8")
        linked = self.root / "linked.py"
        linked.symlink_to(external)
        with mock.patch.object(
            package_builder,
            "package_files",
            return_value=[(linked, Path("inventory/linked.py"))],
        ):
            with self.assertRaisesRegex(RuntimeError, "Symbolic link"):
                package_builder.build_windows_package(
                    Path(self.temporary.name) / "leak.zip", root=self.root
                )

    def test_source_hardlink_outside_repository_is_rejected(self) -> None:
        external = Path(self.temporary.name) / "outside.py"
        external.write_text("SECRET", encoding="utf-8")
        linked = self.root / "linked.py"
        os.link(external, linked)
        with self.assertRaisesRegex(RuntimeError, "Hard link"):
            package_builder._copy_portable_file(
                self.root, linked, Path(self.temporary.name) / "copied.py"
            )

    def test_source_swap_to_symlink_between_validation_and_open_is_rejected(self) -> None:
        external = Path(self.temporary.name) / "outside.py"
        external.write_text("SECRET", encoding="utf-8")
        target = Path(self.temporary.name) / "copied.py"
        original_open = package_builder.os.open
        swapped = False

        def swap_before_open(path: object, *args: object, **kwargs: object) -> int:
            nonlocal swapped
            selected = Path(path)
            if (
                selected.name == self.source.name
                and selected.parent.resolve() == self.root.resolve()
                and not swapped
            ):
                swapped = True
                self.source.unlink()
                self.source.symlink_to(external)
            return original_open(path, *args, **kwargs)

        with mock.patch.object(
            package_builder.os, "open", side_effect=swap_before_open
        ):
            with self.assertRaisesRegex(RuntimeError, "изменился до чтения"):
                package_builder._copy_portable_file(self.root, self.source, target)
        self.assertFalse(target.exists())
        self.assertEqual(external.read_text("utf-8"), "SECRET")

    @unittest.skipUnless(
        os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"),
        "openat/no-follow traversal is unavailable",
    )
    def test_parent_swap_to_external_symlink_after_validation_is_rejected(self) -> None:
        source_dir = self.root / "inventory"
        source_dir.mkdir()
        source = source_dir / "module.py"
        source.write_text("SAFE", encoding="utf-8")
        original_dir = self.root / "inventory-original"
        external_dir = Path(self.temporary.name) / "external"
        external_dir.mkdir()
        (external_dir / "module.py").write_text("LEAKED", encoding="utf-8")
        target = Path(self.temporary.name) / "copied.py"
        original_validate = package_builder._validated_source_with_identity
        swapped = False

        def validate_then_swap(
            root: Path, selected: Path
        ) -> tuple[Path, os.stat_result]:
            nonlocal swapped
            result = original_validate(root, selected)
            if not swapped:
                swapped = True
                source_dir.rename(original_dir)
                source_dir.symlink_to(external_dir, target_is_directory=True)
            return result

        with mock.patch.object(
            package_builder,
            "_validated_source_with_identity",
            side_effect=validate_then_swap,
        ):
            with self.assertRaisesRegex(RuntimeError, "изменился до чтения"):
                package_builder._copy_portable_file(self.root, source, target)
        self.assertFalse(target.exists())

    def test_parent_swap_is_rejected_on_windows_fallback_path(self) -> None:
        source_dir = self.root / "inventory"
        source_dir.mkdir()
        source = source_dir / "module.py"
        source.write_text("SAFE", encoding="utf-8")
        original_dir = self.root / "inventory-original"
        external_dir = Path(self.temporary.name) / "external"
        external_dir.mkdir()
        (external_dir / "module.py").write_text("LEAKED", encoding="utf-8")
        target = Path(self.temporary.name) / "copied.py"
        original_validate = package_builder._validated_source_with_identity
        swapped = False

        def validate_then_swap(
            root: Path, selected: Path
        ) -> tuple[Path, os.stat_result]:
            nonlocal swapped
            result = original_validate(root, selected)
            if not swapped:
                swapped = True
                source_dir.rename(original_dir)
                source_dir.symlink_to(external_dir, target_is_directory=True)
            return result

        with mock.patch.object(package_builder.os, "supports_dir_fd", set()), \
             mock.patch.object(
                 package_builder,
                 "_validated_source_with_identity",
                 side_effect=validate_then_swap,
             ):
            with self.assertRaisesRegex(RuntimeError, "изменился до чтения"):
                package_builder._copy_portable_file(self.root, source, target)
        self.assertFalse(target.exists())

    def test_untracked_file_in_release_tree_fails_closed(self) -> None:
        static = self.root / "static"
        static.mkdir()
        (static / "private-token.pem").write_text("PRIVATE", encoding="utf-8")
        package_builder.subprocess.run(
            ["git", "init", "-q"], cwd=self.root, check=True
        )
        with self.assertRaisesRegex(RuntimeError, "неутверждённые untracked"):
            package_builder._repository_snapshot(self.root)

    def test_secret_marker_in_selected_source_fails_closed(self) -> None:
        selected = self.root / "config.py"
        fake_prefix = b"sk-" + b"proj-"
        selected.write_bytes(b"API_KEY = '" + fake_prefix + b"not-a-release-value'")
        with self.assertRaisesRegex(RuntimeError, "Обнаружен секрет"):
            package_builder._copy_portable_file(
                self.root,
                selected,
                Path(self.temporary.name) / "copied.py",
            )

    def test_private_transfer_readme_is_explicitly_excluded(self) -> None:
        selected = {
            relative.as_posix()
            for _source, relative in package_builder.package_files()
        }
        self.assertFalse(
            any(name.startswith("PRIVATE_WINDOWS_TRANSFER_") for name in selected)
        )

    def test_failed_zip_write_preserves_previous_archive(self) -> None:
        output = Path(self.temporary.name) / "known-good.zip"
        known_good = b"known good archive sentinel"
        output.write_bytes(known_good)
        with self._single_source(), mock.patch.object(
            zipfile.ZipFile, "write", side_effect=RuntimeError("simulated write failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
                package_builder.build_windows_package(output, root=self.root)
        self.assertEqual(output.read_bytes(), known_good)

    def test_directory_fsync_failure_does_not_report_false_publish_failure(self) -> None:
        output = Path(self.temporary.name) / "published.zip"
        original_open = package_builder.os.open

        def fail_only_for_directory(path: object, *args: object, **kwargs: object) -> int:
            if Path(path) == output.parent:
                raise PermissionError("directory open")
            return original_open(path, *args, **kwargs)

        with self._single_source(), mock.patch.object(
            package_builder.os, "open", side_effect=fail_only_for_directory
        ):
            result = package_builder.build_windows_package(output, root=self.root)
        self.assertEqual(result, output)
        self.assertTrue(zipfile.is_zipfile(output))

    def test_double_release_directory_failure_preserves_previous_recovery(self) -> None:
        staged = Path(self.temporary.name) / "staged"
        staged.mkdir()
        (staged / "new.txt").write_text("new", encoding="utf-8")
        destination = self.root / "release" / package_builder.RC_DIR_NAME
        destination.mkdir(parents=True)
        (destination / "OLD_SENTINEL").write_text("old", encoding="utf-8")
        original_replace = package_builder.os.replace
        calls = 0

        def fail_publish_and_rollback(source: object, target: object) -> None:
            nonlocal calls
            calls += 1
            if calls in {2, 3}:
                raise PermissionError(f"simulated replace failure {calls}")
            original_replace(source, target)

        with mock.patch.object(
            package_builder.os, "replace", side_effect=fail_publish_and_rollback
        ):
            with self.assertRaisesRegex(RuntimeError, "сохранён для восстановления"):
                package_builder._publish_release_directory(staged, destination)
        recovery = destination.with_name(f".{destination.name}.previous")
        self.assertFalse(destination.exists())
        self.assertEqual((recovery / "OLD_SENTINEL").read_text("utf-8"), "old")
        self.assertFalse(any(destination.parent.glob(".ode_publish_*")))

    def test_artifact_set_rolls_back_when_canonical_zip_publish_fails(self) -> None:
        release_root = self.root / "release"
        release_dir = release_root / package_builder.RC_DIR_NAME
        release_dir.mkdir(parents=True)
        (release_dir / "OLD_DIR").write_text("old directory", encoding="utf-8")
        output = release_root / package_builder.PACKAGE_NAME
        alias = release_root / package_builder.RC_PACKAGE_NAME
        output.write_bytes(b"old canonical")
        alias.write_bytes(b"old alias")
        output_sidecar = package_builder._sha256_sidecar_path(output)
        alias_sidecar = package_builder._sha256_sidecar_path(alias)
        output_sidecar.write_text("old canonical sum", encoding="ascii")
        alias_sidecar.write_text("old alias sum", encoding="ascii")
        output_recovery = output.with_name(f".{output.name}.previous")
        original_replace = package_builder.os.replace
        saw_consistent_precommit = False

        def fail_new_canonical(source: object, target: object) -> None:
            nonlocal saw_consistent_precommit
            selected_source = Path(source)
            selected_target = Path(target)
            if selected_target == output and selected_source != output_recovery:
                saw_consistent_precommit = (
                    zipfile.is_zipfile(alias)
                    and (release_dir / "source.txt").is_file()
                    and output_sidecar.read_text("ascii").endswith(
                        f"  {output.name}\n"
                    )
                    and alias_sidecar.read_text("ascii").endswith(
                        f"  {alias.name}\n"
                    )
                )
                raise PermissionError("simulated canonical publish failure")
            original_replace(source, target)

        with self._single_source(), mock.patch.object(
            package_builder.os, "replace", side_effect=fail_new_canonical
        ):
            with self.assertRaisesRegex(PermissionError, "canonical publish"):
                package_builder.build_windows_package(
                    output,
                    root=self.root,
                    release_dir=release_dir,
                    alias_path=alias,
                    write_sha256_sidecars=True,
                )
        self.assertTrue(saw_consistent_precommit)
        self.assertEqual(output.read_bytes(), b"old canonical")
        self.assertEqual(alias.read_bytes(), b"old alias")
        self.assertEqual(output_sidecar.read_text("ascii"), "old canonical sum")
        self.assertEqual(alias_sidecar.read_text("ascii"), "old alias sum")
        self.assertEqual((release_dir / "OLD_DIR").read_text("utf-8"), "old directory")

    def test_external_sha256_sidecars_are_atomic_and_match_each_archive(self) -> None:
        release_root = self.root / "release"
        release_dir = release_root / package_builder.RC_DIR_NAME
        output = release_root / package_builder.PACKAGE_NAME
        alias = release_root / package_builder.RC_PACKAGE_NAME
        with self._single_source():
            package_builder.build_windows_package(
                output,
                root=self.root,
                release_dir=release_dir,
                alias_path=alias,
                write_sha256_sidecars=True,
            )
        self.assertEqual(output.read_bytes(), alias.read_bytes())
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        for archive in (output, alias):
            sidecar = package_builder._sha256_sidecar_path(archive)
            self.assertEqual(
                sidecar.read_text("ascii"), f"{digest}  {archive.name}\n"
            )

    def test_build_lock_rejects_concurrent_publisher(self) -> None:
        release_root = self.root / "release"
        release_root.mkdir()
        lock = release_root / package_builder.BUILD_LOCK_NAME
        lock.write_text("pid=other\n", encoding="ascii")
        with self._single_source():
            with self.assertRaisesRegex(RuntimeError, "уже выполняется"):
                package_builder.build_windows_package(
                    release_root / "concurrent.zip", root=self.root
                )
        self.assertEqual(lock.read_text("ascii"), "pid=other\n")

    def test_stale_failed_recovery_blocks_before_any_publication(self) -> None:
        release_root = self.root / "release"
        release_dir = release_root / package_builder.RC_DIR_NAME
        release_dir.mkdir(parents=True)
        (release_dir / "OLD_DIR").write_text("old", encoding="utf-8")
        failed = release_dir.with_name(f".{release_dir.name}.failed")
        failed.mkdir()
        output = release_root / package_builder.PACKAGE_NAME
        output.write_bytes(b"old canonical")
        with self._single_source():
            with self.assertRaisesRegex(RuntimeError, "recovery-артефакты"):
                package_builder.build_windows_package(
                    output, root=self.root, release_dir=release_dir
                )
        self.assertEqual(output.read_bytes(), b"old canonical")
        self.assertEqual((release_dir / "OLD_DIR").read_text("utf-8"), "old")

    def test_complete_interrupted_set_is_recovered_before_new_build(self) -> None:
        release_root = self.root / "release"
        release_dir = release_root / package_builder.RC_DIR_NAME
        output = release_root / package_builder.PACKAGE_NAME
        alias = release_root / package_builder.RC_PACKAGE_NAME
        archives = [output, alias]
        sidecars = [package_builder._sha256_sidecar_path(path) for path in archives]
        destinations = archives + sidecars + [release_dir]
        release_root.mkdir()
        for destination in destinations:
            previous, _failed = package_builder._recovery_paths(destination)
            if destination == release_dir:
                destination.mkdir()
                previous.mkdir()
                (destination / "NEW").write_text("interrupted", encoding="utf-8")
                (previous / "OLD").write_text("recover", encoding="utf-8")
            else:
                destination.write_bytes(b"interrupted-new")
                previous.write_bytes(b"recover-old")

        def stop_after_recovery(*_args: object, **_kwargs: object) -> list[tuple[Path, Path]]:
            raise RuntimeError("stop after recovery")

        with mock.patch.object(
            package_builder,
            "package_files",
            side_effect=stop_after_recovery,
        ):
            with self.assertRaisesRegex(RuntimeError, "stop after recovery"):
                package_builder.build_windows_package(
                    output,
                    root=self.root,
                    release_dir=release_dir,
                    alias_path=alias,
                    write_sha256_sidecars=True,
                )
        for destination in archives + sidecars:
            self.assertEqual(destination.read_bytes(), b"recover-old")
            self.assertFalse(package_builder._recovery_paths(destination)[0].exists())
        self.assertTrue((release_dir / "OLD").is_file())
        self.assertFalse((release_dir / "NEW").exists())
        self.assertFalse(package_builder._recovery_paths(release_dir)[0].exists())

    def test_committed_cleanup_marker_prevents_next_run_rollback(self) -> None:
        release_root = self.root / "release"
        release_dir = release_root / package_builder.RC_DIR_NAME
        output = release_root / package_builder.PACKAGE_NAME
        alias = release_root / package_builder.RC_PACKAGE_NAME
        archives = [output, alias]
        sidecars = [package_builder._sha256_sidecar_path(path) for path in archives]
        destinations = archives + sidecars + [release_dir]

        with self._single_source():
            package_builder.build_windows_package(
                output,
                root=self.root,
                release_dir=release_dir,
                alias_path=alias,
                write_sha256_sidecars=True,
            )
        self.source.write_text("new committed payload", encoding="utf-8")
        original_remove = package_builder._remove_path

        def block_previous_cleanup(path: Path) -> None:
            if path.name.endswith(".previous"):
                raise PermissionError("simulated antivirus lock")
            original_remove(path)

        with self._single_source(), mock.patch.object(
            package_builder,
            "_remove_path",
            side_effect=block_previous_cleanup,
        ):
            package_builder.build_windows_package(
                output,
                root=self.root,
                release_dir=release_dir,
                alias_path=alias,
                write_sha256_sidecars=True,
            )

        committed_digest = hashlib.sha256(output.read_bytes()).hexdigest()
        marker = package_builder._committed_marker_path(release_root)
        self.assertTrue(marker.is_file())
        self.assertTrue(
            all(package_builder._recovery_paths(path)[0].exists() for path in destinations)
        )
        self.assertEqual((release_dir / "source.txt").read_text("utf-8"), "new committed payload")

        with mock.patch.object(
            package_builder,
            "package_files",
            side_effect=RuntimeError("simulated next source failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "next source failure"):
                package_builder.build_windows_package(
                    output,
                    root=self.root,
                    release_dir=release_dir,
                    alias_path=alias,
                    write_sha256_sidecars=True,
                )

        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), committed_digest)
        self.assertEqual(hashlib.sha256(alias.read_bytes()).hexdigest(), committed_digest)
        self.assertEqual((release_dir / "source.txt").read_text("utf-8"), "new committed payload")
        self.assertFalse(marker.exists())
        self.assertTrue(
            all(not package_builder._recovery_paths(path)[0].exists() for path in destinations)
        )

    def test_interrupt_after_marker_install_never_rolls_committed_set_back(self) -> None:
        release_root = self.root / "release"
        release_dir = release_root / package_builder.RC_DIR_NAME
        output = release_root / package_builder.PACKAGE_NAME
        alias = release_root / package_builder.RC_PACKAGE_NAME
        archives = [output, alias]
        sidecars = [package_builder._sha256_sidecar_path(path) for path in archives]
        destinations = archives + sidecars + [release_dir]

        with self._single_source():
            package_builder.build_windows_package(
                output,
                root=self.root,
                release_dir=release_dir,
                alias_path=alias,
                write_sha256_sidecars=True,
            )
        old_digest = hashlib.sha256(output.read_bytes()).hexdigest()
        self.source.write_text("new after marker interrupt", encoding="utf-8")
        marker = package_builder._committed_marker_path(release_root)
        original_fsync_directory = package_builder._fsync_directory_best_effort
        interrupted = False

        def interrupt_once_after_marker(path: Path) -> None:
            nonlocal interrupted
            if marker.exists() and not interrupted:
                interrupted = True
                raise KeyboardInterrupt("simulated post-marker interruption")
            original_fsync_directory(path)

        with self._single_source(), mock.patch.object(
            package_builder,
            "_fsync_directory_best_effort",
            side_effect=interrupt_once_after_marker,
        ):
            with self.assertRaisesRegex(KeyboardInterrupt, "post-marker"):
                package_builder.build_windows_package(
                    output,
                    root=self.root,
                    release_dir=release_dir,
                    alias_path=alias,
                    write_sha256_sidecars=True,
                )

        committed_digest = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertNotEqual(committed_digest, old_digest)
        self.assertEqual(hashlib.sha256(alias.read_bytes()).hexdigest(), committed_digest)
        self.assertEqual(
            (release_dir / "source.txt").read_text("utf-8"),
            "new after marker interrupt",
        )
        self.assertTrue(marker.is_file())
        self.assertTrue(
            all(package_builder._recovery_paths(path)[0].exists() for path in destinations)
        )

        self.source.write_text("next build completed", encoding="utf-8")
        with self._single_source():
            package_builder.build_windows_package(
                output,
                root=self.root,
                release_dir=release_dir,
                alias_path=alias,
                write_sha256_sidecars=True,
            )
        next_digest = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertNotEqual(next_digest, old_digest)
        self.assertNotEqual(next_digest, committed_digest)
        self.assertEqual(hashlib.sha256(alias.read_bytes()).hexdigest(), next_digest)
        self.assertEqual(
            (release_dir / "source.txt").read_text("utf-8"),
            "next build completed",
        )
        self.assertFalse(marker.exists())
        self.assertTrue(
            all(not package_builder._recovery_paths(path)[0].exists() for path in destinations)
        )

    def test_partial_interrupted_set_fails_closed(self) -> None:
        release_root = self.root / "release"
        output = release_root / package_builder.PACKAGE_NAME
        release_root.mkdir()
        output.write_bytes(b"new")
        output_previous = package_builder._recovery_paths(output)[0]
        output_previous.write_bytes(b"old")
        with self._single_source():
            with self.assertRaisesRegex(RuntimeError, "Неполный recovery-набор"):
                package_builder.build_windows_package(
                    output,
                    root=self.root,
                    alias_path=release_root / package_builder.RC_PACKAGE_NAME,
                    write_sha256_sidecars=True,
                )
        self.assertEqual(output.read_bytes(), b"new")
        self.assertEqual(output_previous.read_bytes(), b"old")

    def test_main_publishes_default_alias_and_external_sha256_sidecars(self) -> None:
        expected_output = package_builder.ROOT / "release" / package_builder.PACKAGE_NAME
        expected_alias = package_builder.ROOT / "release" / package_builder.RC_PACKAGE_NAME
        with mock.patch.object(sys, "argv", ["build_windows_package.py"]), \
             mock.patch.object(
                 package_builder,
                 "build_windows_package",
                 return_value=expected_output,
             ) as build, \
             mock.patch("builtins.print"):
            self.assertEqual(package_builder.main(), 0)
        build.assert_called_once_with(
            expected_output,
            release_dir=package_builder.ROOT / "release" / package_builder.RC_DIR_NAME,
            alias_path=expected_alias,
            write_sha256_sidecars=True,
        )

    def test_archive_cannot_be_published_inside_replaced_release_directory(self) -> None:
        release_dir = self.root / "release" / package_builder.RC_DIR_NAME
        nested_output = release_dir / "nested.zip"
        with self.assertRaisesRegex(RuntimeError, "внутри release-каталога"):
            package_builder.build_windows_package(
                nested_output, root=self.root, release_dir=release_dir
            )
        self.assertFalse(nested_output.exists())


if __name__ == "__main__":
    unittest.main()
