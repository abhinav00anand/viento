import requests

headers = {'Authorization': 'Bearer sk-lit-698f2cfc-3fe8-433d-98da-b03aa08d5037'}
project_id = '01kjd0z4rx2vr6ke3y8e07en7z'
r = requests.get(f'https://lightning.ai/v1/projects/{project_id}/cloudspaces', headers=headers)
data = r.json()
cloudspaces = data.get('cloudspaces', [])
print(f'Number of cloudspaces: {len(cloudspaces)}')
for cs in cloudspaces:
    name = cs.get('name')
    phase = cs.get('status', {}).get('phase')
    spec = cs.get('spec', {}).get('instanceType')
    print(f"Name: {name} | Phase: {phase} | Machine: {spec}")
