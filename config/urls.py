"""URL configuration for the SkillMatch project."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    # django-allauth is used only for Google sign-in; send its own
    # login/signup pages to SkillMatch's designed screens.
    path('accounts/login/', RedirectView.as_view(pattern_name='login', query_string=True)),
    path('accounts/signup/', RedirectView.as_view(pattern_name='register', query_string=True)),
    path('accounts/', include('allauth.urls')),
    path('', include('core.urls')),
]

if settings.DEBUG:
    # Profile photos only. CVs live outside MEDIA_ROOT and are served by an
    # owner-only view, never as public files.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
