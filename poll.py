from botocore.vendored import requests
from datetime import datetime, timedelta, timezone
import json
import sys
import os.path
import time

with open('credentials.json', 'r') as f:
    creds = json.load(f)

METRA_AUTH = (creds['metraClient'], creds['metraSecret'])
METRA_URL = 'https://gtfsapi.metrarail.com/gtfs'
SLACK_URL = 'https://hooks.slack.com/services/' + creds['slackHook']
CALENDAR_URL = 'https://www.googleapis.com/calendar/v3/calendars/' + creds['googleCalendar']
GOOGLE_KEY = creds['googleKey']
RED = '#D00000'
YELLOW = '#D0D000'
GREEN = '#00D000'
MAGENTA = '#FF00FF'
TIME_FORMAT = '%H:%M'

delayed_template = '{adjust_time} arrival for {normal_time} {direction} train. ({delay})'
normal_template = '{normal_time} {direction} train is arriving on time.'

def get(endpoint):
    resp = requests.get(METRA_URL + endpoint, auth=METRA_AUTH)
    return resp.json()

def pretty(obj):
    return json.dumps(obj, sort_keys=True, indent=4, separators=(',',': '))
    
def post_slack(title='', text='', color=MAGENTA):
    slack_payload = { 
        'username': 'Metra Updates',
        'channel': '#metra',
        'icon_emoji': ':steam_locomotive:',
        'attachments': [
            {
                'fallback': text,
                'color': color,
                'fields': [
                    {
                        'title': title,
                        'value': text,
                        'short': False
                    }
                ]
            }
        ]
    }
    requests.post(SLACK_URL, data=json.dumps(slack_payload), headers={'Content-Type': 'application/json'})

def load_input(path):
    with open(path,'r') as f:
        favorites = json.load(f)
    # TODO Add validation that input is the data expected.
    return favorites

stop_times_path = 'stop_times.json'
def load_stop_times(local=True):
    global stop_times
    if local and os.path.isfile(stop_times_path):
        print('Using local stop times.')
        with open(stop_times_path, 'r') as f:
            stop_times = json.load(f)
    else:
        print('Fetching remote stop times.')
        stop_times = get('/schedule/stop_times')
        with open(stop_times_path, 'w') as f:
            json.dump(stop_times, f)

def find_trip_id(stop_id, stop_time):
    load_stop_times()
    arrival_time = stop_time + ':00' # add seconds
    for x in stop_times:
        if x['stop_id'] == stop_id and x['arrival_time'] == arrival_time: 
            return x['trip_id']
    return None

trip_updates = None # reset to None when want to refresh
def get_delays(trip_id, stop_id):
    global trip_updates
    if trip_updates is None:
        trip_updates = get('/tripUpdates')
    for x in trip_updates:
        if x['id'] == trip_id:
            for y in x['trip_update']['stop_time_update']:
                if  y['stop_id'] == stop_id:
                    return y['arrival']['delay'] # arrival.time.low
    return 0

def lambda_handler(event, context):
    load_stop_times(local=True)
    now = datetime.utcnow()
    last_hour = now - timedelta(hours=3)
    next_hour = now + timedelta(hours=3)
    # next_day = datetime(now.year, now.month, now.day) + timedelta(days=1) # copy without time components
    params = {
        'key': GOOGLE_KEY,
        'timeMin': last_hour.isoformat('T') + 'Z',
        'timeMax': next_hour.isoformat('T') + 'Z',
        'singleEvents': True # expands recurring events into their own objects.
    }
    r = requests.get(CALENDAR_URL + '/events', params=params)
    for i in r.json()['items']:
        data = i['description'].split('\n')
        trip_id = data[0]
        stop_id = data[1]
        for x in stop_times:
            if x['trip_id'] == trip_id and x['stop_id'] == stop_id:
                stop_time = x['arrival_time'][:-3]
        previous_arrival = datetime.strptime(i['start']['dateTime'] , '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
        normal_arrival = datetime.strptime(stop_time, TIME_FORMAT).replace(year=previous_arrival.year, month=previous_arrival.month, day=previous_arrival.day)
        normal_time = stop_time
        direction = 'inbound' if normal_arrival.hour < 12 else 'outbound' # TODO Assumes all trains before noon are inbound, which isn't true.
        delay = get_delays(trip_id, stop_id)
        # delay = 260 # can hardcode delays here for testing
        delay_time = timedelta(seconds=abs(delay))
        adjust_arrival = normal_arrival + (delay_time * (-1 if delay < 0 else 1))
        adjust_time = adjust_arrival.strftime(TIME_FORMAT)
        difference = (adjust_arrival - previous_arrival).total_seconds()
        if difference != 0:
            # TODO Update Calendar Event with New Arrival Time
            color = YELLOW if difference < 0 else RED
            print(difference, delay)
            if delay == 0:
                color = GREEN
                text = normal_template.format(
                    normal_time=normal_time,
                    direction=direction,
                )
            else:
                text = delayed_template.format(
                    normal_time=normal_time, 
                    direction=direction, 
                    adjust_time=adjust_time, 
                    delay=('+' if delay > 0 else '-') + str(delay_time)
                )
            post_slack(title=stop_id,text=text,color=color)
        
    return {
        'statusCode': 200,
    }
