from django.contrib import admin
from django.urls import include, path
from conversations.web import demo_page, demo_state, select_demo_service, confirm_demo_language

admin.site.site_header = "ISP Support Administration"
admin.site.site_title = "ISP Support"
admin.site.index_title = "Technical support workspace"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("demo/", demo_page, name="demo"),
    path("demo/state/", demo_state, name="demo-state"),
    path("demo/session/", select_demo_service, name="demo-session"),
    path("demo/language/", confirm_demo_language, name="demo-language"),
]
