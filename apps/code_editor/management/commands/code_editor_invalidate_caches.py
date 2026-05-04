"""Invalidate caches related to the code editor application.

This management command provides a simple interface to invalidate one or more
caches used by the code editor.  If no specific cache names are provided,
all known caches will be cleared.  A ``--dry-run`` option allows operators
to see which caches would be invalidated without performing the operation.

Example usage::

    python manage.py code_editor_invalidate_caches --cache model_registry --cache code_map

Available cache names: model_registry, provider_health, repository_stats, code_map,
context_pack, retrieval_results, all
"""

from django.core.management.base import BaseCommand
from typing import List
from ...services.cache_helper import CacheHelper


class Command(BaseCommand):
    help = 'Invalidate caches used by the code editor.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--cache', action='append', dest='caches', default=[],
            help='Name of the cache to invalidate (repeatable). Use "all" to clear everything.'
        )
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run', default=False,
            help='Print what would be invalidated without performing the action.'
        )

    def handle(self, *args, **options) -> None:
        caches: List[str] = options.get('caches') or []
        dry_run: bool = bool(options.get('dry_run'))
        if not caches:
            caches = ['all']
        for cache_name in caches:
            cache_name = cache_name.strip().lower()
            if cache_name == 'all':
                if dry_run:
                    self.stdout.write('Would invalidate all caches')
                else:
                    CacheHelper.invalidate_all()
                    self.stdout.write(self.style.SUCCESS('All caches invalidated'))
                continue
            method_name = f'invalidate_{cache_name}_cache'
            if not hasattr(CacheHelper, method_name):
                self.stdout.write(self.style.WARNING(f'Unknown cache name: {cache_name}'))
                continue
            if dry_run:
                self.stdout.write(f'Would invalidate cache: {cache_name}')
            else:
                getattr(CacheHelper, method_name)()
                self.stdout.write(self.style.SUCCESS(f'Cache invalidated: {cache_name}'))