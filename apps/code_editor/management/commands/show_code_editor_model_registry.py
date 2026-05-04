"""
Management command to display the model registry for the code editor.

This command instantiates the ``ModelRegistryService`` and prints a
concise table of roles, resolved providers, models and key
capabilities.  It does not make outbound network calls to external
providers and therefore may be safely executed in development or
production environments without triggering any API usage.  The
registry reflects both environment variable overrides and the router
configuration at the time of execution.

Example usage::

    python manage.py show_code_editor_model_registry

"""

from django.core.management.base import BaseCommand

from ...services.model_registry import ModelRegistryService


class Command(BaseCommand):
    help = 'Show the resolved model registry by role for the code editor'

    def handle(self, *args, **options) -> None:
        self.stdout.write('Resolving model registry...')
        registry_service = ModelRegistryService()
        try:
            registry = registry_service.get_registry()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Failed to resolve model registry: {exc}'))
            return
        # Print a tabular summary
        if not registry:
            self.stdout.write('No roles are defined in the model registry.')
            return
        # Determine column widths
        role_width = max(len(role) for role in registry.keys()) + 2
        prov_width = max(len(entry.get('provider') or '') for entry in registry.values()) + 2
        model_width = max(len(entry.get('model') or '') for entry in registry.values()) + 2
        # Header
        header = f"{'Role'.ljust(role_width)}{'Provider'.ljust(prov_width)}{'Model'.ljust(model_width)}Capabilities"
        self.stdout.write(header)
        self.stdout.write('-' * len(header))
        for role, entry in registry.items():
            provider = entry.get('provider') or '—'
            model = entry.get('model') or '—'
            caps = entry.get('capabilities') or {}
            # Summarise capabilities by listing enabled keys
            cap_list = ', '.join(sorted(k for k, v in caps.items() if v)) or 'none'
            line = f"{role.ljust(role_width)}{provider.ljust(prov_width)}{model.ljust(model_width)}{cap_list}"
            self.stdout.write(line)
        self.stdout.write('Model registry resolved.')