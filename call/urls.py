from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('make-call/', views.make_call, name='make_call'),
    path('answer/', views.answer_call, name='answer_call'),
    path('save-recording/', views.save_recording, name='save_recording'),
    path('test-config/', views.test_config, name='test_config'),
]