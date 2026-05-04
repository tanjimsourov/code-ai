from rest_framework import status
from rest_framework.exceptions import APIException


class CodeEditorException(APIException):
    """Base exception for code editor API"""
    default_detail = "Code Editor API error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR


class ProviderNotAvailableException(CodeEditorException):
    """Raised when AI provider is not available"""
    default_detail = "AI provider is not available"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class QuotaExceededException(CodeEditorException):
    """Raised when API key quota is exceeded"""
    default_detail = "API key quota exceeded"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


class RateLimitExceededException(CodeEditorException):
    """Raised when rate limit is exceeded"""
    default_detail = "Rate limit exceeded"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


class InvalidAPIKeyException(CodeEditorException):
    """Raised when API key is invalid"""
    default_detail = "Invalid API key"
    status_code = status.HTTP_401_UNAUTHORIZED


class InvalidRequestException(CodeEditorException):
    """Raised when request is invalid"""
    default_detail = "Invalid request"
    status_code = status.HTTP_400_BAD_REQUEST


class ModelNotSupportedException(CodeEditorException):
    """Raised when model is not supported"""
    default_detail = "Model not supported"
    status_code = status.HTTP_400_BAD_REQUEST


class ProviderTimeoutException(CodeEditorException):
    """Raised when provider request times out"""
    default_detail = "Provider request timeout"
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
