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
from io import BytesIO
from django.contrib import messages
from django.contrib.auth.decorators import login_required

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

# Define the sequence of questions
INTERVIEW_QUESTIONS = [
    "Hi, what is your full name?",
    "What is your work experience?",
    "What was your previous job role?",
    "Why do you want to join our company?"
]

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
            messages.error(request, "Phone number is required")
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
        
        # Create webhook URL using settings
        webhook_url = f"{settings.PUBLIC_URL}/answer/"
        
        # Make the call
        call = client.calls.create(
            to=phone_number,
            from_=settings.TWILIO_PHONE_NUMBER,
            url=webhook_url,
            record=True,
            status_callback=f"{settings.PUBLIC_URL}/call_status/",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed']
        )
        
        # Create initial call response record
        CallResponse.objects.create(
            phone_number=phone_number,
            call_sid=call.sid,
            call_status=call.status,
            question="Call initiated"
        )
        
        logger.info(f"Call initiated to {phone_number} with SID: {call.sid}")
        messages.success(request, f"Call successfully initiated to {phone_number}")
        return redirect('dashboard')
        
    except Exception as e:
        logger.error(f"Error making call: {str(e)}")
        messages.error(request, f"Error making call: {str(e)}")
        return redirect('dashboard')

# Answer call with questions
@csrf_exempt
@require_http_methods(["POST"])
def answer(request):
    """Handle incoming call and play question"""
    try:
        # Get the call SID from the request
        call_sid = request.POST.get('CallSid')
        if not call_sid:
            logger.error("No CallSid provided in request")
            return HttpResponse('No CallSid provided', status=400)

        # Get the phone number from the request
        phone_number = request.POST.get('To', '')
        logger.info(f"Received call from {phone_number} with SID: {call_sid}")
        
        # Initialize Twilio client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Get call details
        call = client.calls(call_sid).fetch()
        
        # Get the first question
        question = INTERVIEW_QUESTIONS[0]
        
        # Create a new response record
        response = CallResponse.objects.create(
            phone_number=phone_number,
            call_sid=call_sid,
            question=question,
            call_status='in-progress'
        )
        
        # Store the response ID in the session
        request.session['response_id'] = response.id
        
        # Create TwiML response
        resp = VoiceResponse()
        
        # Add a short pause before asking the question
        resp.pause(length=0.5)
        
        # Ask the question
        resp.say(question, voice='Polly.Amy')
        
        # Add a short pause after the question
        resp.pause(length=0.5)
        
        # Record the response
        resp.record(
            action=f'{settings.PUBLIC_URL}/voice/?response_id={response.id}',
            maxLength='30',
            playBeep=False,
            trim='trim-silence'
        )
        
        return HttpResponse(str(resp))
        
    except Exception as e:
        logger.error(f"Error in answer view: {str(e)}")
        resp = VoiceResponse()
        resp.say("We're sorry, but there was an error processing your call. Please try again later.", voice='Polly.Amy')
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
    """Handle recording status and ask next question"""
    try:
        # Get the call SID from the request
        call_sid = request.POST.get('CallSid')
        if not call_sid:
            logger.error("No CallSid provided in request")
            return HttpResponse('No CallSid provided', status=400)

        # Get the response ID from the URL parameters
        response_id = request.GET.get('response_id')
        if not response_id:
            logger.error("No response_id provided in request")
            return HttpResponse('No response_id provided', status=400)

        # Get the recording SID from the request
        recording_sid = request.POST.get('RecordingSid')
        if not recording_sid:
            logger.error("No RecordingSid provided in request")
            return HttpResponse('No RecordingSid provided', status=400)

        logger.info(f"Processing recording {recording_sid} for call {call_sid} with response_id {response_id}")
        
        # Initialize Twilio client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Get call details
        call = client.calls(call_sid).fetch()
        
        # Update the response with recording details
        try:
            response = CallResponse.objects.get(id=response_id)
            recording = client.recordings(recording_sid).fetch()
            response.recording_sid = recording_sid
            response.recording_url = recording.uri
            response.recording_duration = recording.duration
            response.save()

            # Try to get the transcript
            try:
                # Get transcript for this recording
                transcript = client.transcriptions.list(recording_sid=recording_sid)
                if transcript:
                    response.transcript = transcript[0].transcription_text
                    response.transcript_status = 'completed'
                else:
                    response.transcript_status = 'pending'
            except Exception as e:
                logger.error(f"Error fetching transcript for recording {recording_sid}: {str(e)}")
                response.transcript_status = 'failed'
            response.save()

            # Create a new VoiceResponse for the next question
            resp = VoiceResponse()
            
            # Get questions from session or use default
            questions = request.session.get('questions', INTERVIEW_QUESTIONS)
            
            # Get current question index from session or initialize to 0
            current_index = request.session.get('current_question_index', 0)
            
            if current_index < len(questions):
                # Ask the next question
                resp.say(questions[current_index], voice='Polly.Amy')
                resp.record(
                    action=f'{settings.PUBLIC_URL}/voice/?response_id={response.id}',
                    maxLength='30',
                    playBeep=False,
                    trim='trim-silence'
                )
                
                # Increment the question index for next time
                request.session['current_question_index'] = current_index + 1
            else:
                # All questions have been asked
                resp.say("Thank you for your time. We will review your responses and get back to you soon.", voice='Polly.Amy')
                
                # Update all responses for this call to completed
                CallResponse.objects.filter(call_sid=call_sid).update(call_status='completed')
                
                # Reset the session
                request.session['current_question_index'] = 0
                if 'response_id' in request.session:
                    del request.session['response_id']
                if 'questions' in request.session:
                    del request.session['questions']
            
            return HttpResponse(str(resp))
            
        except CallResponse.DoesNotExist:
            logger.error(f"Response not found: {response_id}")
            return HttpResponse('Response not found', status=404)
            
    except Exception as e:
        logger.error(f"Error in recording_status view: {str(e)}")
        resp = VoiceResponse()
        resp.say("We're sorry, but there was an error processing your call. Please try again later.", voice='Polly.Amy')
        return HttpResponse(str(resp))

# HR Dashboard
@login_required
def dashboard(request):
    """Display call dashboard"""
    try:
        # Get all calls with their responses
        calls = CallResponse.objects.values('call_sid').distinct()
        call_records = []
        
        for call in calls:
            # Get the first response for each call to get call details
            first_response = CallResponse.objects.filter(call_sid=call['call_sid']).first()
            if first_response:
                # Get all responses for this call
                responses = CallResponse.objects.filter(call_sid=call['call_sid']).order_by('created_at')
                
                # Get transcripts for each response
                for response in responses:
                    if response.recording_sid and not response.transcript:
                        try:
                            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                            transcript = client.transcriptions.list(recording_sid=response.recording_sid)
                            if transcript:
                                response.transcript = transcript[0].transcription_text
                                response.transcript_status = 'completed'
                                response.save()
                        except Exception as e:
                            logger.error(f"Error fetching transcript for recording {response.recording_sid}: {str(e)}")
                
                call_records.append({
                    'phone_number': first_response.phone_number,
                    'call_sid': first_response.call_sid,
                    'call_status': first_response.call_status,
                    'created_at': first_response.created_at,
                    'recording_duration': first_response.recording_duration,
                    'responses': responses
                })
        
        # Calculate statistics
        total_calls = len(call_records)
        completed_calls = CallResponse.objects.filter(call_status='completed').values('call_sid').distinct().count()
        total_responses = CallResponse.objects.count()
        completed_transcripts = CallResponse.objects.filter(transcript_status='completed').count()
        
        context = {
            'call_records': call_records,
            'total_calls': total_calls,
            'completed_calls': completed_calls,
            'total_responses': total_responses,
            'completed_transcripts': completed_transcripts
        }
        
        return render(request, 'call/dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Error in dashboard view: {str(e)}")
        messages.error(request, "Error loading dashboard")
        return redirect('home')

def index(request):
    """Render the main page"""
    return render(request, 'call/dashboard.html')

def test_config(request):
    """Test Twilio configuration and webhook URLs"""
    try:
        # Test Twilio credentials
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        account = client.api.accounts(settings.TWILIO_ACCOUNT_SID).fetch()
        
        # Get webhook URLs
        answer_url = f"{settings.PUBLIC_URL}/answer/"
        voice_url = f"{settings.PUBLIC_URL}/voice/"
        
        # Test database connection
        call_count = CallResponse.objects.count()
        
        config_info = {
            'twilio_account_sid': settings.TWILIO_ACCOUNT_SID,
            'twilio_auth_token': 'Configured' if settings.TWILIO_AUTH_TOKEN else 'Not Configured',
            'twilio_phone_number': settings.TWILIO_PHONE_NUMBER,
            'public_url': settings.PUBLIC_URL,
            'answer_webhook': answer_url,
            'voice_webhook': voice_url,
            'database_connection': 'Connected' if call_count is not None else 'Error',
            'total_calls': call_count,
            'debug_mode': settings.DEBUG,
        }
        
        return render(request, 'call/test_config.html', {'config': config_info})
        
    except Exception as e:
        logger.error(f"Error in test_config: {str(e)}")
        return render(request, 'call/test_config.html', {
            'error': str(e),
            'config': {
                'twilio_account_sid': settings.TWILIO_ACCOUNT_SID,
                'twilio_auth_token': 'Configured' if settings.TWILIO_AUTH_TOKEN else 'Not Configured',
                'twilio_phone_number': settings.TWILIO_PHONE_NUMBER,
                'public_url': settings.PUBLIC_URL,
                'debug_mode': settings.DEBUG,
            }
        })

def view_response(request, response_id):
    """Display the details of a specific response"""
    response = CallResponse.objects.get(id=response_id)
    return render(request, 'call/view_response.html', {'response': response})

def export_to_excel(request):
    try:
        # Get all responses
        responses = CallResponse.objects.all().order_by('-created_at')
        
        # Create a DataFrame
        data = []
        for response in responses:
            data.append({
                'Phone Number': response.phone_number,
                'Question': response.question or 'N/A',
                'Response': response.response or 'N/A',
                'Recording URL': response.recording_url or 'N/A',
                'Recording Duration (seconds)': response.recording_duration or 'N/A',
                'Transcript': response.transcript or 'N/A',
                'Transcript Status': response.transcript_status,
                'Call SID': response.call_sid or 'N/A',
                'Call Duration (seconds)': response.call_duration or 'N/A',
                'Call Status': response.call_status or 'N/A',
                'Created At': response.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'Updated At': response.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        
        df = pd.DataFrame(data)
        
        # Create Excel writer
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Call Responses', index=False)
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Call Responses']
            
            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column = [cell for cell in column]
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column[0].column_letter].width = adjusted_width
        
        # Set up the response
        output.seek(0)
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=call_responses.xlsx'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting to Excel: {str(e)}")
        messages.error(request, f"Error exporting to Excel: {str(e)}")
        return redirect('dashboard')

@csrf_exempt
def voice(request):
    """Handle voice response and ask next question"""
    try:
        # Get the call SID from the request
        call_sid = request.POST.get('CallSid')
        if not call_sid:
            logger.error("No CallSid provided in request")
            return HttpResponse('No CallSid provided', status=400)

        # Get the response ID from the URL parameters
        response_id = request.GET.get('response_id')
        if not response_id:
            logger.error("No response_id provided in request")
            return HttpResponse('No response_id provided', status=400)

        logger.info(f"Processing voice response for call {call_sid} with response_id {response_id}")
        
        # Initialize Twilio client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Get call details
        call = client.calls(call_sid).fetch()
        
        # Get the recording SID from the request
        recording_sid = request.POST.get('RecordingSid')
        if recording_sid:
            # Update the previous response with recording details
            try:
                response = CallResponse.objects.get(id=response_id)
                recording = client.recordings(recording_sid).fetch()
                response.recording_sid = recording_sid
                response.recording_url = recording.uri
                response.recording_duration = recording.duration
                response.save()

                # Get the transcript from Twilio
                try:
                    # Get the recording's transcript
                    transcript = client.transcriptions.list(recording_sid=recording_sid)
                    if transcript:
                        response.transcript = transcript[0].transcription_text
                        response.transcript_status = 'completed'
                        logger.info(f"Transcript saved for recording {recording_sid}")
                    else:
                        response.transcript_status = 'pending'
                        logger.info(f"No transcript available for recording {recording_sid}")
                except Exception as e:
                    logger.error(f"Error fetching transcript: {str(e)}")
                    response.transcript_status = 'failed'
                response.save()
            except CallResponse.DoesNotExist:
                logger.error(f"Response not found: {response_id}")
        
        # Get current question index from session or initialize to 0
        current_index = request.session.get('current_question_index', 0)
        
        # Create response object
        resp = VoiceResponse()
        
        # Check if we have more questions to ask
        if current_index < len(INTERVIEW_QUESTIONS):
            # Get the current question
            question = INTERVIEW_QUESTIONS[current_index]
            
            # Create a new CallResponse record
            response = CallResponse.objects.create(
                phone_number=call.to,
                call_sid=call_sid,
                question=question,
                call_status='in-progress'
            )
            
            # Store the response ID in the session
            request.session['response_id'] = response.id
            
            # Add a short pause before asking the question
            resp.pause(length=0.5)
            
            # Ask the question
            resp.say(question, voice='Polly.Amy')
            
            # Add a short pause after the question
            resp.pause(length=0.5)
            
            # Record the response
            resp.record(
                action=f'{settings.PUBLIC_URL}/voice/?response_id={response.id}',
                maxLength='30',
                playBeep=False,
                trim='trim-silence'
            )
            
            # Increment the question index for next time
            request.session['current_question_index'] = current_index + 1
            
            logger.info(f"Generated TwiML for next question {current_index + 1} for call {call_sid}")
            
        else:
            # All questions have been asked
            resp.say("Thank you for your time. We will review your responses and get back to you soon.", voice='Polly.Amy')
            
            # Update all responses for this call to completed
            CallResponse.objects.filter(call_sid=call_sid).update(call_status='completed')
            
            # Reset the session
            request.session['current_question_index'] = 0
            if 'response_id' in request.session:
                del request.session['response_id']
            
            logger.info(f"Call {call_sid} completed successfully")
        
        return HttpResponse(str(resp))
        
    except Exception as e:
        logger.error(f"Error in voice view: {str(e)}")
        resp = VoiceResponse()
        resp.say("We're sorry, but there was an error processing your call. Please try again later.", voice='Polly.Amy')
        return HttpResponse(str(resp))

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

@csrf_exempt
def call_status(request):
    """Handle call status updates"""
    try:
        call_sid = request.POST.get('CallSid')
        call_status = request.POST.get('CallStatus')
        
        if call_sid and call_status:
            # Update all responses for this call with the new status
            CallResponse.objects.filter(call_sid=call_sid).update(call_status=call_status)
            logger.info(f"Updated call {call_sid} status to {call_status}")
        
        return HttpResponse(status=200)
    except Exception as e:
        logger.error(f"Error in call_status view: {str(e)}")
        return HttpResponse(status=500)