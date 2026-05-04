from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from ..permissions import CodeEditorApiKeyPermission
from rest_framework.response import Response

from ..exceptions import InvalidRequestException
from ..services.template_command_service import TemplateCommandService


@api_view(["POST"])
@permission_classes([CodeEditorApiKeyPermission])
def template_command(request):
    """Generate a ready-to-place template plan from a natural-language command."""
    service = TemplateCommandService()
    try:
        result = service.generate_template_plan(request.data if isinstance(request.data, dict) else {})
        return Response(result)
    except InvalidRequestException as exc:
        return Response(
            {
                "error": {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return Response(
            {
                "error": {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
