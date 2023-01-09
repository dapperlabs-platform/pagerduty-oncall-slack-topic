
import os
from requests import get, post
import threading
import logging
from datetime import datetime, timezone, timedelta
import json
from google.cloud import secretmanager

# semaphore limit of 5, picked this number arbitrarily
maxthreads = 5
sema = threading.Semaphore(value=maxthreads)

smclient = secretmanager.SecretManagerServiceClient()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

ONCALL_CONFIG_NEW = os.environ['ONCALL_CONFIG_NEW']
PAGERDUTY_API_KEY = smclient.access_secret_version(
    request={"name": os.environ['PAGERDUTY_API_KEY_SECRET_NAME']}).payload.data.decode("UTF-8") if os.getenv('PAGERDUTY_API_KEY') is None else os.environ['PAGERDUTY_API_KEY']
SLACK_API_KEY = smclient.access_secret_version(
    request={"name": os.environ['SLACK_API_KEY_SECRET_NAME']}).payload.data.decode("UTF-8") if os.getenv('SLACK_API_KEY') is None else os.environ['SLACK_API_KEY']
user_ids = []

# Gets user on calls email from PD schedule ID
def get_user(schedule_id):
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': f"Token token={PAGERDUTY_API_KEY}"
    }
    normal_url = f'https://api.pagerduty.com/schedules/{schedule_id}/users'
    # This value should be less than the running interval
    # It is best to use UTC for the datetime object
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=1)  # One minute ago
    payload = {}
    payload['since'] = since.isoformat()
    payload['until'] = now.isoformat()
    normal = get(normal_url, headers=headers, params=payload)
    if normal.status_code == 404:
        logger.critical(f"ABORT: Not a valid schedule: {schedule_id}")
        return False
    try:
        return normal.json()['users'][0]
    except IndexError:
        print(f"No user found for schedule {schedule_id}")

# Looks up user by email and returns userID
def get_user_id(email):
    payload = {}
    payload['token'] = SLACK_API_KEY
    payload['email'] = email
    try:
        r = post('https://slack.com/api/users.lookupByEmail', data=payload)
        current = r.json()['user']['id']
        logger.debug("User ID: '{}'".format(current))
        return current
    except KeyError:
        logger.critical('Failed to get user')

# Adds users to Slack group based on their Slack ID
def add_users_to_group(user_ids,groupid):
    payload = {}
    payload['token'] = SLACK_API_KEY
    payload['usergroup'] = groupid
    payload['users'] = str(user_ids)
    try:
        r = post('https://slack.com/api/usergroups.users.update',data=payload)
        logger.debug("Response for '{}' was: {}".format(groupid,user_ids, r.json()))
        print('Success')
    except KeyError:
        logger.critical("Failed to add user to group")

# do work for on-call people
def oncall(obj):
    for pd_oncall_schedule_id in obj['pd_oncall_id']:
        try:
            user = get_user(pd_oncall_schedule_id)
            userid = get_user_id(user['email'])
        except KeyError:
            logger.critical("Nope, Doesn't Work")
    add_users_to_group(userid, obj['oncall_slack_group_id'])

# do work for support people
def support(obj):
    for pd_support_schedule_id in obj['pd_support_id'].split(','):
        try:
            user = get_user(pd_support_schedule_id)
            user_ids.append(get_user_id(user['email']))
        except KeyError:
            logger.critical("NOPE, doesn't work")   
    add_users_to_group(user_ids, obj['support_slack_group_id'])

def handler(request,event):
    config = json.loads(ONCALL_CONFIG_NEW)
    threads_oncall = []
    for schedule in config:
        thread_oncall = threading.Thread(target=oncall, args=(schedule,))
        threads_oncall.append(thread_oncall)
    [t.start() for t in threads_oncall]
    [t.join() for t in threads_oncall]
    threads_support = []
    for schedule in config:
        thread_support = threading.Thread(target=support, args=(schedule,))
        threads_support.append(thread_support)
    [t.start() for t in threads_support]
    [t.join() for t in threads_support]


    return 0

if __name__ == "__main__":
    handler(None,None)
