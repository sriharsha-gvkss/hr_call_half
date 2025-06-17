from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from twilio.twiml.voice_response import VoiceResponse, Record, Say
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
        question = request.POST.get('question')
        
        if not phone_number or not question:
            return JsonResponse({'error': 'Phone number and question are required'}, status=400)
        
        # Format phone number
        formatted_number = format_phone_number(phone_number)
        
        # Create webhook URL with proper encoding
        encoded_question = quote(question)
        webhook_url = f"{PUBLIC_URL}/answer/?q={encoded_question}"
        
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
def answer(request):
    """Handle incoming call and play question"""
    question = request.GET.get('q', '')
    phone_number = request.GET.get('phone', '')
    
    # If no question is provided, use a default question
    if not question:
        question = "Please tell us your full name, a brief self-introduction, your experience, and why you want to join our company."
    
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

# Handle recorded answer
@csrf_exempt
@require_http_methods(["POST"])
def recording_status(request):
    """Handle recording status callback"""
    response_id = request.GET.get('response_id')
    recording_url = request.POST.get('RecordingUrl')
    
    if response_id and recording_url:
        try:
            response = CallResponse.objects.get(id=response_id)
            response.recording_url = recording_url
            response.save()
            return HttpResponse('Recording saved successfully!')
        except CallResponse.DoesNotExist:
            return HttpResponse('Response not found.', status=404)
    
    return HttpResponse('No recording URL provided.', status=400)

# HR Dashboard
def dashboard(request):
    """Display dashboard with all responses"""
    responses = CallResponse.objects.all().order_by('-created_at')
    return render(request, 'call/dashboard.html', {'responses': responses})

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