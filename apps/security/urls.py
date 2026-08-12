from django.shortcuts import redirect
from django.urls import path
from . import views

urlpatterns = [
    path('',                      lambda request: redirect('security-dashboard'), name='security-root'),
    path('login/',                views.security_login,     name='security-login'),
    path('logout/',               views.security_logout,    name='security-logout'),
    path('dashboard/',            views.dashboard,          name='security-dashboard'),
    path('overview/',             views.security_overview,  name='security-overview'),
    path('live-stats/',           views.live_stats,         name='security-live-stats'),
    path('block-ip/',             views.block_ip,           name='security-block-ip'),
    path('unblock-ip/<str:ip>/',  views.unblock_ip,         name='security-unblock-ip'),
    path('alert/<int:alert_id>/resolve/', views.resolve_alert,      name='security-resolve-alert'),
    path('alerts/resolve-all/',   views.resolve_all_alerts, name='security-resolve-all'),
]
