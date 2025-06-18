from django.db import models
from django.utils import timezone

# Create your models here.
class Recording(models.Model):
    question = models.CharField(max_length=255)
    recording_url = models.URLField()
    transcript = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question

class CallResponse(models.Model):
    phone_number = models.CharField(max_length=20)
    question = models.TextField(blank=True, null=True)
    response = models.TextField(blank=True, null=True)
    recording_url = models.URLField(blank=True, null=True)
    recording_sid = models.CharField(max_length=100, unique=True, blank=True, null=True)
    recording_duration = models.IntegerField(blank=True, null=True)
    transcript = models.TextField(blank=True, null=True)
    transcript_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ],
        default='pending'
    )
    call_sid = models.CharField(max_length=100, blank=True, null=True)
    call_duration = models.IntegerField(blank=True, null=True)
    call_status = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Call to {self.phone_number} at {self.created_at}"