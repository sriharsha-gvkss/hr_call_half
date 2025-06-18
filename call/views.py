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
import csv

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

# Load questions from JSON file
def load_questions():
    try:
        with open('questions.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("questions.json not found, using default questions")
        return [
            "Hi, what is your full name?",
            "What is your work experience?",
            "What was your previous job role?",
            "Why do you want to join our company?"
        ]

INTERVIEW_QUESTIONS = load_questions()

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
        
        # Initialize session state for this call
        request.session['current_question_index'] = 0
        request.session['call_sid'] = call_sid
        
        # Create TwiML response
        resp = VoiceResponse()
        
        # Welcome message
        resp.say("Welcome to the HR interview. Let's begin.", voice='Polly.Amy')
        resp.pause(length=1)
        
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
        
        # Ask the question
        gather = Gather(input='speech', action=f'{settings.PUBLIC_URL}/voice/?response_id={response.id}', 
                       method='POST', timeout=5)
        gather.say(question, voice='Polly.Amy')
        resp.append(gather)
        
        logger.info(f"Initialized call {call_sid} with first question")
        return HttpResponse(str(resp))
        
    except Exception as e:
        logger.error(f"Error in answer view: {str(e)}")
        resp = VoiceResponse()
        resp.say("We're sorry, but there was an error processing your call. Please try again later.", voice='Polly.Amy')
        return HttpResponse(str(resp))

def fetch_transcript_with_retry(recording_sid, max_retries=3, delay=5):
    """Fetch transcript for a recording with retries and error handling"""
    for attempt in range(max_retries):
        try:
            # Get the recording
            recording = client.recordings(recording_sid).fetch()
            
            # Get transcriptions for the recording
            transcriptions = client.transcriptions.list(recording_sid=recording_sid)
            
            if transcriptions:
                # Get the most recent transcription
                transcription = transcriptions[0]
                
                # Check if transcription is complete
                if transcription.status == 'completed':
                    return {
                        'status': 'completed',
                        'text': transcription.text
                    }
                elif transcription.status == 'failed':
                    return {
                        'status': 'failed',
                        'text': None
                    }
            
            # If we get here, either no transcriptions or still processing
            if attempt < max_retries - 1:
                time.sleep(delay)
                continue
                
            return {
                'status': 'pending',
                'text': None
            }
            
        except Exception as e:
            logger.error(f"Error fetching transcript (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(delay)
                continue
            return {
                'status': 'failed',
                'text': None
            }

def update_transcript_for_response(response):
    """Update transcript for a specific response"""
    if not response.recording_sid:
        logger.warning(f"No recording SID for response {response.id}")
        return False
        
    try:
        result = fetch_transcript_with_retry(response.recording_sid)
        
        if result['status'] == 'completed':
            response.transcript = result['text']
            response.transcript_status = 'completed'
            response.save()
            logger.info(f"Updated transcript for response {response.id}")
            return True
        elif result['status'] == 'failed':
            response.transcript_status = 'failed'
            response.save()
            logger.warning(f"Failed to get transcript for response {response.id}")
            return False
        else:
            response.transcript_status = 'pending'
            response.save()
            logger.info(f"Transcript pending for response {response.id}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating transcript for response {response.id}: {str(e)}")
        return False

@csrf_exempt
def transcription_webhook(request):
    """Handle incoming transcription data from Twilio"""
    try:
        data = json.loads(request.body)
        logger.info(f"Received transcription webhook: {data}")
        
        # Extract relevant data
        recording_sid = data.get('RecordingSid')
        transcription_text = data.get('TranscriptionText')
        transcription_status = data.get('TranscriptionStatus')
        
        if not recording_sid:
            logger.error("No RecordingSid in transcription webhook")
            return HttpResponse(status=400)
            
        # Find the response with this recording SID
        try:
            response = CallResponse.objects.get(recording_sid=recording_sid)
        except CallResponse.DoesNotExist:
            logger.error(f"No response found for recording {recording_sid}")
            return HttpResponse(status=404)
            
        # Update the response with transcription data
        if transcription_status == 'completed' and transcription_text:
            response.transcript = transcription_text
            response.transcript_status = 'completed'
            response.save()
            logger.info(f"Updated transcript for response {response.id}")
        elif transcription_status == 'failed':
            response.transcript_status = 'failed'
            response.save()
            logger.warning(f"Transcription failed for response {response.id}")
            
        return HttpResponse(status=200)
        
    except Exception as e:
        logger.error(f"Error in transcription webhook: {str(e)}")
        return HttpResponse(status=500)

@login_required
def retry_transcription(request, response_id):
    """Manually trigger transcription for a specific response"""
    try:
        response = CallResponse.objects.get(id=response_id)
        
        if response.transcript_status == 'completed':
            messages.warning(request, "Transcription is already completed")
            return redirect('dashboard')
            
        success = update_transcript_for_response(response)
        
        if success:
            messages.success(request, "Transcription updated successfully")
        else:
            messages.warning(request, "Transcription is still processing or failed")
            
        return redirect('dashboard')
        
    except CallResponse.DoesNotExist:
        messages.error(request, "Response not found")
        return redirect('dashboard')
    except Exception as e:
        logger.error(f"Error retrying transcription: {str(e)}")
        messages.error(request, "Error updating transcription")
        return redirect('dashboard')

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

@login_required
def export_to_excel(request):
    """Export call responses to Excel"""
    try:
        # Get all completed responses
        responses = CallResponse.objects.filter(call_status='completed').order_by('created_at')
        
        # Create a DataFrame
        data = []
        for response in responses:
            data.append({
                'Phone Number': response.phone_number,
                'Question': response.question,
                'Response': response.response,
                'Transcript': response.transcript,
                'Recording Duration': response.recording_duration,
                'Created At': response.created_at
            })
        
        df = pd.DataFrame(data)
        
        # Create Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Responses', index=False)
            
            # Auto-adjust columns width
            worksheet = writer.sheets['Responses']
            for i, col in enumerate(df.columns):
                max_length = max(df[col].astype(str).apply(len).max(), len(col)) + 2
                worksheet.set_column(i, i, max_length)
        
        output.seek(0)
        
        # Create the response
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=call_responses.xlsx'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting to Excel: {str(e)}")
        messages.error(request, "Error exporting data to Excel")
        return redirect('dashboard')

@csrf_exempt
def voice(request):
    """Handle voice responses and ask next question"""
    try:
        # Get the call SID from the request
        call_sid = request.POST.get('CallSid')
        if not call_sid:
            logger.error("No CallSid provided in request")
            return HttpResponse('No CallSid provided', status=400)
            
        # Get the response ID from the URL
        response_id = request.GET.get('response_id')
        if not response_id:
            logger.error("No response_id provided in request")
            return HttpResponse('No response_id provided', status=400)
            
        # Get the current response
        try:
            current_response = CallResponse.objects.get(id=response_id)
        except CallResponse.DoesNotExist:
            logger.error(f"Response {response_id} not found")
            return HttpResponse('Response not found', status=404)
            
        # Get the speech result
        speech_result = request.POST.get('SpeechResult', '').strip()
        if speech_result:
            logger.info(f"Received answer for question {current_response.question}: {speech_result}")
            current_response.response = speech_result
            current_response.save()
            
            # Save to CSV for backup
            with open('responses.csv', 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([current_response.question, speech_result])
        
        # Get the current question index from the session
        current_index = request.session.get('current_question_index', 0)
        
        # Create TwiML response
        resp = VoiceResponse()
        
        # Check if we have more questions to ask
        if current_index + 1 < len(INTERVIEW_QUESTIONS):
            # Get the next question
            next_index = current_index + 1
            question = INTERVIEW_QUESTIONS[next_index]
            
            # Create a new CallResponse record
            response = CallResponse.objects.create(
                phone_number=current_response.phone_number,
                call_sid=call_sid,
                question=question,
                call_status='in-progress'
            )
            
            # Store the response ID in the session
            request.session['response_id'] = response.id
            
            # Update the question index for next time
            request.session['current_question_index'] = next_index
            
            # Ask the question
            gather = Gather(input='speech', action=f'{settings.PUBLIC_URL}/voice/?response_id={response.id}', 
                           method='POST', timeout=5)
            gather.say(question, voice='Polly.Amy')
            resp.append(gather)
            
            logger.info(f"Generated TwiML for question {next_index + 1} for call {call_sid}")
        else:
            # All questions have been asked
            resp.say("Thank you for your time. The interview is now complete.", voice='Polly.Amy')
            
            # Update all responses for this call to completed
            CallResponse.objects.filter(call_sid=call_sid).update(call_status='completed')
            
            # Clean up session
            request.session.flush()
            
            logger.info(f"Completed call {call_sid}")
        
        return HttpResponse(str(resp))
        
    except Exception as e:
        logger.error(f"Error in voice view: {str(e)}")
        resp = VoiceResponse()
        resp.say("We're sorry, but there was an error processing your response. Please try again later.", voice='Polly.Amy')
        return HttpResponse(str(resp))

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

@login_required
def download_csv(request):
    """Download responses as CSV"""
    try:
        # Get all completed responses
        responses = CallResponse.objects.filter(call_status='completed').order_by('created_at')
        
        # Create the response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=call_responses.csv'
        
        # Create CSV writer
        writer = csv.writer(response)
        writer.writerow(['Question', 'Response', 'Transcript', 'Created At'])
        
        # Write data
        for response_obj in responses:
            writer.writerow([
                response_obj.question,
                response_obj.response,
                response_obj.transcript,
                response_obj.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading CSV: {str(e)}")
        messages.error(request, "Error downloading CSV file")
        return redirect('dashboard')