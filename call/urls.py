from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('make-call/', views.make_call, name='make_call'),
    path('answer/', views.answer, name='answer'),
    path('voice/', views.voice, name='voice'),
    path('test-config/', views.test_config, name='test_config'),
    path('view-response/<int:response_id>/', views.view_response, name='view_response'),
    path('export-excel/', views.export_to_excel, name='export_excel'),
    path('transcription/', views.transcription_webhook, name='transcription'),
]