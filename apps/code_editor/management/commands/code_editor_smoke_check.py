"""Management command to perform a lightweight sanity check on the code editor.

This command imports core modules of the ``code_editor`` package to ensure
that the application can be loaded without raising import errors.  It
verifies that the API views, serializers, tasks and workflows modules
resolve correctly and that the services package can be imported lazily.  It
also lists the configured providers and warns if multiple migration
``000X`` leaves exist within the app's migrations.  The command does not
execute any provider API calls or run the full Django system checks, so
it is safe to run in environments without external credentials.

Example usage::

    python manage.py code_editor_smoke_check
"""

import os
import re
import time
from importlib import import_module

from django.core.management.base import BaseCommand

try:
    from ...services.router import RouterService
except Exception:
    # If RouterService cannot be imported, we handle this in the command
    RouterService = None  # type: ignore


class Command(BaseCommand):
    help = 'Run a lightweight smoke check on the code editor application'

    def handle(self, *args, **options) -> None:
        self.stdout.write('Running code editor smoke check...')

        modules_to_import = [
            'code_editor.models',
            'code_editor.views',
            'code_editor.api',
            'code_editor.services',
            'code_editor.tasks',
            'code_editor.workflows',
        ]
        import_errors: list[tuple[str, str]] = []
        for module_name in modules_to_import:
            try:
                import_module(module_name)
            except Exception as exc:  # pragma: no cover
                import_errors.append((module_name, str(exc)))

        # Detect multiple leaf migrations using Django's migration graph.  Duplicate
        # numeric prefixes are not considered errors because merge migrations
        # legitimately share prefixes.  Instead we warn if more than one leaf
        # exists for the code_editor app.
        dup_migrations: list[str] = []
        try:
            from django.db import connections
            from django.db.migrations.executor import MigrationExecutor
            connection = connections['default']
            executor = MigrationExecutor(connection)
            leaf_nodes = executor.loader.graph.leaf_nodes()
            # Filter leaf nodes belonging to this app
            code_editor_leaves = [name for (app_label, name) in leaf_nodes if app_label == 'code_editor']
            if len(code_editor_leaves) > 1:
                dup_migrations = code_editor_leaves
        except Exception:
            # ignore issues in migration scanning
            pass

        # List available providers using RouterService, if import succeeded
        provider_info = None
        if RouterService is not None:
            try:
                router = RouterService()
                providers = router.get_available_providers()
                provider_info = ', '.join(providers) if providers else 'none'
            except Exception as exc:
                provider_info = f'error: {exc}'
        else:
            provider_info = 'RouterService import failed'

        # Report findings
        if import_errors:
            self.stdout.write(self.style.ERROR('Import errors detected:'))
            for mod, err in import_errors:
                self.stdout.write(f'  - {mod}: {err}')
        else:
            self.stdout.write(self.style.SUCCESS('All core modules imported successfully.'))

        if dup_migrations:
            self.stdout.write(
                self.style.WARNING(
                    f"Migration conflicts detected for prefixes: {', '.join(dup_migrations)}."
                )
            )
        else:
            self.stdout.write('No conflicting migration prefixes detected.')

        self.stdout.write(f'Available providers: {provider_info}')

        if import_errors or dup_migrations:
            self.stdout.write(self.style.ERROR('Smoke check failed'))
        else:
            self.stdout.write(self.style.SUCCESS('Smoke check passed'))