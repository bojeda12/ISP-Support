from django.urls import path

from .views import health
from diagnostics.api import RunDiagnosticView
from conversations.api import ChatView
from conversations.history_api import ConversationMessagesView
from conversations.media_api import (
    InstructionCatalogView, InstructionImageView, ConversationPhotosView, PhotoDetailView, PhotoContentView,
)

app_name = "api"
urlpatterns = [
    path("health/", health, name="health"),
    path("diagnostics/run/", RunDiagnosticView.as_view(), name="diagnostic-run"),
    path("chat/", ChatView.as_view(), name="chat"),
    path("conversations/<int:conversation_id>/messages/", ConversationMessagesView.as_view(), name="conversation-messages"),
    path("instructions/", InstructionCatalogView.as_view(), name="instruction-catalog"),
    path("instructions/<slug:image_id>/", InstructionImageView.as_view(), name="instruction-image"),
    path("conversations/<int:conversation_id>/photos/", ConversationPhotosView.as_view(), name="conversation-photos"),
    path("photos/<uuid:photo_id>/", PhotoDetailView.as_view(), name="photo-detail"),
    path("photos/<uuid:photo_id>/content/", PhotoContentView.as_view(), name="photo-content"),
]
