"""Service registry for the code_editor package.

This module exposes service classes lazily so that importing the
``code_editor.services`` package does not eagerly import all provider
implementations or other heavy modules.  Many services depend on
third‑party libraries, environment configuration or network access; they
should only be loaded when explicitly requested.  To avoid circular
dependencies and unnecessary side effects at import time, this module
defines a mapping of service class names to their modules and implements
``__getattr__`` to import the appropriate module on demand.

Only service classes listed in ``__all__`` are accessible as attributes
of this package.  Attempting to access any other name will raise
``AttributeError``.
"""

from importlib import import_module
from typing import Any

__all__ = [
    'ConfigService',
    'RouterService',
    'PromptBuilderService',
    'ContextBuilderService',
    'ChatService',
    'CompletionService',
    'EditService',
    'EmbeddingsService',
    'RerankService',
    'InfillService',
    'ModelsService',
    'RepositoryService',
    'RetrievalService',
    'IngestionService',
    'StreamingService',
    # Task orchestration services
    'PlanningService',
    'FileSelectionService',
    'PatchGenerationService',
    'ValidationService',
    'CandidateScoringService',
    'BugRepairService',
    'SymbolAnalysisService',
    'PatchService',
    'CodeMapService',
    'ContextPackBuilderService',
    'TaskArtifactService',
    # Model registry service
    'ModelRegistryService',
    # Model registry service
    'ModelRegistryService',
]

# Map public service names to their module paths within the services package.
_SERVICE_MODULES = {
    'ConfigService': '.config',
    'RouterService': '.router',
    'PromptBuilderService': '.prompt_builder',
    'ContextBuilderService': '.context_builder',
    'ChatService': '.chat_service',
    'CompletionService': '.completion_service',
    'EditService': '.edit_service',
    'EmbeddingsService': '.embeddings_service',
    'RerankService': '.rerank_service',
    'InfillService': '.infill_service',
    'ModelsService': '.models_service',
    'RepositoryService': '.repository_service',
    'RetrievalService': '.retrieval_service',
    'IngestionService': '.ingestion_service',
    'StreamingService': '.streaming_service',
    'PlanningService': '.planning_service',
    'FileSelectionService': '.file_selection_service',
    'PatchGenerationService': '.patch_generation_service',
    'ValidationService': '.validation_service',
    'CandidateScoringService': '.candidate_scoring_service',
    'BugRepairService': '.bug_repair_service',
    'SymbolAnalysisService': '.symbol_analysis_service',
    'PatchService': '.patch_service',
    'CodeMapService': '.code_map_service',
    'ContextPackBuilderService': '.context_pack_builder',
    'TaskArtifactService': '.task_artifact_service',
    # Model registry service
    'ModelRegistryService': '.model_registry',
    # Model registry service
    'ModelRegistryService': '.model_registry',
}


def __getattr__(name: str) -> Any:
    """Dynamically import the requested service class on first access.

    When an attribute corresponding to a service class is accessed on
    ``code_editor.services``, this function looks up the module path in
    ``_SERVICE_MODULES`` and imports the module.  It then retrieves
    the service class from that module and returns it.  If the name
    is not listed in ``__all__``, an ``AttributeError`` is raised.

    :param name: The service class name being requested
    :returns: The service class object
    :raises AttributeError: If the name is not a known service
    """
    if name not in __all__:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    module_path = _SERVICE_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"Service '{name}' is not registered")
    module = import_module(module_path, __name__)
    attr = getattr(module, name, None)
    if attr is None:
        raise AttributeError(f"Module '{module.__name__}' does not define '{name}'")
    return attr