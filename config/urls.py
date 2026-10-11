from django.contrib import admin
from django.urls import include, path
from conversations.web import demo_page, demo_state, select_demo_service, confirm_demo_language, previous_conversations, choose_conversation
from conversations.web import customer_page, customer_state, customer_reconnect

admin.site.site_header = "ISP Support Administration"
admin.site.site_title = "ISP Support"
admin.site.index_title = "Technical support workspace"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("demo/", demo_page, name="demo"),
    path("demo/customer/", customer_page, name="demo-customer"),
    path("demo/customer/state/", customer_state, name="demo-customer-state"),
    path("demo/customer/reconnect/", customer_reconnect, name="demo-customer-reconnect"),
    path("demo/state/", demo_state, name="demo-state"),
    path("demo/session/", select_demo_service, name="demo-session"),
    path("demo/language/", confirm_demo_language, name="demo-language"),
    path("demo/conversations/", previous_conversations, name="demo-conversations"),
    path("demo/conversation/", choose_conversation, name="demo-conversation"),
]
