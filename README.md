# PR-Reviewer
Lambda function for automated PR reviews

# To run on local - 

1. install the openai and requests modules.
2. Uncomment the main logic at the end of the python file.
3. Get openai keys, Github personal access token to access the respective apis.

   
# To install as a Lambda function 
1. Create a Python 3.10 runtime layer that provides the openai, requests and json libraries
2. Create a Python 3.10 lambda that uses the above layer and the code from the pr_reviewer.py.
3. create the prompt.txt file in the lambda file structure.
4. Enable github webhooks for your organisation, use the lambda url as a listener.
5. Select "Pull Request" event for listening.


