import requests
import json
import sys
import os.path
import time
from datetime import datetime, timedelta

with open('credentials.json', 'r') as f:
    creds = json.load(f)

METRA_AUTH = (creds['metraClient'], creds['metraSecret'])
HOST = 'https://gtfsapi.metrarail.com/gtfs'
SLACK_URL = 'https://hooks.slack.com/services/' + creds['slackHook']
HEADERS = {'Content-Type': 'application/json'}
RED = '#D00000'
GREEN = '#00D000'
MAGENTA = '#FF00FF'
TIME_FORMAT = '%H:%M'

delayed_template = '{adjust_time} arrival for {normal_time} {direction} train. ({delay})'
normal_template = '{normal_time} {direction} train is arriving on time.'

def get(endpoint):
    resp = requests.get(HOST + endpoint, auth=METRA_AUTH)
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
    resp = requests.post(SLACK_URL, data=json.dumps(slack_payload), headers=HEADERS)
    print(resp)

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
                    return y['arrival']['delay']
    return 0

if len(sys.argv) != 2:
    print('Usage: python {0} input.json'.format(sys.argv[0]))
    sys.exit(1) 
path = sys.argv[1]
if not os.path.isfile(path):
    print(sys.argv[1] + ' is not a valid file.')
    sys.exit(2) 

# TODO Parameterize sleep values
sleep_duration = 30 # how long to sleep between polls
sleep_counter = 60 # how many times to poll

inputs = load_input(path)
load_stop_times()
while True:
    for i in inputs:
        stop_id = i['stop_id']
        stop_time = i['stop_time']
        trip_id = i['trip_id']
        direction = i['direction']
        normal_arrival = datetime.strptime(stop_time, TIME_FORMAT)
        normal_time = stop_time
        delay = get_delays(trip_id, stop_id)
        # delay = 260 # can hardcode delays here for testing
        if delay != 0:
            delay_time = timedelta(seconds=abs(delay))
            adjust_arrival = normal_arrival + (delay_time * (-1 if delay < 0 else 1))
            adjust_time = adjust_arrival.strftime(TIME_FORMAT)
            text = delayed_template.format(
                normal_time=normal_time, 
                direction=direction, 
                adjust_time=adjust_time, 
                delay=('+' if delay > 0 else '-') + str(delay_time)
            )
            color = RED
        else:
            text = normal_template.format(
                normal_time=normal_time,
                direction=direction,
            )
            color = GREEN
        post_slack(title=stop_id,text=text,color=color)

    if sleep_counter > 0:
        sleep_counter -= 1
        time.sleep(sleep_duration)
        trip_updates = None
    else:
        break
        