from django.urls import path
from .views import RouteAPIView, RouteMapView

urlpatterns = [
    path('route/',      RouteAPIView.as_view(), name='route_api'),
    path('route/map/',  RouteMapView.as_view(), name='route_map'),
]
