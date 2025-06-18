from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from twilio.twiml.voice_response import VoiceResponse, Record, Say, Gather
from twilio.rest import Client
from django.conf import settings
from urllib.parse import quote
from .models import Recording, CallResponse
import re
from django.views.decorators.http import require_http_methods
from datetime import datetime
import os
from dotenv import load_dotenv
from django.utils import timezone
import pandas as pd
import logging
import time
import json

logger = logging.getLogger(__name__)

# Load environment variables first
load_dotenv()

# Initialize Twilio client with environment variables
client = Client(
    os.getenv('TWILIO_ACCOUNT_SID'),
    os.getenv('TWILIO_AUTH_TOKEN')
)

# Public URL for webhooks - Replace this with your actual public URL
PUBLIC_URL = "https://call-1-u39m.onrender.com"  # Update this with your Render URL

def format_phone_number(phone_number):
    """Format phone number to E.164 format"""
    # Remove any non-digit characters
    phone_number = ''.join(filter(str.isdigit, phone_number))
    
    # If number starts with 91, keep it as is
    if phone_number.startswith('91'):
        return f"+{phone_number}"
    
    # If number is 10 digits, add 91
    if len(phone_number) == 10:
        return f"+91{phone_number}"
    
    return phone_number

# Make a call to client
@csrf_exempt
@require_http_methods(["POST"])
def make_call(request):
    try:
        phone_number = request.POST.get('phone_number')
        if not phone_number:
            return redirect('dashboard')

        # Format phone number for India
        if not phone_number.startswith('+'):
            if phone_number.startswith('0'):
                phone_number = '+91' + phone_number[1:]
            else:
                phone_number = '+91' + phone_number

        # Create Twilio client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Reset session for new call
        request.session['current_question_index'] = 0
        
        # Create webhook URL
        webhook_url = f"{settings.PUBLIC_URL}/answer/"
        
        # Make the call
        call = client.calls.create(
            to=phone_number,
            from_=settings.TWILIO_PHONE_NUMBER,
            url=webhook_url,
            record=True
        )
        
        logger.info(f"Call initiated to {phone_number} with SID: {call.sid}")
        return redirect('dashboard')
        
    except Exception as e:
        logger.error(f"Error making call: {str(e)}")
        return redirect('dashboard')

# Answer call with questions
@csrf_exempt
@require_http_methods(["POST"])
def answer(request):
    """Handle incoming call and play question"""
    phone_number = request.GET.get('phone', '')
    
    # Define the sequence of default questions
    questions = [
        "Hi, please tell us your full name.",
        "What is your work experience?",
        "What was your previous job role?",
        "Why do you want to join our company?"
    ]
    
    # Store the questions in the session
    request.session['questions'] = questions
    request.session['current_question_index'] = 0
    question = questions[0]
    
    # Create a new response record
    response = CallResponse.objects.create(
        phone_number=phone_number,
        question=question
    )
    
    # Store the response ID in the session
    request.session['response_id'] = response.id
    
    resp = VoiceResponse()
    resp.say(question, voice='Polly.Amy')
    resp.record(
        action=f'/recording_status/?response_id={response.id}',
        maxLength='30',
        playBeep=False
    )
    
    return HttpResponse(str(resp))

def fetch_transcript(recording_sid):
    """Fetch transcript for a recording using Twilio's API"""
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Get the recording
        recording = client.recordings(recording_sid).fetch()
        
        # Get the transcript
        transcript = client.recordings(recording_sid).transcriptions.list()
        
        if transcript:
            return transcript[0].transcription_text
        return None
    except Exception as e:
        logger.error(f"Error fetching transcript: {str(e)}")
        return None

# Handle recorded answer
@csrf_exempt
@require_http_methods(["POST"])
def recording_status(request):
    """Handle recording status callback from Twilio"""
    try:
        response_id = request.GET.get('response_id')
        recording_url = request.POST.get('RecordingUrl')
        recording_duration = request.POST.get('RecordingDuration')
        recording_sid = request.POST.get('RecordingSid')
        
        logger.info(f"Recording status callback - Response ID: {response_id}, Recording URL: {recording_url}")
        
        if not response_id or not recording_url:
            logger.error("Missing response_id or recording_url in callback")
            return HttpResponse('Missing required parameters', status=400)
            
        try:
            response = CallResponse.objects.get(id=response_id)
            
            # Update response with recording details
            response.recording_url = recording_url
            if recording_duration:
                response.recording_duration = recording_duration
            if recording_sid:
                response.recording_sid = recording_sid
                # Start transcript fetching process
                response.transcript_status = 'pending'
                response.save()
                
                # Fetch transcript in background
                transcript = fetch_transcript(recording_sid)
                if transcript:
                    response.transcript = transcript
                    response.transcript_status = 'completed'
                else:
                    response.transcript_status = 'failed'
                response.save()
            
            logger.info(f"Saved recording for response {response_id}")
            
            # Check if we need to ask more questions
            current_index = request.session.get('current_question_index', 0)
            if current_index < 4:  # We have 4 questions total
                # Redirect to voice view for next question
                return redirect('voice')
            else:
                # All questions answered
                resp = VoiceResponse()
                resp.say("Thank you for your responses. We will review them and get back to you soon. Goodbye!")
                return HttpResponse(str(resp))
                
        except CallResponse.DoesNotExist:
            logger.error(f"Response {response_id} not found")
            return HttpResponse('Response not found', status=404)
            
    except Exception as e:
        logger.error(f"Error in recording_status: {str(e)}")
        return HttpResponse('Server error', status=500)

# HR Dashboard
def dashboard(request):
    """Display dashboard with all responses"""
    try:
        # Get all responses ordered by creation date
        responses = CallResponse.objects.all().order_by('-created_at')
        
        # Get transcript statistics
        transcript_stats = {
            'completed': responses.filter(transcript_status='completed').count(),
            'pending': responses.filter(transcript_status='pending').count(),
            'failed': responses.filter(transcript_status='failed').count()
        }
        
        # Group responses by phone number
        responses_by_phone = {}
        for response in responses:
            if response.phone_number not in responses_by_phone:
                responses_by_phone[response.phone_number] = []
            responses_by_phone[response.phone_number].append(response)
        
        context = {
            'responses': responses,
            'total_responses': responses.count(),
            'total_recordings': responses.exclude(recording_url__isnull=True).count(),
            'total_transcripts': transcript_stats['completed'],
            'responses_by_phone': responses_by_phone,
            'transcript_stats': transcript_stats
        }
        
        return render(request, 'call/dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in dashboard view: {str(e)}")
        return render(request, 'call/dashboard.html', {
            'error': str(e),
            'responses': [],
            'total_responses': 0,
            'total_recordings': 0,
            'total_transcripts': 0,
            'responses_by_phone': {},
            'transcript_stats': {'completed': 0, 'pending': 0, 'failed': 0}
        })

def index(request):
    """Render the main page"""
    return render(request, 'call/dashboard.html')

def test_config(request):
    config = {
        'TWILIO_ACCOUNT_SID': os.getenv('TWILIO_ACCOUNT_SID'),
        'TWILIO_AUTH_TOKEN': os.getenv('TWILIO_AUTH_TOKEN'),
        'TWILIO_PHONE_NUMBER': os.getenv('TWILIO_PHONE_NUMBER'),
    }
    return JsonResponse(config)

def view_response(request, response_id):
    """Display the details of a specific response"""
    response = CallResponse.objects.get(id=response_id)
    return render(request, 'call/view_response.html', {'response': response})

def export_to_excel(request):
    """Export all responses to Excel"""
    try:
        # Get all responses
        responses = CallResponse.objects.all().order_by('-created_at')
        
        # Create a DataFrame
        data = {
            'Phone Number': [r.phone_number for r in responses],
            'Question': [r.question for r in responses],
            'Recording URL': [r.recording_url for r in responses],
            'Created At': [r.created_at.strftime('%Y-%m-%d %H:%M:%S') for r in responses]
        }
        df = pd.DataFrame(data)
        
        # Create Excel file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'call_responses_{timestamp}.xlsx'
        
        # Save to Excel
        df.to_excel(filename, index=False)
        
        # Read the file and create response
        with open(filename, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Delete the temporary file
        os.remove(filename)
        
        return response
        
    except Exception as e:
        print(f"Error exporting to Excel: {str(e)}")
        return HttpResponse('Error exporting to Excel', status=500)

@csrf_exempt
def voice(request):
    """Handle incoming voice calls"""
    try:
        response = VoiceResponse()
        
        # Define the sequence of default questions
        questions = [
            "Hi, please tell us your full name.",
            "What is your work experience?",
            "What was your previous job role?",
            "Why do you want to join our company?"
        ]
        
        # Get the current question index from the session or start with 0
        current_index = request.session.get('current_question_index', 0)
        
        if current_index < len(questions):
            # Get the current question
            question = questions[current_index]
            
            # Create a new response record
            call_response = CallResponse.objects.create(
                phone_number=request.POST.get('From', 'Unknown'),
                question=question
            )
            
            # Store the response ID in the session
            request.session['response_id'] = call_response.id
            
            # Say the question
            response.say(question, voice='Polly.Amy')
            
            # Record the response with transcription enabled
            response.record(
                action=f'/recording-status/?response_id={call_response.id}',
                transcribe=True,
                transcribeCallback='/transcription/',
                maxLength=60,
                playBeep=True
            )
            
            # Increment the question index for next time
            request.session['current_question_index'] = current_index + 1
            
        else:
            # All questions have been asked
            response.say("Thank you for your responses. We will review them and get back to you soon. Goodbye!")
            # Reset the session
            request.session['current_question_index'] = 0
        
        return HttpResponse(str(response))
        
    except Exception as e:
        logger.error(f"Error in voice view: {str(e)}")
        response = VoiceResponse()
        response.say("An error occurred. Please try again later.")
        return HttpResponse(str(response))

@csrf_exempt
def transcription_webhook(request):
    """Handle transcription webhook from Twilio"""
    if request.method == "POST":
        try:
            # Get transcription data from request
            transcript_text = request.POST.get('TranscriptionText')
            recording_url = request.POST.get('RecordingUrl')
            call_sid = request.POST.get('CallSid')
            recording_sid = request.POST.get('RecordingSid')
            
            logger.info(f"Received transcription for CallSID: {call_sid}")
            logger.info(f"Transcript: {transcript_text}")
            logger.info(f"Recording URL: {recording_url}")
            
            # Find or create CallResponse
            response, created = CallResponse.objects.get_or_create(
                recording_sid=recording_sid,
                defaults={
                    'phone_number': call_sid,  # Using call_sid temporarily
                    'question': 'Auto-transcribed response',
                    'recording_url': recording_url,
                    'transcript': transcript_text,
                    'transcript_status': 'completed'
                }
            )
            
            if not created:
                # Update existing response
                response.transcript = transcript_text
                response.transcript_status = 'completed'
                response.save()
            
            return HttpResponse("Transcription received", status=200)
            
        except Exception as e:
            logger.error(f"Error in transcription webhook: {str(e)}")
            return HttpResponse(f"Error processing transcription: {str(e)}", status=500)
            
    return HttpResponse("Invalid request method", status=400)