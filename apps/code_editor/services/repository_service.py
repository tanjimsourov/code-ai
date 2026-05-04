import os
import hashlib
import mimetypes
import datetime
from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db import transaction
from django.core.files import File
from django.db.models import Sum
from django.db.models.query import QuerySet
from ..models import Project, Repository, IndexedFile, CodeChunk, IngestionJob
from ..exceptions import InvalidRequestException, ProviderNotAvailableException
from ..utils import extract_code_language


class RepositoryService:
    """Service for managing repositories, syncing and indexing.

    This service centralises logic for creating projects, adding
    repositories, synchronising remote repositories to a local working
    directory and gathering files for ingestion.  Remote clone/fetch
    operations are implemented using the git CLI with strict timeouts and a
    sanitized environment.  Local repositories (access_type 'local')
    continue to be read directly from the filesystem.
    """
    
    @staticmethod
    def create_project(name: str, description: str = '', owner: Any = None) -> Project:
        """Create a new local project. The owner argument is ignored."""
        name = name.strip() if name else ''
        description = description.strip() if description else ''
        project = Project.objects.create(
            name=name,
            description=description,
            is_active=True
        )
        return project

    @staticmethod
    def add_repository(project: Project, name: str, url: str, access_type: str = 'public', branch: str = 'main') -> Repository:
        """Add a repository to a project"""
        return Repository.objects.create(
            project=project,
            name=name.strip(),
            url=url.strip(),
            access_type=access_type,
            branch=branch
        )

    # ------------------------------------------------------------------
    # Remote repository support
    # ------------------------------------------------------------------

    @staticmethod
    def _get_base_clone_dir() -> str:
        """Determine the base directory for storing cloned repositories.

        The directory is taken from the ``CODE_EDITOR_REPOSITORY_STORAGE_ROOT``
        environment variable or the Django settings if defined.  If
        unspecified, a default under ``/tmp/code_editor_repositories`` is used.  The directory is
        created if it does not exist.
        """
        from django.conf import settings  # deferred import to avoid early Django setup
        # Prefer the new storage setting; fall back to legacy name for backward compatibility
        base_dir = (
            os.getenv('CODE_EDITOR_REPOSITORY_STORAGE_ROOT')
            or getattr(settings, 'CODE_EDITOR_REPOSITORY_STORAGE_ROOT', None)
            or os.getenv('CODE_EDITOR_REPOSITORY_ROOT')
            or getattr(settings, 'CODE_EDITOR_REPOSITORY_ROOT', None)
        )
        if not base_dir:
            base_dir = '/tmp/code_editor_repositories'
        base_dir = os.path.abspath(base_dir)
        os.makedirs(base_dir, exist_ok=True)
        return base_dir

    @staticmethod
    def _derive_storage_path(repository: Repository) -> str:
        """Derive a filesystem path to clone or fetch a repository.

        Uses the base clone directory along with the repository's ID and
        slugified name to ensure uniqueness.  This function does not
        create the directory, it only computes the path.
        """
        base = RepositoryService._get_base_clone_dir()
        safe_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in (repository.name or ''))
        return os.path.join(base, f"repo_{repository.id}_{safe_name}")

    @staticmethod
    def _inject_credentials(url: str, credential_key: str) -> str:
        """Inject credentials into a repository URL for private access.

        For private repositories, a credential key may be provided which
        references an environment variable containing a token.  When a
        token is available it is inserted before the host component of
        the URL (e.g. ``https://<token>@github.com/org/repo.git``).  The
        token is not persisted anywhere in the repository model.
        """
        if not credential_key:
            return url
        token = os.getenv(credential_key)
        if not token:
            return url
        try:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(url)
            if not parts.scheme or not parts.netloc:
                return url
            if parts.scheme not in ('https', 'http'):
                return url
            if '@' in parts.netloc:
                return url
            new_netloc = f"{token}@{parts.netloc}"
            return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))
        except Exception:
            return url

    @staticmethod
    def sync_repository(repository: Repository, branch: Optional[str] = None, dry_run: bool = False) -> None:
        """Synchronise a repository to the local filesystem.

        If the repository is local (``access_type == 'local'``) this method
        updates the sync metadata without performing any network operations.
        For remote repositories the method clones the repository if it
        hasn't been cloned before, or fetches and checks out the desired
        branch if it already exists.  All git commands are executed with
        strict timeouts and sanitized environment variables.  The current
        commit SHA is recorded on success.  Errors during sync are
        captured and stored in ``sync_error``.
        """
        import subprocess
        from django.utils import timezone  # deferred import
        # For local repositories, simply mark as synced
        if repository.access_type == 'local':
            if not dry_run:
                repository.sync_status = 'synced'
                repository.last_synced_at = timezone.now()
                repository.commit_sha = ''
                repository.sync_error = ''
                repository.save(update_fields=['sync_status', 'last_synced_at', 'commit_sha', 'sync_error'])
            return
        # Only support git for now
        if repository.vcs_provider not in ('git', 'unknown'):
            if not dry_run:
                repository.sync_status = 'failed'
                repository.sync_error = f"Unsupported VCS provider: {repository.vcs_provider}"
                repository.save(update_fields=['sync_status', 'sync_error'])
            return
        branch_to_use = branch or repository.branch or 'main'
        storage_path = repository.storage_path or RepositoryService._derive_storage_path(repository)
        base_dir = RepositoryService._get_base_clone_dir()
        abs_storage = os.path.abspath(storage_path)
        if not abs_storage.startswith(os.path.abspath(base_dir)):
            if not dry_run:
                repository.sync_status = 'failed'
                repository.sync_error = 'Invalid storage path'
                repository.save(update_fields=['sync_status', 'sync_error'])
            return
        # Sanitized environment for git commands
        env = {
            'GIT_TERMINAL_PROMPT': '0',
            'PATH': os.getenv('PATH', ''),
        }
        for key, value in os.environ.items():
            if key.startswith('CODE_EDITOR_'):
                env[key] = value
        git_dir = os.path.join(abs_storage, '.git')
        repo_url = RepositoryService._inject_credentials(repository.url, repository.credential_key or '')
        try:
            if not os.path.isdir(git_dir):
                if dry_run:
                    repository.sync_status = 'pending'
                    repository.sync_error = ''
                    repository.save(update_fields=['sync_status', 'sync_error'])
                    return
                os.makedirs(abs_storage, exist_ok=True)
                repository.sync_status = 'syncing'
                repository.sync_error = ''
                repository.save(update_fields=['sync_status', 'sync_error'])
                subprocess.run(
                    ['git', 'clone', '--depth', '1', '--branch', branch_to_use, repo_url, abs_storage],
                    cwd=base_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    check=True,
                    text=True,
                )
            else:
                if dry_run:
                    repository.sync_status = 'synced'
                    repository.sync_error = ''
                    repository.save(update_fields=['sync_status', 'sync_error'])
                    return
                repository.sync_status = 'syncing'
                repository.sync_error = ''
                repository.save(update_fields=['sync_status', 'sync_error'])
                subprocess.run(
                    ['git', 'fetch', '--all', '--prune'],
                    cwd=abs_storage,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                    check=True,
                    text=True,
                )
                subprocess.run(
                    ['git', 'checkout', branch_to_use],
                    cwd=abs_storage,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=True,
                    text=True,
                )
                subprocess.run(
                    ['git', 'pull', '--ff-only'],
                    cwd=abs_storage,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                    check=True,
                    text=True,
                )
            # After clone or fetch, record the current commit SHA
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=abs_storage,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=True,
                text=True,
            )
            commit_sha = result.stdout.strip()
            if not dry_run:
                repository.commit_sha = commit_sha
                repository.last_synced_at = timezone.now()
                repository.storage_path = abs_storage
                repository.sync_status = 'synced'
                repository.sync_error = ''
                repository.save(update_fields=['commit_sha', 'last_synced_at', 'storage_path', 'sync_status', 'sync_error'])
        except subprocess.CalledProcessError as exc:
            err_msg = exc.stderr.strip().split('\n')[-1] if exc.stderr else str(exc)
            if not dry_run:
                repository.sync_status = 'failed'
                repository.sync_error = f"Git error: {err_msg}"
                repository.save(update_fields=['sync_status', 'sync_error'])
            raise
        except Exception as exc:
            if not dry_run:
                repository.sync_status = 'failed'
                repository.sync_error = str(exc)
                repository.save(update_fields=['sync_status', 'sync_error'])
            raise
    
    @staticmethod
    def start_ingestion_job(repository: Repository) -> IngestionJob:
        """Start a background ingestion job for a repository"""
        # Cancel any pending jobs for this repository
        IngestionJob.objects.filter(
            repository=repository,
            status__in=['pending', 'running']
        ).update(status='cancelled')
        
        # Create a unique job identifier for the ingestion job. The job_id is used to
        # correlate the Celery task and the database record. Without a job_id, the
        # IngestionJob model would violate its non-null constraint.
        import uuid
        job_uuid = uuid.uuid4().hex
        job = IngestionJob.objects.create(
            repository=repository,
            job_id=job_uuid,
            status='pending'
        )

        # Trigger the asynchronous ingestion task if Celery is available. In this
        # environment the task may be a no-op; if Celery is not configured,
        # ingestion will be invoked synchronously via IngestionService.
        try:
            from ..tasks import ingest_repository_task  # type: ignore
            ingest_repository_task.delay(job_uuid)  # type: ignore
        except Exception:
            # If tasks or Celery is unavailable, proceed without enqueueing
            pass

        return job
    
    @staticmethod
    def get_repository_files(repository: Repository) -> List[Dict[str, Any]]:
        """
        Get a list of files in the repository suitable for indexing.

        For local repositories (access_type='local'), this scans the directory
        specified by the repository URL (after stripping the file:// scheme),
        respecting `.gitignore` patterns, skipping binary files, and only
        returning source code files based on a whitelist of file extensions.

        For remote repositories, this currently returns an empty list. A future
        implementation could clone the repository using git and perform the same
        processing on the cloned working tree.
        """
        # Determine the base path depending on repository type.  For remote
        # repositories perform a sync to ensure the working tree is available.
        if repository.access_type != 'local':
            try:
                RepositoryService.sync_repository(repository)
            except Exception:
                return []
            base_path = repository.storage_path or RepositoryService._derive_storage_path(repository)
        else:
            base_path = repository.url.replace('file://', '')
        if not base_path:
            return []
        base_path = os.path.abspath(base_path)
        if not os.path.exists(base_path) or not os.path.isdir(base_path):
            return []
        # Build ignore patterns from configuration and .gitignore
        ignore_patterns: List[str] = []
        extra_patterns = os.getenv('CODE_EDITOR_IGNORE_PATTERNS', '')
        if extra_patterns:
            for pattern in extra_patterns.split(','):
                pattern = pattern.strip()
                if pattern:
                    ignore_patterns.append(pattern)
        gitignore_path = os.path.join(base_path, '.gitignore')
        if os.path.isfile(gitignore_path):
            try:
                with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as gitignore_file:
                    for line in gitignore_file:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        ignore_patterns.append(line)
            except Exception:
                pass
        def is_ignored(relative_path: str) -> bool:
            rel = relative_path.replace('\\', '/')
            for pattern in ignore_patterns:
                if pattern.startswith('*.'):
                    suffix = pattern[1:]
                    if rel.endswith(suffix):
                        return True
                if pattern.endswith('/') and rel.startswith(pattern.rstrip('/')):
                    return True
                if '*' in pattern:
                    if pattern.startswith('*') and rel.endswith(pattern.lstrip('*')):
                        return True
                    if pattern.endswith('*') and rel.startswith(pattern.rstrip('*')):
                        return True
                if pattern == rel:
                    return True
            return False
        # File extensions that should always be considered for indexing.  This list includes
        # a broad range of programming, markup and configuration languages.  Extensionless
        # files such as ``Dockerfile`` and ``Makefile`` are handled via ``allowed_filenames``.
        allowed_extensions = (
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.cs', '.php', '.rb', '.go', '.rs',
            '.swift', '.kt', '.scala', '.r', '.sql', '.sh', '.html', '.css', '.scss', '.sass', '.less', '.xml',
            '.json', '.yaml', '.yml', '.toml', '.ini', '.md', '.txt', '.dockerfile'
        )
        # Explicit filenames (case sensitive) that should be indexed even though they lack
        # extensions.  These are common build and config files that are important for
        # understanding the repository structure and runtime environment.
        allowed_filenames = {
            'Dockerfile', 'Makefile', 'Procfile',
            'dockerfile', 'makefile', 'procfile',
        }
        # Patterns for additional config files that may end with various extensions or
        # prefixes.  Patterns should be lowercased for matching.  Examples include
        # ``hardhat.config.js``, ``foundry.toml``, ``truffle-config.ts``, etc.
        allowed_name_prefixes = (
            'hardhat.config', 'foundry', 'truffle-config', 'foundry.config',
        )
        ignored_dirs = {'.git', 'node_modules', 'venv', '__pycache__', 'dist', 'build', 'coverage', '.hg', '.svn'}
        ignored_extensions = (
            '.exe', '.dll', '.so', '.bin', '.class', '.jar', '.war', '.apk',
            '.log', '.lock', '.pyc', '.pyo', '.o', '.a', '.dylib', '.db', '.sqlite',
            '.mp3', '.mp4', '.avi', '.mov', '.jpg', '.jpeg', '.png', '.gif', '.bmp',
            '.ico', '.zip', '.tar', '.gz', '.tgz', '.rar', '.7z', '.pdf', '.doc', '.docx',
            '.xls', '.xlsx'
        )
        try:
            max_file_size = int(os.getenv('CODE_EDITOR_MAX_FILE_SIZE', '500000'))
        except Exception:
            max_file_size = 500000
        max_repo_size = None
        try:
            max_repo_size_val = os.getenv('CODE_EDITOR_MAX_REPOSITORY_SIZE')
            if max_repo_size_val:
                max_repo_size = int(max_repo_size_val)
        except Exception:
            max_repo_size = None
        max_indexed_files = None
        try:
            max_files_val = os.getenv('CODE_EDITOR_MAX_INDEXED_FILES')
            if max_files_val:
                max_indexed_files = int(max_files_val)
        except Exception:
            max_indexed_files = None
        total_repo_bytes = 0
        file_list: List[Dict[str, Any]] = []
        for root, dirs, filenames in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not is_ignored(os.path.relpath(os.path.join(root, d), base_path))]
            for filename in filenames:
                rel_path = os.path.relpath(os.path.join(root, filename), base_path)
                lower_name = filename.lower()
                if is_ignored(rel_path):
                    continue
                if lower_name.endswith(ignored_extensions):
                    continue
                # Determine whether this file should be considered for indexing.  Files are
                # accepted if they match a supported extension, are explicitly listed in
                # ``allowed_filenames``, or start with any pattern in ``allowed_name_prefixes``.
                allowed_names = {name.lower() for name in allowed_filenames}
                name_matches_prefix = any(lower_name.startswith(prefix) for prefix in allowed_name_prefixes)
                has_allowed_extension = lower_name.endswith(allowed_extensions)
                if not has_allowed_extension and lower_name not in allowed_names and not name_matches_prefix:
                    continue
                if lower_name in {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'}:
                    continue
                full_path = os.path.join(root, filename)
                try:
                    canonical = os.path.abspath(full_path)
                    if not canonical.startswith(base_path):
                        continue
                except Exception:
                    continue
                try:
                    with open(full_path, 'rb') as bf:
                        raw = bf.read(1024)
                        if b'\x00' in raw:
                            continue
                except Exception:
                    continue
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception:
                    continue
                size_bytes = len(content.encode('utf-8'))
                if size_bytes > max_file_size:
                    continue
                total_repo_bytes += size_bytes
                if max_repo_size and total_repo_bytes > max_repo_size:
                    break
                try:
                    last_mod = timezone.make_aware(
                        timezone.datetime.fromtimestamp(os.path.getmtime(full_path))
                    )
                except Exception:
                    last_mod = timezone.now()
                file_list.append({
                    'path': rel_path,
                    'content': content,
                    'size': size_bytes,
                    'last_modified': last_mod,
                    'language': extract_code_language(filename, content),
                })
            if max_repo_size and total_repo_bytes > max_repo_size:
                break
        if max_indexed_files and len(file_list) > max_indexed_files:
            file_list = file_list[:max_indexed_files]
        return file_list
    
    @staticmethod
    def should_reindex(repository: Repository) -> bool:
        """Check if repository should be reindexed"""
        if repository.indexing_status == 'indexing':
            return False
        # Reindex if never indexed or if indexed more than 24 hours ago.
        # In some stub environments, ``last_indexed_at`` may be a descriptor
        # rather than a datetime instance; treat such cases as never indexed.
        if (not repository.last_indexed_at or
                not isinstance(repository.last_indexed_at, datetime.datetime)):
            return True
        time_since_index = timezone.now() - repository.last_indexed_at
        return time_since_index.total_seconds() > 24 * 3600  # 24 hours
    
    @staticmethod
    def get_ingestion_status(job_id: str) -> Optional[IngestionJob]:
        """Get status of an ingestion job"""
        try:
            return IngestionJob.objects.get(job_id=job_id)
        except IngestionJob.DoesNotExist:
            return None
    
    @staticmethod
    def list_projects(owner: Optional[Any] = None, include_inactive: bool = False) -> QuerySet[Project]:
        """List projects for the local single-user backend."""
        projects = Project.objects.all()
        if not include_inactive:
            projects = projects.filter(is_active=True)
        return projects.order_by('-created_at')

    # NOTE: create_project is defined above with an optional owner argument. The second
    # definition has been removed to avoid confusion. If you need to create a project
    # without specifying an owner, call the first create_project and omit the owner parameter.
    
    @staticmethod
    def get_project_stats(project: Project) -> Dict[str, Any]:
        """Get statistics for a project"""
        repositories = project.repositories.all()
        total_files = 0
        total_size = 0
        languages: Dict[str, int] = {}

        for repo in repositories:
            files = repo.indexed_files.all()
            total_files += files.count()
            total_size += files.aggregate(total_size=Sum('file_size'))['total_size'] or 0
            # Count languages
            for file in files:
                lang = file.language or 'unknown'
                languages[lang] = languages.get(lang, 0) + 1

        # Determine most recent indexing time across repositories. Skip any
        # values that are not datetime instances to avoid comparison errors.
        index_dates = [
            repo.last_indexed_at
            for repo in repositories
            if repo.last_indexed_at and isinstance(repo.last_indexed_at, datetime.datetime)
        ]
        last_indexed = max(index_dates) if index_dates else None

        return {
            'repository_count': repositories.count(),
            'total_files': total_files,
            'total_size_bytes': total_size,
            'languages': dict(sorted(languages.items(), key=lambda x: x[1], reverse=True)),
            'last_indexed': last_indexed,
        }
