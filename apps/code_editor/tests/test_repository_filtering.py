import os
import shutil
import tempfile

from django.test import TestCase

from code_editor.models import Project, Repository
from code_editor.services.repository_service import RepositoryService


class RepositoryFilteringTestCase(TestCase):
    """Tests that get_repository_files correctly ignores unwanted files and directories."""

    def test_get_repository_files_ignores_unwanted(self) -> None:
        # Create a temporary directory to simulate a local repository
        tmp_dir = tempfile.mkdtemp()
        try:
            # Create ignored directory and file
            os.makedirs(os.path.join(tmp_dir, 'node_modules'), exist_ok=True)
            with open(os.path.join(tmp_dir, 'node_modules', 'module.js'), 'w', encoding='utf-8') as f:
                f.write('ignored module')
            # Create binary file (contains null byte)
            with open(os.path.join(tmp_dir, 'binary.exe'), 'wb') as f:
                f.write(b'\x00\x01')
            # Create lock file
            with open(os.path.join(tmp_dir, 'package-lock.json'), 'w', encoding='utf-8') as f:
                f.write('{}')
            # Create .git directory and file
            os.makedirs(os.path.join(tmp_dir, '.git'), exist_ok=True)
            with open(os.path.join(tmp_dir, '.git', 'config'), 'w', encoding='utf-8') as f:
                f.write('[core]\n')
            # Create allowed source files
            with open(os.path.join(tmp_dir, 'main.py'), 'w', encoding='utf-8') as f:
                f.write('print("ok")')
            with open(os.path.join(tmp_dir, 'README.md'), 'w', encoding='utf-8') as f:
                f.write('# Readme')

            # Construct repository pointing to the temp directory
            project = Project.objects.create(name='FilterTest', description='')
            repo = Repository.objects.create(
                project=project,
                name='filter-repo',
                url='file://' + tmp_dir,
                branch='main',
                access_type='local',
            )
            files = RepositoryService.get_repository_files(repo)
            paths = {file['path'] for file in files}
            # Only include main.py and README.md
            self.assertIn('main.py', paths)
            self.assertIn('README.md', paths)
            # Ensure ignored files are not included
            self.assertNotIn(os.path.join('node_modules', 'module.js'), paths)
            self.assertNotIn('binary.exe', paths)
            self.assertNotIn('package-lock.json', paths)
            self.assertNotIn(os.path.join('.git', 'config'), paths)
        finally:
            shutil.rmtree(tmp_dir)

