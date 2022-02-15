# pd-oncall-slack-topic

A slightly modified version of [pagerduty/pd-oncall-chat-topic](https://github.com/PagerDuty/pd-oncall-chat-topic) that takes a list PD Schedule/Slack Channels as a JSON environment variable instead of reading from a database, and without any of the infrastructure code.
![flow diagram](./docs/flow.png 'Flow Diagram')

Given the following environment variables:

- `PAGERDUTY_API_KEY` - key from https://support.pagerduty.com/docs/api-access-keys
- `SLACK_API_KEY` - key from https://api.slack.com/authentication/basics. App user must be invited to channels you want to set topics for
- `SCHEDULE_CONFIG` - list of objects providing a slack_channel_id and a comma-separated list of pd_schedule_ids to be updated with shift changes for that schedule:

  `'[{"slack_channel_id": "foo", "pd_schedule_id": "bar"}]'`

  > slack_channel_id is displayed in the channel's details at the bottom of the modal.
  > pd_schedule_id is displayed in the URL from PagerDuty UI: People -> On-call Schedules -> Select a schedule. The ID will be in the URL https://<your-account>.pagerduty.com/schedules#<SCHEDULE-ID>
  > The script will update the Slack channel topic to say `<User> is on-call for <Schedule>`

## How to run

1. `pip install -r requirements.txt`
2. Set and export variables in `.env.sample`. Rename to gitignored `.env` if you use a dotenv tool.
3. Run `python main.py`

> `./main.py` defines a `handler` function that can be used by AWS Lambda or GCP Cloud Functions
