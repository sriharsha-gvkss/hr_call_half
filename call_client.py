from twilio.rest import Client
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get Twilio credentials from environment variables
account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone = os.getenv('TWILIO_PHONE_NUMBER')

client = Client(account_sid, auth_token)

def make_call(to_number, question):
    call = client.calls.create(
        to=to_number,
        from_=twilio_phone,
        url=f'https://YOUR_SERVER_URL/answer/?q={question}'
    )
    return call.sid 