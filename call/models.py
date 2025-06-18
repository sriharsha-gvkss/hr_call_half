from django.db import models

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
    question = models.TextField()
    response = models.TextField(blank=True, null=True)
    recording_url = models.URLField(blank=True, null=True)
    recording_sid = models.CharField(max_length=100, blank=True, null=True)
    recording_duration = models.CharField(max_length=20, blank=True, null=True)
    transcript = models.TextField(blank=True, null=True)
    transcript_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Call to {self.phone_number} - {self.created_at}"