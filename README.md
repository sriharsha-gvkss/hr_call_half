# HR Team Call System

An automated interview system built with Django and Twilio that conducts phone interviews by asking predefined questions and recording responses.

## Features

- Automated phone interviews
- Question sequence management
- Response recording and transcription
- Dashboard for viewing responses
- Excel export functionality
- Configuration testing

## Setup

1. Clone the repository:
```bash
git clone https://github.com/sriharsha-gvkss/hr_call_half.git
cd hr_call_half
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables in `.env`:
```
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone_number
PUBLIC_URL=your_deployment_url
```

4. Run migrations:
```bash
python manage.py migrate
```

5. Start the development server:
```bash
python manage.py runserver
```

## Usage

1. Access the dashboard at `/dashboard/`
2. Enter a phone number to make a call
3. The system will:
   - Ask predefined questions
   - Record responses
   - Generate transcripts
   - Save all data

## Testing

Visit `/test-config/` to verify your configuration settings.

## License

MIT License 
