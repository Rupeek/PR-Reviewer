import hashlib
import os
import json
import requests
import ast
import hmac
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
# Configuration from environment variables
TOKEN = os.getenv('TOKEN')
REPO_OWNER = os.getenv('REPO_OWNER', 'Rupeek')
TOKEN_OPENAI = os.getenv('TOKEN_OPENAI')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')

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
    # print(response.text)
    return response.text

def get_context(patch):
    prompt = ''
    # Open the prompt file and read its contents into a variable
    with open('prompt.txt', 'r') as file:
        prompt = file.read()

    # print("prompt: ",prompt,"patch: ",patch)
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

    # authenticated, response = authenticate_request(event, context)
    # if not authenticated:
    #     return response
    
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
    # commit_id = fetch_commit_id(pr_number, repo_name)
    # print(commit_id)
    commit_id=payload['pull_request']['head']['sha']
    openai_review_concatenated = openai_review_comments(files, pr_number, repo_name)
    for i, review_comment in enumerate(openai_review_concatenated):
        body = review_comment.get('body')
        path = review_comment.get('path')
        start_line = review_comment.get('start_line')
        line = review_comment.get('line')
        start_side = review_comment.get('start_side')
        side = review_comment.get('side')
        diff_hunk = review_comment.get('diff_hunk')
        position = review_comment.get('position')

        # Validate that start_line precedes line
        # if start_line is not None and line is not None and start_line >= line:
        #     print(f"Invalid comment data: start_line ({start_line}) must be less than line ({line}).")
        #     continue

        if body and path and commit_id and start_line and line and start_side and side:
            print("body: ", body)
            print("path: ", path)
            print("commit_id: ", commit_id)
            # print("start_line: ", start_line)
            # print("line: ", line)
            # print("start_side: ", start_side)
            print("side: ", side)
            print("pr_number", pr_number)
            print("repo_name", repo_name)
            print("diff_hunk", diff_hunk)
            print("position", position)
            print("_______________")
            if side == "RIGHT":
                post_review_comment_on_line(pr_number, repo_name, path, body, commit_id,side, diff_hunk, position)

        # print(i,openai_review_concatenated[i].path)
        # print(i,openai_review_concatenated[i].position)
    # print("individual comment")
    # review_comments_on_lines(files)
    # print(f'comment posted on #{pr_number} in repository {repo_name}')
    return {
        'statusCode': 200,
        'body': json.dumps(f'comment posted on #{pr_number} in repository {repo_name}')
    }


def openai_review_comments(files, pr_number, repo_name):
    openai_review_concatenated = []
    if len(files) >= 10:
        num_batches = len(files) // 10
        batch_size = (len(files) + num_batches - 1) // num_batches
        batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]
        for batch in batches:
            concatenated_patch = ''.join(file.get('patch', '') for file in batch)
            batch_review = generate_openai(get_context(concatenated_patch))
            openai_review_concatenated.extend(batch_review)
    else:
        patch = get_patch_from_pr(pr_number, repo_name)
        context = get_context(patch)
        openai_review_concatenated = generate_openai(context)

    # Convert the list of review comments to a single object
    return openai_review_concatenated



def generate_openai(context):
    openai_response = []  # Initialize an empty string to accumulate response content

    tools = [
        {
            "type": "function",
            "function": {
                "name": "post_review_comment_on_line",
                "description": "Post a review comment on a specific range of lines in a file within a commit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "body": {
                            "type": "string",
                            "description": "The body text of the review comment to be posted."
                        },
                        "path": {
                            "type": "string",
                            "description": "The path to the file in which the review comment will be posted."
                        },
                        "commit_id": {
                            "type": "string",
                            "description": "The ID of the commit that contains the modified file."
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "The starting line number of the range in the file where the comment should be applied."
                        },
                        "line": {
                            "type": "integer",
                            "description": "The ending line number of the range in the file where the comment should be applied."
                        },
                        "start_side": {
                            "type": "string",
                            "description": "The side of the diff where the comment starts. LEFT for deleted lines and RIGHT for added lines.",
                            "enum": ["LEFT", "RIGHT"]
                        },
                        "side": {
                            "type": "string",
                            "description": "The side of the diff where the comment ends. LEFT for deleted lines and RIGHT for added lines.",
                            "enum": ["LEFT", "RIGHT"]
                        },
                        "diff_hunk": {
                            "type": "string",
                            "description": "The diff hunk of the comment."
                        },
                        "position": {
                            "type": "integer",
                            "description": "The line number in the file where the comment should be applied."
                        },
                        "in_reply_to": {
                            "type": "string",
                            "description": "The ID of the review comment to which the new comment should be a reply."
                        },
                        "subject_type": {
                            "type": "string",
                            "description": "The type of the subject of the review comment. Can be either 'REVIEW' or 'ISSUE'.",
                        }
                    },
                    "required": ["path", "body", "commit_id", "start_line", "line", "start_side", "side", "diff_hunk", "position"]
                }
            }
        }
    ]


    # Create a streaming completion request
    stream = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": context}
        ],
        tools=tools,
        # stream=True  # Enable streaming
    )
    # print("context",context)
    # Extract tool calls from the response
    choices = stream.choices
    # print(choices)
    for choice in choices:
        if hasattr(choice.message, 'tool_calls'):
            for tool_call in choice.message.tool_calls:
                if tool_call.function:
                    function_arguments = tool_call.function.arguments
                    if function_arguments:
                        try:
                            # Load the function arguments as JSON
                            arguments_dict = json.loads(function_arguments)
                            # Extract the 'body' field
                            body = arguments_dict.get('body')
                            path = arguments_dict.get('path')
                            commit_id = arguments_dict.get('commit_id')
                            start_line = arguments_dict.get('start_line')
                            line = arguments_dict.get('line')
                            start_side = arguments_dict.get('start_side')
                            side = arguments_dict.get('side')
                            diff_hunk = arguments_dict.get('diff_hunk')

                            position = arguments_dict.get('position')
                            in_reply_to = arguments_dict.get('in_reply_to')
                            subject_type = arguments_dict.get('subject_type')
                            # print("Extracted body:", body)
                            # print('path,',path)
                            # print('position',position)
                            openai_response.append({
                                "body":body,
                                "path":path,
                                "commit_id":commit_id,
                                "start_line":start_line,
                                "line":line,
                                "start_side":start_side,
                                "side":side,
                                "diff_hunk":diff_hunk,

                                "position":position,
                                "in_reply_to":in_reply_to,
                                "subject_type":subject_type
                            })
                        except json.JSONDecodeError as e:
                            print("Error decoding JSON:", e)
                    else:
                        print("Function arguments are empty.")
    # print('openai_response',openai_response)
    return openai_response


def fetch_commit_id(pr_number, repo_name):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}/commits'
    response = requests.get(url, headers=get_headers())
    data = response.text
    # commit_id = data['head']['sha']
    print("response", data)
    return response



def post_review_comment_on_line(pr_number, repo_name, path, body, commit_id, side, diff_hunk, position):
    
    # Validate that required fields are not None
    if path is None or body is None or commit_id is None:
        raise ValueError("Missing required fields.")

    if side != "RIGHT":
        print(f"Skipping comment on side {side} for path {path}.")
        return None
    
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}/comments'
    data = {
        "body": body,
        "path": path,
        "commit_id": commit_id,
        # "start_line": start_line,
        # "line": line,
        # "start_side": start_side,
        "side": side,
        "diff_hunk": diff_hunk,
        "position": position
    }

    # Remove keys with None values to avoid sending unnecessary fields
    data = {k: v for k, v in data.items() if v is not None}

    response = requests.post(url, headers=get_headers(), data=json.dumps(data))
    print("posting completed")
    print(response.json())
    return response.json()



if __name__ == '__main__':
    with open('sample_event.json', 'r') as fileVariable:
        event_text = json.load(fileVariable)

    # event = ast.literal_eval(event_text)
    # event = json.loads(event_text)
    context = ''
    lambda_handler(event_text, context)