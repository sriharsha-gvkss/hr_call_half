from django.core.management.base import BaseCommand
from django.conf import settings
from twilio.rest import Client
from call.models import CallResponse
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fetch transcripts from Twilio and save them to the database'

    def handle(self, *args, **options):
        try:
            # Check if Twilio credentials are set
            if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
                self.stdout.write(self.style.ERROR('Twilio credentials not found in settings'))
                return

            # Initialize Twilio client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            
            # Get calls from the last 30 days
            start_date = datetime.utcnow() - timedelta(days=30)
            calls = client.calls.list(start_time_after=start_date)
            
            self.stdout.write(f"Found {len(calls)} calls in the last 30 days")
            
            for call in calls:
                try:
                    # Get call details
                    call_details = client.calls(call.sid).fetch()
                    phone_number = call_details.to
                    
                    # Get recordings for this call
                    recordings = client.recordings.list(call_sid=call.sid)
                    
                    for recording in recordings:
                        try:
                            # Get transcript for this recording
                            transcript = None
                            transcript_status = 'pending'
                            
                            try:
                                transcript = client.transcriptions.list(recording_sid=recording.sid)
                                if transcript:
                                    transcript = transcript[0].transcription_text
                                    transcript_status = 'completed'
                            except Exception as e:
                                logger.error(f"Error fetching transcript for recording {recording.sid}: {str(e)}")
                                transcript_status = 'failed'
                            
                            # Create or update CallResponse
                            response, created = CallResponse.objects.update_or_create(
                                recording_sid=recording.sid,
                                defaults={
                                    'phone_number': phone_number,
                                    'recording_url': recording.uri,
                                    'recording_duration': recording.duration,
                                    'transcript': transcript,
                                    'transcript_status': transcript_status
                                }
                            )
                            
                            status = "Created" if created else "Updated"
                            self.stdout.write(f"{status} response for call {call.sid} with recording {recording.sid}")
                            
                        except Exception as e:
                            logger.error(f"Error processing recording {recording.sid}: {str(e)}")
                            continue
                            
                except Exception as e:
                    logger.error(f"Error processing call {call.sid}: {str(e)}")
                    continue
            
            self.stdout.write(self.style.SUCCESS('Successfully fetched transcripts from Twilio'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            logger.error(f"Error in fetch_twilio_transcripts: {str(e)}") 