# PR-Reviewer
Lambda function for automated PR reviews

To run on local - 

1. install the openai and requests modules.
2. Create logic for a main function in the python code as below
     with open('sample_event.txt', 'r') as file:
          event_text = file.read()
  
      event = ast.literal_eval(event_text)
      context = ''
      lambda_handler(event, context)

3. Get openai keys, Github personal access token to access the respective apis. 
