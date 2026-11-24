"""Drop-in route configuration for the tested OMERO.oauth deployment."""
from django.urls import re_path as url
from . import views
from .cci_orcid import OrcidCallbackView, sessiontoken

urlpatterns = [
    url(r'^$', views.OauthLoginView.as_view(), name='oauth_index'),
    url(r'^callback/(?P<name>orcid)$', OrcidCallbackView.as_view(), name='oauth_orcid_callback'),
    url(r'^callback/(?P<name>[a-z][a-z0-9]+)$', views.OauthCallbackView.as_view(), name='oauth_callback'),
    url(r'^confirm$', views.confirm, name='oauth_confirm'),
    url(r'^sessiontoken$', sessiontoken, name='oauth_sessiontoken'),
    url(r'^error$', views.error, name='oauth_error'),
]
