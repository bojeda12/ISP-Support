"""Carga acotada en memoria: no crea archivos temporales fuera del repositorio."""

from io import BytesIO

from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler, StopUpload


class BoundedPhotoUploadHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.total_bytes = 0

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.buffer = BytesIO()

    def receive_data_chunk(self, raw_data, start):
        self.total_bytes += len(raw_data)
        if self.total_bytes > settings.PHOTO_MAX_BYTES:
            self.request.photo_too_large = True
            raise StopUpload(connection_reset=True)
        self.buffer.write(raw_data)

    def file_complete(self, file_size):
        self.buffer.seek(0)
        return InMemoryUploadedFile(
            self.buffer, self.field_name, self.file_name, self.content_type,
            file_size, self.charset, self.content_type_extra,
        )
