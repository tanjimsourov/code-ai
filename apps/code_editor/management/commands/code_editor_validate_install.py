"""Validate the code editor installation.

This management command performs a series of lightweight checks to
validate that the code editor is installed correctly.  It compiles all
Python files under the package to bytecode, invokes the built-in smoke
check and ensures that the migration graph has a single leaf node.
These checks are safe to run in production environments.

Example usage::

    python manage.py code_editor_validate_install

You may pass ``--dry-run`` to print the actions without executing them.
"""

import compileall
from django.core.management.base import BaseCommand, CommandError
from django.urls import get_resolver, resolve


class Command(BaseCommand):
    help = 'Perform installation validation checks for the code editor.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run', default=False,
            help='Show checks without executing them.'
        )
        parser.add_argument(
            '--check-providers', action='store_true', dest='check_providers', default=False,
            help='Perform health checks on configured providers (may make network calls).'
        )

    def handle(self, *args, **options) -> None:
        dry_run = bool(options.get('dry_run'))
        check_providers = bool(options.get('check_providers'))
        if dry_run:
            self.stdout.write('Would run compileall on code_editor package')
            self.stdout.write('Would run code_editor_smoke_check')
            self.stdout.write('Would verify migration graph leaves')
            return

        # Compile all python files to ensure they are syntactically valid
        self.stdout.write('Compiling code_editor package...')
        ok = compileall.compile_dir('apps/code_editor', quiet=1, force=False)
        if not ok:
            raise CommandError('Compilation failures detected')
        self.stdout.write(self.style.SUCCESS('Compilation succeeded'))

        # Import core modules to ensure they can be loaded
        self.stdout.write('Importing core modules...')
        modules = [
            'code_editor.models',
            'code_editor.views',
            'code_editor.api',
            'code_editor.api.urls',
            'code_editor.services',
            'code_editor.tasks',
            'code_editor.workflows',
            'code_editor.admin',
        ]
        import_errors: list[tuple[str, Exception]] = []
        for mod in modules:
            try:
                __import__(mod)
            except Exception as exc:
                import_errors.append((mod, exc))
        if import_errors:
            for mod, exc in import_errors:
                self.stdout.write(self.style.ERROR(f'Failed to import {mod}: {exc}'))
            raise CommandError('Core module imports failed')
        self.stdout.write(self.style.SUCCESS('All core modules imported successfully'))

        # Run smoke check command
        self.stdout.write('Running smoke check...')
        try:
            from django.core.management import call_command
            call_command('code_editor_smoke_check')
        except Exception as exc:
            raise CommandError(f'Smoke check failed: {exc}') from exc

        # Run model registry check (safe, no external calls)
        self.stdout.write('Validating model registry...')
        try:
            from django.core.management import call_command
            call_command('show_code_editor_model_registry')
        except Exception as exc:
            raise CommandError(f'Model registry check failed: {exc}') from exc

        # Verify there is only one migration leaf node
        try:
            from django.db import connections
            from django.db.migrations.executor import MigrationExecutor
            connection = connections['default']
            executor = MigrationExecutor(connection)
            leaf_nodes = executor.loader.graph.leaf_nodes()
            leaves = [name for (app_label, name) in leaf_nodes if app_label == 'code_editor']
            if len(leaves) > 1:
                raise CommandError(f'Multiple migration leaf nodes detected: {", ".join(leaves)}')
            else:
                self.stdout.write(self.style.SUCCESS('Single migration leaf node detected'))
        except Exception as exc:
            raise CommandError(f'Could not verify migration graph: {exc}') from exc

        # Check cache connectivity
        try:
            from django.core.cache import caches
            default_cache = caches['default']
            test_key = '_code_editor_validate_install'
            default_cache.set(test_key, 'ok', 1)
            if default_cache.get(test_key) != 'ok':
                raise RuntimeError('Cache set/get failed')
            self.stdout.write(self.style.SUCCESS('Cache backend is reachable'))
        except Exception as exc:
            raise CommandError(f'Cache backend is not reachable or misconfigured: {exc}') from exc

        # Check storage paths
        try:
            from django.conf import settings
            import os

            required_settings = [
                'CODE_EDITOR_TASK_STORAGE_ROOT',
                'CODE_EDITOR_REPOSITORY_STORAGE_ROOT',
                'CODE_EDITOR_ARTIFACT_STORAGE_ROOT',
                'CODE_EDITOR_COMMAND_TIMEOUT_SECONDS',
                'CODE_EDITOR_COMMAND_MAX_OUTPUT_BYTES',
                'CODE_EDITOR_PUBLIC_MODEL_LISTING',
                'CODE_EDITOR_PUBLIC_METRICS',
            ]
            missing = [name for name in required_settings if getattr(settings, name, None) in (None, '')]
            if missing:
                raise CommandError(f'Missing required settings: {", ".join(missing)}')
            storage_root = settings.CODE_EDITOR_TASK_STORAGE_ROOT
            if not os.path.isdir(storage_root):
                raise CommandError(f'Task storage root {storage_root} does not exist')
            else:
                self.stdout.write(self.style.SUCCESS(f'Task storage root exists: {storage_root}'))
            repository_root = settings.CODE_EDITOR_REPOSITORY_STORAGE_ROOT
            if not os.path.isdir(repository_root):
                raise CommandError(f'Repository storage root {repository_root} does not exist')
            self.stdout.write(self.style.SUCCESS(f'Repository storage root exists: {repository_root}'))
            artifact_root = settings.CODE_EDITOR_ARTIFACT_STORAGE_ROOT
            if not os.path.isdir(artifact_root):
                raise CommandError(f'Artifact storage root {artifact_root} does not exist')
            self.stdout.write(self.style.SUCCESS(f'Artifact storage root exists: {artifact_root}'))
        except Exception as exc:
            raise CommandError(f'Failed to verify storage roots: {exc}') from exc

        try:
            resolver = get_resolver()
            if resolver.url_patterns is None:
                raise CommandError('URL resolver did not load any patterns')
            resolve('/health/live/')
            resolve('/api/code-editor/metrics/')
            self.stdout.write(self.style.SUCCESS('URL configuration resolves health and metrics endpoints'))
        except Exception as exc:
            raise CommandError(f'URLConf validation failed: {exc}') from exc

        try:
            from django.contrib import admin

            admin.site.check(None)
            self.stdout.write(self.style.SUCCESS('Admin registrations validated'))
        except Exception as exc:
            raise CommandError(f'Admin validation failed: {exc}') from exc

        try:
            from django.test import RequestFactory
            from ...api import views as api_views
            from ...observability.metrics import metrics_view

            request = RequestFactory().get('/api/code-editor/models/')
            response = api_views.models_list(request)
            if response.status_code not in {401, 403}:
                raise CommandError(
                    f'Model listing must be private by default; received {response.status_code}'
                )
            metrics_response = metrics_view(RequestFactory().get('/api/code-editor/metrics/'))
            if metrics_response.status_code not in {403, 404}:
                raise CommandError(
                    f'Metrics endpoint must be protected by default; received {metrics_response.status_code}'
                )
            self.stdout.write(self.style.SUCCESS('Public surface protection validated'))
        except Exception as exc:
            raise CommandError(f'Protected endpoint validation failed: {exc}') from exc

        # Optionally check providers if requested
        if check_providers:
            self.stdout.write('Checking provider health (may take time)...')
            try:
                from django.core.management import call_command
                call_command('check_code_editor_providers', '--check-providers')
            except Exception as exc:
                raise CommandError(f'Provider health check failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS('Installation validation completed'))
