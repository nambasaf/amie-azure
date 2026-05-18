import os
import json
from dotenv import dotenv_values

print("Running environment synchronization...")

env = dotenv_values('.env')
files = [
    'backend/ingestion-agent/local.settings.json',
    'backend/idca_func/local.settings.json',
    'backend/naa-amie-azure-clean/local.settings.json',
    'backend/aa/local.settings.json'
]

for f in files:
    try:
        if not os.path.exists(f) or os.stat(f).st_size == 0:
            with open(f, 'w') as fh:
                json.dump({'IsEncrypted': False, 'Values': env}, fh, indent=2)
            print(f"Created and populated {f}")
        else:
            try:
                with open(f, 'r') as fh:
                    data = json.load(fh)
            except json.JSONDecodeError:
                data = {}
            
            if 'Values' not in data:
                data['Values'] = {}
                
            for k, v in env.items():
                if v is not None:
                    data['Values'][k] = v
                    
            with open(f, 'w') as fh:
                json.dump(data, fh, indent=2)
            print(f"Updated {f}")
    except Exception as e:
        print(f"Failed to process {f}: {e}")

print("Environment synchronization complete.")
