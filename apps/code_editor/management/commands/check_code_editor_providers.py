"""Management command to perform safe health checks on AI providers.

This command enumerates the configured providers via the ``RouterService``
and reports a normalised health status for each without invoking any
paid endpoints.  It uses the ``get_provider_health_status`` method of
``RouterService`` which performs a lightweight availability check
against each provider's ``is_available`` method and gathers capability
metadata.  The command is safe to run in development or production
environments as it does not initiate any network calls beyond those
explicitly permitted by provider implementations.

Example usage::

    python manage.py check_code_editor_providers
"""

from django.core.management.base import BaseCommand, CommandError

from ...services.router import RouterService


class Command(BaseCommand):
    help = 'Run a safe health check on configured AI providers'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--check-providers',
            action='store_true',
            default=False,
            help='Perform online availability checks (may call configured local endpoints).',
        )

    def handle(self, *args, **options) -> None:
        online = bool(options.get('check_providers'))
        self.stdout.write('Checking AI provider configuration...')
        router = RouterService()
        if online:
            try:
                health_status = router.get_provider_health_status()
            except Exception as exc:
                raise CommandError(f'Failed to compute provider health: {exc}') from exc
        else:
            health_status = {}
            for name, provider in router._providers.items():  # pylint: disable=protected-access
                health_status[name] = {
                    'provider': name,
                    'type': type(provider).__name__,
                    'status': 'configured',
                    'available': 'not-checked',
                    'response_time_ms': None,
                    'capabilities': provider.get_capabilities(),
                    'error': None,
                }
        if not health_status:
            self.stdout.write('No providers are configured.')
            return
        # Print a simple report for each provider
        for name, info in health_status.items():
            status = info.get('status', 'unknown')
            available = info.get('available', False)
            latency = info.get('response_time_ms') or info.get('latency_ms')
            capabilities = info.get('capabilities', {})
            error = info.get('error')
            self.stdout.write(f"Provider: {name}")
            self.stdout.write(f"  Type: {info.get('type')}")
            self.stdout.write(f"  Status: {status}")
            self.stdout.write(f"  Available: {available}")
            if latency is not None:
                self.stdout.write(f"  Response time: {latency} ms")
            if capabilities:
                caps = ', '.join(k for k, v in capabilities.items() if v)
                self.stdout.write(f"  Capabilities: {caps if caps else 'none'}")
            if error:
                self.stdout.write(f"  Error: {error}")
        if not online:
            self.stdout.write('Provider online checks skipped. Re-run with --check-providers to test availability.')
        self.stdout.write('Provider check completed.')
