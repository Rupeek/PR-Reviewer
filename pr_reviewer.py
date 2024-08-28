import hashlib
import os
import json
import requests
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
    api_key=TOKEN_OPENAI,
)

# Headers for GitHub API
def get_headers():
    return {
        'Authorization': f'token {TOKEN}',
        'Accept': 'application/vnd.github.v3.diff',
    }

def get_patch_from_pr(pr_number, repo_name):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}'
    response = requests.get(url, headers=get_headers())
    response.raise_for_status()  # Ensure we raise an error for bad responses
    return response.text

def get_context(patch):
    prompt = ''
    with open('prompt.txt', 'r') as file:
        prompt = file.read()
    return prompt + patch

def get_pull_request_files(pr_number, repo_name):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}/files'
    response = requests.get(url, headers=get_headers())
    response.raise_for_status()  # Ensure we raise an error for bad responses
    return response.json()

def verify_signature(payload, signature, secret):
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = 'sha256=' + mac.hexdigest()
    return hmac.compare_digest(expected_signature, signature)

def authenticate_request(event, context):
    authenticated = True
    response = ''
    headers = event.get('headers', {})
    signature = headers.get('x-hub-signature-256')
    
    if not signature:
        authenticated = False
        response = {'statusCode': 400, 'body': 'Missing signature'}
    
    payload = event.get('body', '').encode()
    if not verify_signature(payload, signature, WEBHOOK_SECRET):
        authenticated = False
        response = {'statusCode': 400, 'body': 'Invalid signature'}

    return authenticated, response

def lambda_handler(event, context):
    authenticated, response = authenticate_request(event, context)
    if not authenticated:
        return response
    
    try:
        payload = json.loads(event.get('body', '{}'))
    except (KeyError, json.JSONDecodeError):
        return {'statusCode': 400, 'body': json.dumps('Invalid payload format')}

    action = payload.get('action')
    if action in ['opened', 'synchronize']:
        pr_number = payload['pull_request']['number']
        repo_name = payload['repository']['name']
        print(f"Pull request opened: #{pr_number} in repository {repo_name}")

        files = get_pull_request_files(pr_number, repo_name)
        commit_id = payload['pull_request']['head']['sha']
        openai_review_concatenated = openai_review_comments(files, pr_number, repo_name)
        post_line_level_comment(pr_number, repo_name, commit_id, openai_review_concatenated)
        
        return {'statusCode': 200, 'body': json.dumps(f'Comment posted on #{pr_number} in repository {repo_name}')}
    
    return {'statusCode': 200, 'body': json.dumps('Not a pull request opened event.')}

def adjust_line_numbers(diff_hunk, comments):
    """
    Adjust the line numbers for comments based on the diff hunks.
    
    diff_hunk: str - The diff hunk containing the changes.
    comments: list - A list of comments where each comment contains the original line number.
    
    Returns:
        list - A list of adjusted line numbers for each comment.
    """
    line_number_adjustments = []
    hunk_lines = diff_hunk.split('\n')

    for comment in comments:
        comment_line = comment.get('position')
        if comment_line is None:
            continue

        adjusted_line_number = comment_line
        for hunk_line in hunk_lines:
            if hunk_line.startswith('@@'):
                parts = hunk_line.split()
                old_start = int(parts[1].split(',')[0][1:])
                new_start = int(parts[2].split(',')[0][1:])
                old_length = int(parts[1].split(',')[1])
                
                if old_start <= comment_line < old_start + old_length:
                    adjusted_line_number = new_start + (comment_line - old_start)
                    break

        line_number_adjustments.append(adjusted_line_number)
    
    return line_number_adjustments

def post_line_level_comment(pr_number, repo_name, commit_id, comments):
    """
    Post comments to the specific lines in a pull request based on the adjusted positions.
    
    pr_number: int - The pull request number.
    repo_name: str - The name of the repository.
    commit_id: str - The commit ID.
    comments: list - A list of comments to post.
    """
    for comment in comments:
        path = comment.get('path')
        body = comment.get('body')
        side = comment.get('side')
        diff_hunk = comment.get('diff_hunk')
        position = comment.get('position')
        
        # Check for required fields and valid values
        if not path or not body or not commit_id or position is None or position <= 0:
            print(f"Invalid comment data: path={path}, body={body}, commit_id={commit_id}, position={position}")
            continue
        
        if side != "RIGHT":
            print(f"Skipping comment on side {side} for path {path}.")
            continue
        
        if not diff_hunk:
            print(f"Missing diff_hunk for path {path}. Comment not posted.")
            continue
        
        # Adjust position numbers based on the diff hunk
        adjusted_positions = adjust_line_numbers(diff_hunk, [comment])
        if not adjusted_positions:
            print(f"Unable to adjust position for comment. Skipping.")
            continue
        
        adjusted_position = adjusted_positions[0]

        print("position", adjusted_position)
        url = f'https://api.github.com/repos/{REPO_OWNER}/{repo_name}/pulls/{pr_number}/comments'
        data = {
            "body": body,
            "path": path,
            "commit_id": commit_id,
            "side": side,
            "diff_hunk": diff_hunk,
            "position": adjusted_position
        }

        response = requests.post(url, headers=get_headers(), data=json.dumps(data))
        
        if response.status_code != 201:
            print(f"Failed to post comment. Status code: {response.status_code}, Response: {response.json()}")
        else:
            print(f"Comment posted successfully on line {adjusted_position}")
            print(response.json())

def openai_review_comments(files, pr_number, repo_name):
    """
    Generate review comments from OpenAI based on the diff patches.
    
    files: list - List of files in the pull request.
    pr_number: int - The pull request number.
    repo_name: str - The name of the repository.
    
    Returns:
        list - A list of comments to post.
    """
    openai_review_concatenated = []
    if len(files) >= 10:
        num_batches = (len(files) + 9) // 10
        batches = [files[i * 10:(i + 1) * 10] for i in range(num_batches)]
        for batch in batches:
            concatenated_patch = ''.join(file.get('patch', '') for file in batch)
            batch_review = generate_openai(get_context(concatenated_patch))
            openai_review_concatenated.extend(batch_review)
    else:
        patch = get_patch_from_pr(pr_number, repo_name)
        context = get_context(patch)
        openai_review_concatenated = generate_openai(context)

    return openai_review_concatenated

def generate_openai(context):
    """
    Generate comments from OpenAI based on the provided context.
    
    context: str - The context containing the diff information.
    
    Returns:
        list - A list of comments with positions and other details.
    """
    openai_response = []
    tools = [
        {
            "type": "function",
            "function": {
                "name": "post_review_comment_on_line",
                "description": "Post a review comment on a specific line of a file within a commit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "body": {"type": "string", "description": "The body text of the review comment."},
                        "path": {"type": "string", "description": "The path to the file."},
                        "commit_id": {"type": "string", "description": "The ID of the commit."},
                        "side": {"type": "string", "description": "The side of the diff. LEFT for deleted lines, RIGHT for added lines.", "enum": ["LEFT", "RIGHT"]},
                        "diff_hunk": {"type": "string", "description": "The diff hunk where the comment is applied."},
                        "position": {"type": "integer", "description": "The line number where the comment is applied."}
                    },
                    "required": ["path", "body", "commit_id", "side", "diff_hunk", "position"]
                }
            }
        }
    ]

    stream = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": context}],
        tools=tools,
    )

    choices = stream.choices
    for choice in choices:
        if hasattr(choice.message, 'tool_calls'):
            for tool_call in choice.message.tool_calls:
                if tool_call.function:
                    function_arguments = tool_call.function.arguments
                    if function_arguments:
                        try:
                            arguments_dict = json.loads(function_arguments)
                            # Ensure all required fields are present and valid
                            if all(key in arguments_dict for key in ["body", "path", "commit_id", "side", "diff_hunk", "position"]):
                                # Add to response with adjusted positions
                                openai_response.append({
                                    "body": arguments_dict.get('body'),
                                    "path": arguments_dict.get('path'),
                                    "commit_id": arguments_dict.get('commit_id'),
                                    "side": arguments_dict.get('side'),
                                    "diff_hunk": arguments_dict.get('diff_hunk'),
                                    "position": arguments_dict.get('position')
                                })
                            else:
                                print(f"Missing fields in OpenAI response: {arguments_dict}")
                        except (json.JSONDecodeError, TypeError) as e:
                            print(f"Error processing tool call arguments: {e}")
                    else:
                        print("Function arguments are empty.")
    
    return openai_response

if __name__ == '__main__':
    with open('sample_event.json', 'r') as fileVariable:
        event_text = json.load(fileVariable)

    context = ''
    lambda_handler(event_text, context)
