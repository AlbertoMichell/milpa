import requests
import time
from datetime import datetime, timedelta

BASE_URL = 'http://127.0.0.1:4000'

def test_api():
    print(f'Testing {BASE_URL}...')
    
    # 1) GET / confirmed HTML
    try:
        r = requests.get(BASE_URL)
        print(f'1) GET / Status: {r.status_code}, Content-Type: {r.headers.get("Content-Type")}')
        if 'text/html' not in r.headers.get('Content-Type', ''):
            print('Error: Root is not HTML')
    except Exception as e:
        print(f'Error connecting to {BASE_URL}: {e}')
        return

    # 2) POST /api/auth/login (testuser/123456)
    login_data = {'username': 'testuser', 'password': '123456'}
    r = requests.post(f'{BASE_URL}/api/auth/login', json=login_data)
    print(f'2) POST /api/auth/login (testuser): {r.status_code}')
    testuser_token = r.json().get('token') if r.status_code == 200 else None

    # 3) GET /api/datasets/users
    if testuser_token:
        headers = {'Authorization': f'Bearer {testuser_token}'}
        r = requests.get(f'{BASE_URL}/api/datasets/users', headers=headers)
        print(f'3) GET /api/datasets/users: {r.status_code}, User count: {len(r.json()) if isinstance(r.json(), list) else "N/A"}')
    else:
        print('Skipping 3: testuser login failed')

    # 4) Register new user
    timestamp = int(time.time())
    new_username = f'nuevo_user_{timestamp}'
    reg_data = {'username': new_username, 'password': '123456'}
    r = requests.post(f'{BASE_URL}/api/auth/register', json=reg_data)
    print(f'4) POST /api/auth/register ({new_username}): {r.status_code}')
    
    # Login with new user
    r = requests.post(f'{BASE_URL}/api/auth/login', json=reg_data)
    print(f'4b) POST /api/auth/login ({new_username}): {r.status_code}')
    new_user_data = r.json()
    new_user_token = new_user_data.get('token')
    new_user_id = new_user_data.get('user', {}).get('id')

    if not new_user_token or not new_user_id:
        print('Failed to get new user credentials')
        return

    headers_new = {'Authorization': f'Bearer {new_user_token}'}

    # 5a) GET /api/ai/crops/{newUserId}
    r = requests.get(f'{BASE_URL}/api/ai/crops/{new_user_id}', headers=headers_new)
    print(f'5a) GET /api/ai/crops/{new_user_id}: {r.status_code}')

    # 5b) POST /api/datasets/bootstrap
    bootstrap_data = {
        'target_user_id': new_user_id,
        'clear_existing': True,
        'weeks': 12,
        'interval_days': 7
    }
    r = requests.post(f'{BASE_URL}/api/datasets/bootstrap', json=bootstrap_data, headers=headers_new)
    print(f'5b) POST /api/datasets/bootstrap: {r.status_code}')

    # 5c) GET /api/ai/crops/{newUserId}
    r = requests.get(f'{BASE_URL}/api/ai/crops/{new_user_id}', headers=headers_new)
    crops = r.json()
    print(f'5c) GET /api/ai/crops/{new_user_id}: {r.status_code}, Crop count: {len(crops) if isinstance(crops, list) else 0}')
    
    if not isinstance(crops, list) or len(crops) == 0:
        print('No crops found after bootstrap')
        return

    first_crop_id = crops[0].get('id')

    # 5d) GET /api/ai/sensors/{firstCropId}?limit=240
    r = requests.get(f'{BASE_URL}/api/ai/sensors/{first_crop_id}?limit=240', headers=headers_new)
    sensor_data = r.json()
    print(f'5d) GET /api/ai/sensors/{first_crop_id}: {r.status_code}, Reading count: {len(sensor_data) if isinstance(sensor_data, list) else 0}')

    # 6) Calculate weekly differences
    if isinstance(sensor_data, list) and len(sensor_data) > 0:
        # Sort and interpret timestamps
        # Assuming entries have 'timestamp' or 'date'
        readings = []
        for d in sensor_data:
            ts_str = d.get('timestamp') or d.get('date')
            if ts_str:
                try:
                    # Generic ISO format or similar
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    readings.append(dt)
                except:
                    continue
        
        readings.sort()
        
        if readings:
            # Group by week (Monday start) - one point per week
            weekly_points = {}
            for dt in readings:
                monday = dt - timedelta(days=dt.weekday())
                week_key = monday.date()
                if week_key not in weekly_points:
                    weekly_points[week_key] = dt
            
            sorted_weeks = sorted(weekly_points.keys())
            gaps = []
            for i in range(len(sorted_weeks) - 1):
                diff = (sorted_weeks[i+1] - sorted_weeks[i]).days
                gaps.append(diff)
            
            print(f'6) Calculated weekly gaps (days) for first 5: {gaps[:5]}')
        else:
            print('6) No valid timestamps found to calculate gaps')

test_api()
