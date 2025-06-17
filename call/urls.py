from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('make-call/', views.make_call, name='make_call'),
    path('answer/', views.answer, name='answer'),
    path('recording_status/', views.recording_status, name='recording_status'),
    path('test-config/', views.test_config, name='test_config'),
    path('view_response/<int:response_id>/', views.view_response, name='view_response'),
]