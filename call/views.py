from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from twilio.twiml.voice_response import VoiceResponse, Record, Say
from twilio.rest import Client
from django.conf import settings
from urllib.parse import quote
from .models import Recording
import re
from django.views.decorators.http import require_http_methods
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Initialize Twilio client with environment variables
client = Client(
    os.getenv('TWILIO_ACCOUNT_SID'),
    os.getenv('TWILIO_AUTH_TOKEN')
)

# Public URL for webhooks - Replace this with your actual public URL
PUBLIC_URL = "https://your-public-url.ngrok.io"  # You'll need to replace this with your actual ngrok URL

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
        question = request.POST.get('question')
        
        if not phone_number or not question:
            return JsonResponse({'error': 'Phone number and question are required'}, status=400)
        
        # Format phone number
        formatted_number = format_phone_number(phone_number)
        
        # Create webhook URL
        webhook_url = f"{request.scheme}://{request.get_host()}/answer/?q={question}"
        
        # Make the call
        call = client.calls.create(
            to=formatted_number,
            from_=os.getenv('TWILIO_PHONE_NUMBER'),
            url=webhook_url
        )
        
        return JsonResponse({
            'message': 'Call initiated successfully',
            'call_sid': call.sid
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# Answer call with questions
@csrf_exempt
@require_http_methods(["POST"])
def answer_call(request):
    try:
        # Get the question from the URL
        question = request.GET.get('q', '')
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Add the question
        response.say(f"Hello, I have a question for you: {question}")
        
        # Record the response
        response.record(
            action=f"/save-recording/?q={question}",
            maxLength="60",
            playBeep=True
        )
        
        return HttpResponse(str(response), content_type='text/xml')
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# Handle recorded answer
@csrf_exempt
@require_http_methods(["POST"])
def save_recording(request):
    try:
        # Get the recording URL and question
        recording_url = request.POST.get('RecordingUrl')
        question = request.GET.get('q', '')
        
        if not recording_url:
            return JsonResponse({'error': 'No recording URL provided'}, status=400)
        
        # Save the recording
        recording = Recording.objects.create(
            question=question,
            recording_url=recording_url,
            created_at=datetime.now()
        )
        
        return JsonResponse({'message': 'Recording saved successfully'})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# HR Dashboard
def dashboard(request):
    data = Recording.objects.all().order_by('-created_at')
    return render(request, 'dashboard.html', {'recordings': data})

def index(request):
    """Render the main page"""
    recordings = Recording.objects.all().order_by('-created_at')
    return render(request, 'index.html', {'recordings': recordings})

def test_config(request):
    config = {
        'TWILIO_ACCOUNT_SID': os.getenv('TWILIO_ACCOUNT_SID'),
        'TWILIO_AUTH_TOKEN': os.getenv('TWILIO_AUTH_TOKEN'),
        'TWILIO_PHONE_NUMBER': os.getenv('TWILIO_PHONE_NUMBER'),
    }
    return JsonResponse(config)