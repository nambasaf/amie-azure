import os
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

load_dotenv()

PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")

agents_client = AgentsClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_managed_identity_credential=True
    ),
)

print("Deleting all threads...\n")

for thread in agents_client.threads.list():
    print("Deleting:", thread.id)
    agents_client.threads.delete(thread.id)

print("\n✅ Thread cleanup complete.")
