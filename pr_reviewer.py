import hashlib
import os
import json
import requests
import ast
import hmac
from openai import OpenAI

# Configuration from environment variables
TOKEN = os.getenv('TOKEN', '<github PAT>')
REPO_OWNER = os.getenv('REPO_OWNER', 'Rupeek')
TOKEN_OPENAI = os.getenv('TOKEN_OPENAI', '<Openai key>')
WEBHOOK_SECRET = 'secret'

openai_client = OpenAI(
    organization='org-8HnXwbIJshIXURi2kHdzNmqI',
    api_key=f'{TOKEN_OPENAI}',
)

# Headers for GitHub API
def get_headers():
    return {
        'Authorization': f'token {TOKEN}',
        'Accept': 'Accept: application/vnd.github.v3.diff',
    }

# Function to get the files changed in a specific pull request
def get_patch_from_pr(pr_number, repo_name):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}'
    # print(url)
    response = requests.get(url, headers=get_headers())
    return response.text

def get_context(patch):
    prompt = ''
    # Open the prompt file and read its contents into a variable
    with open('prompt.txt', 'r') as file:
        prompt = file.read()
    return prompt + patch


# Function to post a review comment on a pull request
def post_review_comment(body, pr_number, repo_name):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}/reviews'
    data = {
        "body": body,
        "event": "COMMENT"
    }
    response = requests.post(url, headers=get_headers(), data=json.dumps(data))
    return response.json()


# Function to get the files changed in a specific pull request
def get_pull_request_files(pr_number, repo_name):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}/files'
    response = requests.get(url, headers=get_headers())
    return response.json()

def verify_signature(payload, signature, secret):
    """Verify GitHub webhook signature."""
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = 'sha256=' + mac.hexdigest()
    #print(expected_signature)
    #print(signature)
    return hmac.compare_digest(expected_signature, signature)


def authenticate_request(event, context):
    #print(event)
    authenticated = True
    response = ''
    headers = event['headers']
    signature = headers.get('x-hub-signature-256')
    if signature is None:
        authenticated = False
        response = {
            'statusCode': 400,
            'body': 'Missing signature'
        }

    # Verify the payload with the secret
    payload = event['body'].encode()
    if not verify_signature(payload, signature, WEBHOOK_SECRET):
        authenticated = False
        response = {
            'statusCode': 400,
            'body': 'Invalid signature'
        }

    return authenticated, response


def lambda_handler(event, context):

    authenticated, response = authenticate_request(event, context)
    if not authenticated:
        return response
    
    pr_number = ''
    repo_name = ''
    try:
        payload = json.loads(event['body'])
    except KeyError:
        print(f'event is {event}')
        return {
            'statusCode': 400,
            'body': json.dumps('Invalid payload format')
        }
    #print(payload)
    if payload.get('action') == 'opened' or payload.get('action') == 'synchronize':
        # Extract the pull request number and repository name
        pr_number = payload['pull_request']['number']
        repo_name = payload['repository']['name']

        # Log or process the pull request number and repository name
        print(f"Pull request opened: #{pr_number} in repository {repo_name}")

    else:
        # If the event is not a pull request event, return a 200 status code
        print('Not a pull request opened event. Received event' + str(event['headers']))
        return {
            'statusCode': 200,
            'body': json.dumps('Not a pull request opened event. Received event')
        }

    files = get_pull_request_files(pr_number, repo_name)
    openai_review_concatenated = openai_review_comments(files, pr_number, repo_name)
    post_review_comment(body=openai_review_concatenated, pr_number=pr_number, repo_name=repo_name)
    print(f'comment posted on #{pr_number} in repository {repo_name}')
    return {
        'statusCode': 200,
        'body': json.dumps(f'comment posted on #{pr_number} in repository {repo_name}')
    }


def openai_review_comments(files, pr_number, repo_name):
    openai_review_concatenated = ''
    if len(files) >= 10:
        num_batches = len(files) // 10
        batch_size = (len(files) + num_batches - 1) // num_batches
        batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]
        for batch in batches:
            concatenated_patch = ''.join(file.get('patch', '') for file in batch)
            openai_review_concatenated = openai_review_concatenated + " \n" + generate_openai(
                get_context(concatenated_patch))
    else:
        patch = get_patch_from_pr(pr_number, repo_name)
        context = get_context(patch)
        openai_review_concatenated = generate_openai(context)
    return openai_review_concatenated

def generate_openai(context):
    # with open('system.txt', 'r') as file:
    #     system = file.read()

    openai_response = ''
    stream = openai_client.chat.completions.create(
        model="gpt-4o",
        # messages=[{"role": "system", "content": system},{"role": "user", "content": context}],
        messages=[{"role": "user", "content": context}],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            openai_response = openai_response + chunk.choices[0].delta.content
    #print(openai_response)
    return openai_response

# if __name__ == '__main__':
#     with open('event.txt', 'r') as file:
#         event_text = file.read()

#     event = ast.literal_eval(event_text)
#     context = ''
#     lambda_handler(event, context)
