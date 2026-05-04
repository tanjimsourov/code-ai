"""
Management command to generate a health report for the code editor.

This command reports on provider health, migration status and cache connectivity.
It does not execute paid API calls. For provider checks it uses
``RouterService.get_provider_health_status()`` which may perform lightweight
health checks. Operators can run this command periodically to assess the
system state.

Example usage::

    python manage.py code_editor_health_report
"""

from django.core.management.base import BaseCommand
from ...services.router import RouterService
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.core.cache import caches


class Command(BaseCommand):
    help = "Generate a health report for the code editor"

    def handle(self, *args, **options) -> None:
        self.stdout.write("Code editor health report:")
        # Provider health
        try:
            router = RouterService()
            health = router.get_provider_health_status()
            if not health:
                self.stdout.write("  No providers configured")
            else:
                for name, info in health.items():
                    status = info.get('status', 'unknown')
                    available = info.get('available', False)
                    error = info.get('error')
                    self.stdout.write(f"  Provider {name}: status={status}, available={available}, error={error}")
        except Exception as exc:
            self.stdout.write(f"  Provider health error: {exc}")
        # Migration leaf nodes
        try:
            connection = connections['default']
            executor = MigrationExecutor(connection)
            leaf_nodes = executor.loader.graph.leaf_nodes()
            code_leaves = [name for (app_label, name) in leaf_nodes if app_label == 'code_editor']
            leaves = ', '.join(code_leaves) if code_leaves else 'none'
            self.stdout.write(f"  Migration leaf nodes for code_editor: {leaves}")
        except Exception as exc:
            self.stdout.write(f"  Migration check error: {exc}")
        # Cache connectivity
        try:
            default_cache = caches['default']
            default_cache.set('_health_check', 'ok', 1)
            if default_cache.get('_health_check') == 'ok':
                self.stdout.write("  Cache backend: reachable")
            else:
                self.stdout.write("  Cache backend: set/get failed")
        except Exception as exc:
            self.stdout.write(f"  Cache backend error: {exc}")
        self.stdout.write("Health report completed.")