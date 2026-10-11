from django.conf import settings
from django.core.files.storage import FileSystemStorage


class ReferenceStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.PRIVATE_MEDIA_ROOT / 'knowledge', file_permissions_mode=0o600)

    def url(self, name):
        raise ValueError('Reference documents are private.')


def reference_path(instance, filename):
    return f'{instance.pk.hex}/reference.pdf'
