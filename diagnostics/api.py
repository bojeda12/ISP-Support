from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import DiagnosticRunSerializer, RunDiagnosticSerializer
from .services import run_diagnostic


class CanRunSimulation(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_staff and
                    user.has_perm("diagnostics.run_simulated_diagnostic"))


class RunDiagnosticView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanRunSimulation]

    def post(self, request):
        serializer = RunDiagnosticSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            run = run_diagnostic(internet_service=serializer.validated_data["service_id"],
                                 conversation=serializer.validated_data.get("conversation_id"))
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(DiagnosticRunSerializer(run).data, status=status.HTTP_201_CREATED)
