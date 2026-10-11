"""Evita que una carga administrativa PDF escriba temporales fuera del proyecto."""
from django.core.files.uploadhandler import StopUpload
from conversations.upload_handlers import BoundedPhotoUploadHandler


class ReferenceUploadHandler(BoundedPhotoUploadHandler):
    def receive_data_chunk(self,raw_data,start):
        self.total_bytes += len(raw_data)
        if self.total_bytes > 10*1024*1024:
            self.request.reference_too_large = True
            raise StopUpload(connection_reset=True)
        self.buffer.write(raw_data)


class ReferenceUploadMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        if request.method == 'POST' and request.path.startswith('/admin/knowledge/referencedocument/'):
            request.upload_handlers=[ReferenceUploadHandler(request)]
        return self.get_response(request)
