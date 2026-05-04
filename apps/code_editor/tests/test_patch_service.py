import json
import tempfile
import unittest
from pathlib import Path

from code_editor.services.patch_service import PatchService


class PatchServiceTestCase(unittest.TestCase):
    """Tests for the PatchService helper functions."""

    def test_safe_relative_path(self):
        # Valid relative path
        self.assertTrue(PatchService._is_safe_relative_path('src/module/file.py'))
        # Absolute path should be unsafe
        self.assertFalse(PatchService._is_safe_relative_path('/etc/passwd'))
        # Path traversal should be unsafe
        self.assertFalse(PatchService._is_safe_relative_path('../secret.txt'))
        self.assertFalse(PatchService._is_safe_relative_path('dir/../secret.txt'))

    def test_apply_and_revert_patch(self):
        # Create temp directories for repository and workspace
        with tempfile.TemporaryDirectory() as repo_dir_str, tempfile.TemporaryDirectory() as workspace_dir_str:
            repo_dir = Path(repo_dir_str)
            workspace_dir = Path(workspace_dir_str)
            # Prepare original file in repository
            (repo_dir / 'foo.txt').write_text('original\n', encoding='utf-8')
            # Define patch data to modify foo.txt
            patch_data = {
                'files': {'foo.txt': 'modified\n'},
                'changed_files': ['foo.txt'],
                'diff': '',
                'status': 'proposed'
            }
            # Apply patch
            PatchService.apply_patch(patch_data, workspace_dir)
            # New content should be present in workspace
            self.assertEqual((workspace_dir / 'foo.txt').read_text(encoding='utf-8'), 'modified\n')
            # Revert patch should restore original
            PatchService.revert_patch(patch_data, workspace_dir, repository_dir=repo_dir)
            self.assertEqual((workspace_dir / 'foo.txt').read_text(encoding='utf-8'), 'original\n')

    def test_apply_unsafe_path(self):
        # Patch containing unsafe file path should raise ValueError
        patch_data = {
            'files': {'../evil.txt': 'malicious content'},
            'changed_files': ['../evil.txt'],
            'diff': '',
            'status': 'proposed'
        }
        with tempfile.TemporaryDirectory() as workspace_dir_str:
            workspace_dir = Path(workspace_dir_str)
            with self.assertRaises(ValueError):
                PatchService.apply_patch(patch_data, workspace_dir)

    def test_revert_nonexistent_file(self):
        # If original file did not exist, revert should remove file
        with tempfile.TemporaryDirectory() as repo_dir_str, tempfile.TemporaryDirectory() as workspace_dir_str:
            repo_dir = Path(repo_dir_str)
            workspace_dir = Path(workspace_dir_str)
            patch_data = {
                'files': {'newfile.txt': 'new content'},
                'changed_files': ['newfile.txt'],
                'diff': '',
                'status': 'proposed'
            }
            # Apply patch creates new file
            PatchService.apply_patch(patch_data, workspace_dir)
            self.assertTrue((workspace_dir / 'newfile.txt').exists())
            # Revert should remove file
            PatchService.revert_patch(patch_data, workspace_dir, repository_dir=repo_dir)
            self.assertFalse((workspace_dir / 'newfile.txt').exists())


if __name__ == '__main__':
    unittest.main()

