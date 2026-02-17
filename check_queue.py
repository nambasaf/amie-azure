import os
from azure.storage.queue import QueueClient
from dotenv import load_dotenv

load_dotenv()

conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
if not conn_str:
    print("No AZURE_STORAGE_CONNECTION_STRING found in .env")
    exit(1)

queue_name = "idca-queue"
queue_client = QueueClient.from_connection_string(conn_str, queue_name)

try:
    props = queue_client.get_queue_properties()
    print(f"Messages in '{queue_name}': {props.approximate_message_count}")
    
    # Peek at the first message if it exists
    messages = queue_client.peek_messages(max_messages=1)
    if messages:
        print(f"First message body: {messages[0].content}")
    else:
        print("Queue is empty.")
except Exception as e:
    print(f"Error: {e}")
