from django.core.management.base import BaseCommand
from twilio.rest import Client
from django.conf import settings
from call.models import CallResponse
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fetch transcripts from Twilio for all recordings'

    def handle(self, *args, **options):
        try:
            # Debug information
            self.stdout.write("Checking Twilio credentials...")
            if not settings.TWILIO_ACCOUNT_SID:
                self.stdout.write(self.style.ERROR("TWILIO_ACCOUNT_SID is not set"))
                return
            if not settings.TWILIO_AUTH_TOKEN:
                self.stdout.write(self.style.ERROR("TWILIO_AUTH_TOKEN is not set"))
                return
                
            self.stdout.write("Credentials found, initializing Twilio client...")
            
            # Initialize Twilio client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            
            # Get all recordings from Twilio
            self.stdout.write("Fetching recordings from Twilio...")
            recordings = client.recordings.list()
            
            self.stdout.write(f"Found {len(recordings)} recordings in Twilio")
            
            for recording in recordings:
                try:
                    # Get transcript for this recording
                    self.stdout.write(f"Processing recording {recording.sid}...")
                    transcript = client.recordings(recording.sid).transcriptions.list()
                    
                    if transcript:
                        # Find or create CallResponse for this recording
                        response, created = CallResponse.objects.get_or_create(
                            recording_sid=recording.sid,
                            defaults={
                                'phone_number': recording.call_sid,  # Using call_sid as phone number temporarily
                                'question': 'Auto-imported recording',
                                'recording_url': recording.uri,
                                'recording_duration': str(recording.duration),
                                'transcript': transcript[0].transcription_text,
                                'transcript_status': 'completed'
                            }
                        )
                        
                        if not created:
                            # Update existing response with transcript
                            response.transcript = transcript[0].transcription_text
                            response.transcript_status = 'completed'
                            response.save()
                            
                        self.stdout.write(self.style.SUCCESS(
                            f"Successfully processed recording {recording.sid}"
                        ))
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"No transcript found for recording {recording.sid}"
                        ))
                        
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"Error processing recording {recording.sid}: {str(e)}"
                    ))
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {str(e)}")) 