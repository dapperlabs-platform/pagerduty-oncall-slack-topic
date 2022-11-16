#!/usr/bin/env python

import os
from datetime import datetime, timezone, timedelta
from requests import get, post
import threading
import logging
import re
import json
from google.cloud import secretmanager

# semaphore limit of 5, picked this number arbitrarily
maxthreads = 5
sema = threading.Semaphore(value=maxthreads)

smclient = secretmanager.SecretManagerServiceClient()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

# [{"slack_channel_id": "foo", "pd_schedule_id": "bar"},{"slack_channel_id": "boo", "pd_schedule_id": "baz,moz"}]
SCHEDULE_CONFIG = os.environ['SCHEDULE_CONFIG']
SLACK_TAG = os.environ['SLACK_TAG']
SLACK_GROUP_ID = os.environ['SLACK_GROUP_ID']
PAGERDUTY_API_KEY = smclient.access_secret_version(
    request={"name": os.environ['PAGERDUTY_API_KEY_SECRET_NAME']}).payload.data.decode("UTF-8") if os.getenv('PAGERDUTY_API_KEY') is None else os.environ['PAGERDUTY_API_KEY']
SLACK_API_KEY = smclient.access_secret_version(
    request={"name": os.environ['SLACK_API_KEY_SECRET_NAME']}).payload.data.decode("UTF-8") if os.getenv('SLACK_API_KEY') is None else os.environ['SLACK_API_KEY']

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
        #logger.critical(f"ABORT: Not a valid schedule: {schedule_id}")
        return False
    try:
        return normal.json()['users'][0]
    except IndexError:
        print(f"No user found for schedule {schedule_id}")


def get_pd_schedule_name(schedule_id):
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': f"Token token={PAGERDUTY_API_KEY}"
    }
    url = f'https://api.pagerduty.com/schedules/{schedule_id}'
    r = get(url, headers=headers)
    try:
        return r.json()['schedule']['name']
    except KeyError:
        logger.debug(r.status_code)
        logger.debug(r.json())
        return None


# Looks up user by email and returns userID
def get_user_id(email):
    payload = {}
    payload['token'] = SLACK_API_KEY
    payload['email'] = email
    try:
        r = post('https://slack.com/api/users.lookupByEmail', data=payload)
        current = r.json()['user']['id']
        logger.debug("Current Topic: '{}'".format(current))
        return current
    except KeyError:
        logger.critical('Failed to get user')


# Takes user ID and add them to on call group. This also automatically removes
# the previous person
def add_users_to_group(user_ids,groupid):
    payload = {}
    payload['token'] = SLACK_API_KEY
    payload['usergroup'] = groupid
    payload['users'] = user_ids
    try:
        r = post('https://slack.com/api/usergroups.users.update',data=payload)
        logger.debug("Response for '{}' was: {}".format(groupid,user_ids, r.json()))
        print('Success')
    except KeyError:
        logger.critical("Failed to add user to group")


def get_slack_topic(channel):
    payload = {}
    payload['token'] = SLACK_API_KEY
    payload['channel'] = channel
    try:
        r = post(
            'https://slack.com/api/conversations.info', data=payload)
        current = r.json()['channel']['topic']['value']
        logger.debug("Current Topic: '{}'".format(current))
        return current
    except KeyError:
        logger.critical(
            f"Could not find '{channel}' on slack, has the on-call bot been removed from this channel?")


def update_slack_topic(channel, proposed_update):
    logger.debug(
        f"Entered update_slack_topic() with: {channel} {proposed_update}")
    payload = {}
    payload['token'] = SLACK_API_KEY
    payload['channel'] = channel

    slack_topic = get_slack_topic(channel)

    if proposed_update != slack_topic:
        topic = proposed_update
        # slack limits topic to 250 chars
        if len(proposed_update) > 250:
            topic = proposed_update[0:247] + "..."
        payload['topic'] = topic
        r = post(
            'https://slack.com/api/conversations.setTopic', data=payload)
        logger.debug("Response for '{}' was: {}".format(channel, r.json()))
    else:
        logger.info("Not updating slack, topic is the same")
        return None


def do_work(obj):
    # entrypoint of the thread
    sema.acquire()
    logger.debug("Operating on {}".format(obj))
    topic = ""
    # 'pd_schedule_id' may contain multiple channels seperated by comma
    for schedule_id in obj['pd_schedule_id'].split(","):
        user = get_user(schedule_id)
        if user is not None:  # then it is valid and update the chat topic
            schedule_name = get_pd_schedule_name(schedule_id)
            topic += f"{user['name']} is on-call for {schedule_name} | "
            logger.debug(f"username={user['name']}, schedule_name={schedule_name}")
            get_user_id(user['email'])
            user_id = get_user_id(user['email'])
            add_users_to_group(user_id,SLACK_GROUP_ID)
    if topic != "":
        update_slack_topic(obj["slack_channel_id"], topic[0:-3])
    else:
        logger.info("Not updating slack, topic is empty")
    sema.release()


def handler(request, event):
    config = json.loads(SCHEDULE_CONFIG)
    threads = []
    for schedule in config:
        thread = threading.Thread(target=do_work, args=(schedule,))
        threads.append(thread)
    # Start threads and wait for all to finish
    [t.start() for t in threads]
    [t.join() for t in threads]

    return 0


if __name__ == "__main__":
    handler(None, None)