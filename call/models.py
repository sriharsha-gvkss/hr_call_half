from django.db import models

# Create your models here.
class Recording(models.Model):
    question = models.CharField(max_length=255)
    recording_url = models.URLField()
    transcript = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question